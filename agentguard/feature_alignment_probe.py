"""Development-only test of feature mean alignment with a frozen DreamGuard."""
import argparse
import json
from pathlib import Path
from hashlib import sha256
import torch
from .dream_transfer import target_rows
from .dreamguard_training import Encoder, atomic_json
from .dreamguard_model import RiskWorldModel, ModelConfig
from .dreamguard_runtime import predict, policy_config
from .dreamguard_policy import metrics, Evidence


def centroid(rows, field):
    return torch.stack([r[field] if field == "task" else r[field].mean(0) for r in rows]).mean(0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    checkpoint = args.source / "risk-checkpoint.pt"
    saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
    artifact = json.loads((args.source / "calibration.json").read_bytes())
    if sha256(checkpoint.read_bytes()).hexdigest() != artifact["checkpoint_sha256"]:
        raise ValueError("Source policy/checkpoint mismatch")
    model = RiskWorldModel(config=ModelConfig(**saved["model_config"])).cuda().eval()
    model.load_state_dict(saved["model"])
    cache = torch.load(args.source / "source-features.pt", map_location="cpu", weights_only=True)
    source = [r for r in cache["rows"] if r["split"] == "train"]
    rows = target_rows(Path("data/ATBench/test.json"), Path("splits/atbench-v1.json"), "calibration")
    rows.sort(key=lambda r:sha256(r["id"].encode()).digest())
    fit, val = rows[:40], rows[40:80]
    fields = ("task", "actions", "observations")
    encoder = Encoder(Path("models/qwen3-4b-instruct-2507"), "cuda", batch_size=1)
    for r in fit + val:
        for f in fields:
            if f == "task":
                r[f] = encoder.encode(r[f])[0]
            else:
                r[f] = torch.stack([encoder.encode(t)[0] for t in r[f]])
    policy = artifact["config"]
    destination = {f:centroid(fit,f) for f in fields}
    shifts = {f:centroid(source,f)-destination[f] for f in fields}
    summary = {}
    for name, aligned in (("original",()), ("task_alignment",("task",)), ("action_alignment",("actions",)),
                          ("all_alignment", fields)):
        inputs = [{**r, **{f:r[f]+shifts[f] for f in aligned}} for r in val]
        scores = predict(model, inputs, "cuda")
        summary[name] = metrics(scores, policy)
        atomic_json(args.out / (name + ".json"), scores)
    # Same task and empty first observation; substitute another observed action.
    # Synthetic alternatives are used only to measure sensitivity, never as labeled examples.
    def first_block(r):
        h,p = r["hazard_scores"][0],r["prefix_scores"][0]
        return Evidence().propose(h,p,policy_config(policy))[2]
    first = [{**r,"actions":r["actions"][:1],"observations":r["observations"][:1]} for r in val]
    baseline = predict(model, first, "cuda")
    sensitivity = {}
    for field in ("task","actions"):
        swapped = [{**r,field:first[(i+1)%len(first)][field]} for i,r in enumerate(first)]
        scores = predict(model, swapped, "cuda")
        sensitivity[field] = sum(first_block(a)!=first_block(b) for a,b in zip(baseline,scores))
    report = dict(metrics=summary, first_decisions_changed=sensitivity, fit_ids=[r["id"] for r in fit],
                  validation_ids=[r["id"] for r in val], source_checkpoint=artifact["checkpoint_sha256"])
    atomic_json(args.out / "summary.json",report)
    print(json.dumps(summary), sensitivity, flush=True)


if __name__ == "__main__":
    main()
