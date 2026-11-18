"""Train a documented DreamGuard reproduction and transfer it to ATBench."""

import argparse
import json
import math
import random
from collections import Counter
from hashlib import sha256
from pathlib import Path
from time import perf_counter

import numpy as np
import torch
import yaml
from torch.nn.utils.rnn import pad_sequence

from .atbench import read_rows, read_split, replay_reviews
from .dreamguard_model import RiskWorldModel, safety_loss, world_loss
from .guard import json_text, write_record
from .safetydrift import collect, original_split
from .traces import content_text, tool_text

SEED = 20260701


def source_examples(root):
    scenarios = {item["id"]: item for path in (root / "scenarios").rglob("*.yaml")
                 if (item := yaml.safe_load(path.read_bytes()))}
    cases = collect(root)
    train, calibration = original_split(cases)
    split = {row["path"]: name for name, rows in (("train", train), ("calibration", calibration))
             for row in rows}
    examples = []
    for case in cases:
        trajectory = json.loads((root / case["path"]).read_bytes())
        task = scenarios[case["scenario_id"]]["task_prompt"]
        observations, actions, successors = [], [], []
        observation = ""
        for step in trajectory["steps"]:
            raw = step["action"]
            call = raw.get("tool_call")
            action = (json_text({"name": call["tool_name"], "arguments": call["arguments"]})
                      if call else json_text({"response": raw.get("raw_text", "")}))
            observations.append(observation)
            actions.append(action)
            observation = step["observation"]["content"]
            successors.append(observation)
        first = next((i for i, step in enumerate(trajectory["steps"])
                      if step["safety_state_after"]["risk_level"] == 4), None)
        examples.append({
            "id": case["path"], "split": split[case["path"]], "task": task,
            "observations": observations, "actions": actions, "successors": successors,
            "first_hazard": first, "label": int(case["reached_violation"]),
        })
    # Exact repeated trajectories belong to one split.
    unique = {}
    for example in examples:
        key = sha256(json_text([example["task"], example["observations"], example["actions"],
                               example["successors"], example["first_hazard"]]).encode()).hexdigest()
        unique.setdefault(key, example)
    return list(unique.values()), len(examples) - len(unique)


def target_examples(path, split_path):
    split = read_split(split_path)
    digest, rows = read_rows(path, "ATBench", list(map(str, split["splits"]["heldout"])), None)
    if digest != split["source_sha256"]:
        raise ValueError("ATBench data does not match the frozen split")
    examples = []
    for case_id, label, context in rows:
        observations, actions, task = [], [], None
        for _, review in replay_reviews(context):
            task = review.task
            observations.append(next(
                (content_text(m.get("content")) for m in reversed(review.history)
                 if m["role"] in ("tool", "environment")), "",
            ))
            actions.append(json_text(review.candidate) if "response" in review.candidate else tool_text(review.candidate))
        if not actions:
            raise ValueError(f"ATBench {case_id} has no recorded action")
        examples.append({"id": case_id, "split": "heldout", "task": task, "observations": observations,
                         "actions": actions, "successors": [], "label": label, "first_hazard": None})
    return examples


class Encoder:
    def __init__(self, observer, device):
        from transformers import AutoModel, AutoTokenizer

        self.device = device
        self.tokenizer = AutoTokenizer.from_pretrained(observer)
        self.model = AutoModel.from_pretrained(observer, dtype=torch.bfloat16).to(device).eval()
        self.dimension = self.model.config.hidden_size
        self.cache = {}

    def encode(self, text):
        if text in self.cache:
            return self.cache[text], 0.0
        if self.device.startswith("cuda"):
            torch.cuda.synchronize()
        started = perf_counter()
        tokens = self.tokenizer(text or "[No observation]", return_tensors="pt", truncation=True,
                                max_length=2048).to(self.device)
        with torch.inference_mode():
            hidden = self.model(**tokens, output_hidden_states=True, use_cache=False).hidden_states[31]
            vector = hidden[0].float().mean(0).cpu()
        if self.device.startswith("cuda"):
            torch.cuda.synchronize()
        self.cache[text] = vector
        return vector, perf_counter() - started


def extract(examples, encoder, path):
    partial = path.with_name("features-partial.pt")
    encoded = torch.load(partial, map_location="cpu", weights_only=True) if partial.exists() else []
    if [row["id"] for row in encoded] != [row["id"] for row in examples[:len(encoded)]]:
        raise ValueError("Partial feature cache does not match this run")
    for index in range(len(encoded), len(examples)):
        example = examples[index]
        instruction, instruction_seconds = encoder.encode(example["task"])
        record = {key: example[key] for key in ("id", "split", "label", "first_hazard")}
        record["task"] = instruction
        seconds = []
        for kind in ("observations", "actions", "successors"):
            vectors, times = [], []
            for text in example[kind]:
                vector, elapsed = encoder.encode(text)
                vectors.append(vector)
                times.append(elapsed)
            record[kind] = torch.stack(vectors) if vectors else torch.empty(0, encoder.dimension)
            if kind in ("observations", "actions"):
                seconds.append(times)
        record["embedding_seconds"] = [a + b for a, b in zip(*seconds)]
        record["embedding_seconds"][0] += instruction_seconds
        encoded.append(record)
        if (index + 1) % 10 == 0:
            temporary = partial.with_suffix(".tmp")
            torch.save(encoded, temporary)
            temporary.replace(partial)
            print(json_text({"phase": "embedding", "completed": index + 1, "total": len(examples)}), flush=True)
    temporary = path.with_suffix(".tmp")
    torch.save(encoded, temporary)
    temporary.replace(path)
    return encoded


def batch(rows, device):
    lengths = torch.tensor([len(row["actions"]) for row in rows], device=device)
    masks = torch.arange(int(lengths.max()), device=device)[None] < lengths[:, None]
    tensors = [pad_sequence([row[key] for row in rows], batch_first=True).to(device)
               for key in ("observations", "actions", "successors")]
    task = torch.stack([row["task"] for row in rows]).to(device)
    hazard = torch.zeros_like(masks, dtype=torch.float32)
    prefix = torch.zeros_like(hazard)
    safety_mask = masks.clone()
    for i, row in enumerate(rows):
        first = row["first_hazard"]
        if first is not None:
            hazard[i, first] = 1.0
            prefix[i, first] = 1.0
            for previous in range(max(0, first - 3), first):
                prefix[i, previous] = math.exp(-(first - previous - 1) / 1.5)
            safety_mask[i, first + 1:] = False
    return task, tensors, masks, hazard, prefix, safety_mask


def train(model, rows, directory, device):
    for stage_index, (stage, epochs) in enumerate((("world", 10), ("risk", 12))):
        torch.manual_seed(SEED + stage_index)
        rng = random.Random(SEED + stage_index)
        checkpoint = directory / f"{stage}.pt"
        if checkpoint.exists():
            model.load_state_dict(torch.load(checkpoint, map_location=device, weights_only=True))
            continue
        if stage == "risk":
            for parameter in model.transition.parameters():
                parameter.requires_grad = False
            for parameter in model.transition_norm.parameters():
                parameter.requires_grad = False
        parameters = [p for p in model.parameters() if p.requires_grad]
        if stage == "risk":
            heads = list(model.hazard.parameters()) + list(model.prefix.parameters()) + list(model.adapter.parameters())
            head_ids = {id(p) for p in heads}
            parameters = [{"params": heads, "lr": 2e-4},
                          {"params": [p for p in parameters if id(p) not in head_ids], "lr": 5e-5}]
        optimizer = torch.optim.AdamW(parameters, lr=2e-4)
        with (directory / f"{stage}.jsonl").open("x") as log:
            for epoch in range(epochs):
                model.train()
                indices = list(range(len(rows)))
                rng.shuffle(indices)
                losses = []
                for start in range(0, len(indices), 8):
                    selected = [rows[i] for i in indices[start:start + 8]]
                    task, tensors, masks, hazard, prefix, safety_mask = batch(selected, device)
                    optimizer.zero_grad(set_to_none=True)
                    result = model(task, *tensors)
                    loss = (world_loss(result, tensors[-1], masks) if stage == "world"
                            else safety_loss(result, hazard, prefix, safety_mask))
                    if not torch.isfinite(loss):
                        raise ValueError(f"Non-finite {stage} loss")
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 10.0)
                    optimizer.step()
                    losses.append(loss.item())
                record = {"phase": stage, "epoch": epoch + 1, "epochs": epochs,
                          "mean_loss": sum(losses) / len(losses)}
                write_record(log, record)
                print(json_text(record), flush=True)
        temporary = checkpoint.with_suffix(".tmp")
        torch.save(model.state_dict(), temporary)
        temporary.replace(checkpoint)


def predict(model, rows, device):
    model.eval()
    result = []
    with torch.inference_mode():
        for row in rows:
            task = row["task"][None].to(device)
            hidden = model.initial(task)
            hazard, prefix, durations = [], [], []
            for observation, action in zip(row["observations"], row["actions"]):
                if device.startswith("cuda"):
                    torch.cuda.synchronize()
                started = perf_counter()
                hidden, immediate, future, _, _ = model.step(
                    hidden, observation[None].to(device), action[None].to(device), task,
                )
                hazard.append(immediate.sigmoid().item())
                prefix.append(future.sigmoid().item())
                if device.startswith("cuda"):
                    torch.cuda.synchronize()
                durations.append(perf_counter() - started)
            result.append({**row, "hazard_scores": hazard, "prefix_scores": prefix, "head_seconds": durations})
    return result


def fused(hazard, prefix, beta, window, weights):
    ema, buffer, output = 0.0, [], []
    for immediate, future in zip(hazard, prefix):
        ema = beta * ema + (1 - beta) * future
        buffer = [*buffer, future][-window:]
        channels = (immediate, ema, sum(buffer) / len(buffer))
        output.append(1 - math.prod(1 - min(1.0, value * weight)
                                   for value, weight in zip(channels, weights)))
    return output


def threshold(scores, alpha):
    scores = sorted(scores)
    if not scores:
        raise ValueError("No safe trajectories in calibration set")
    return scores[min(math.ceil((len(scores) + 1) * (1 - alpha)), len(scores)) - 1]


def first_intervention(row, config):
    risk = fused(row["hazard_scores"], row["prefix_scores"], config["beta"], config["window"], config["weights"])
    return next((i for i, (hazard, score) in enumerate(zip(row["hazard_scores"], risk))
                 if hazard >= config["block_threshold"] or score >= config["hold_threshold"]), None)


def metrics(rows, config):
    counts = Counter((row["label"], int(first_intervention(row, config) is not None)) for row in rows)
    tp, fp, tn, fn = [counts[pair] for pair in ((1, 1), (0, 1), (0, 0), (1, 0))]
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "f1": 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "fpr": fp / (fp + tn) if fp + tn else None}


def calibrate(rows):
    safe = [row for row in rows if row["label"] == 0]
    block = threshold([max(row["hazard_scores"]) for row in safe], 0.01)
    best = None
    for beta in (0.35, 0.5, 0.65, 0.8):
        for window in (2, 3, 4):
            for weights in ((1, 1, 1), (1, 0.5, 0.5), (1, 0.25, 0.25)):
                config = {"beta": beta, "window": window, "weights": weights, "block_threshold": block}
                maxima = [max(fused(r["hazard_scores"], r["prefix_scores"], beta, window, weights)) for r in safe]
                config["hold_threshold"] = threshold(maxima, 0.05)
                scored = metrics(rows, config)
                if best is None or scored["f1"] > best["calibration_metrics"]["f1"]:
                    best = {**config, "calibration_metrics": scored}
    return best


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--safetydrift-root", type=Path, required=True)
    parser.add_argument("--observer", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=Path("data/ATBench/test.json"))
    parser.add_argument("--split-manifest", type=Path, default=Path("splits/atbench-v1.json"))
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    directory = args.out_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    source, duplicates = source_examples(args.safetydrift_root)
    target = target_examples(args.data, args.split_manifest)
    examples = source + target
    manifest = {
        "variant": "DreamGuard-method-reproduction", "seed": SEED, "observer": str(args.observer),
        "observer_revision": (args.observer / "revision.txt").read_text().strip(),
        "implementation_sha256": {
            name: sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
            for name in ("dreamguard.py", "dreamguard_model.py")
        },
        "torch_version": str(torch.__version__),
        "layer": 31, "pooling": "mean", "max_tokens": 2048, "dtype": "bfloat16",
        "world_epochs": 10, "risk_epochs": 12, "batch_size": 8,
        "training_source": "SafetyDrift-public-original-train",
        "calibration_source": "SafetyDrift-public-original-test",
        "evaluation": "ATBench-heldout-200", "duplicates_removed": duplicates,
        "split_counts": dict(Counter(row["split"] for row in examples)),
        "source_hash": sha256(json_text(examples).encode()).hexdigest(),
        "atbench_sha256": sha256(args.data.read_bytes()).hexdigest(),
        "split_sha256": sha256(args.split_manifest.read_bytes()).hexdigest(),
        "deviations": [
            "Independent implementation, no author checkpoint or exact cleaned split",
            "Public SafetyDrift 285/72 split repurposed as training/calibration, exact duplicates removed",
            "Raw task, previous observation and JSON action encoded separately with mean pooling and 2048-token cap",
            "512-unit single-hidden-layer MLPs, shared 256-unit residual adapter, deterministic argmax test latents",
            "Conformal false-alert budgets hold=0.05 and block=0.01; 36-configuration calibration-only fusion search",
            "ATBench transfer test uses existing 200 heldout trajectories, without ATBench tuning",
            "Native SafetyDrift risk transitions supply hazard targets; ATBench has no first-hazard annotation",
        ],
    }
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_bytes()) != manifest:
            raise ValueError("Existing run configuration differs")
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    cache = directory / "features.pt"
    if cache.exists():
        encoded = torch.load(cache, map_location="cpu", weights_only=True)
    else:
        encoder = Encoder(str(args.observer), args.device)
        encoded = extract(examples, encoder, cache)
        del encoder
        torch.cuda.empty_cache()
    model = RiskWorldModel().to(args.device)
    train(model, [row for row in encoded if row["split"] == "train"], directory, args.device)
    calibration = predict(model, [r for r in encoded if r["split"] == "calibration"], args.device)
    config = calibrate(calibration)
    (directory / "calibration.json").write_text(json.dumps(config, indent=2) + "\n")
    heldout = predict(model, [r for r in encoded if r["split"] == "heldout"], args.device)
    embedding_seconds = head_seconds = 0.0
    calls = 0
    with (directory / "atbench.jsonl").open("x") as output:
        write_record(output, {"record_type": "run_metadata", **manifest, "calibration": config})
        for row in heldout:
            intervention = first_intervention(row, config)
            reviewed = intervention + 1 if intervention is not None else len(row["actions"])
            calls += reviewed
            embedding_seconds += sum(row["embedding_seconds"][:reviewed])
            head_seconds += sum(row["head_seconds"][:reviewed])
            write_record(output, {"record_type": "case", "case_id": row["id"], "label": row["label"],
                                 "prediction": int(intervention is not None), "first_intervention": intervention,
                                 "status": "ok", "hazard_scores": row["hazard_scores"],
                                 "prefix_scores": row["prefix_scores"]})
        summary = {"record_type": "overall_summary", "total_cases": len(heldout),
                   "completed_cases": len(heldout), "error_cases": 0, **metrics(heldout, config),
                   "successful_reviews": calls, "mean_embedding_latency_seconds": embedding_seconds / calls,
                   "mean_head_latency_seconds": head_seconds / calls,
                   "mean_guard_latency_seconds": (embedding_seconds + head_seconds) / calls,
                   "latency_protocol": "cached encoder extraction plus measured sequential recurrent steps",
                   "phir": None, "mas": None}
        write_record(output, summary)
    print(json_text(summary), flush=True)


if __name__ == "__main__":
    main()
