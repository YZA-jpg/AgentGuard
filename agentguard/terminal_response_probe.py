"""Compare ATBench terminal-response serialization on a frozen DreamGuard model."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import statistics

import torch

from .dream_transfer import target_rows
from .dreamguard_data import json_text, source_examples
from .dreamguard_model import ModelConfig, RiskWorldModel
from .dreamguard_policy import metrics
from .dreamguard_runtime import predict
from .dreamguard_training import Encoder, atomic_json


def normalize(action):
    """Unwrap only a complete, unambiguous ATBench response envelope."""
    candidate = json.loads(action)
    if set(candidate) != {"response"}:
        return action
    raw = candidate["response"]
    if not isinstance(raw, str) or not raw.startswith("Complete{"):
        return action
    try:
        envelope = json.loads(raw[len("Complete"):])
    except ValueError:
        return action
    if set(envelope) != {"response"} or not isinstance(envelope["response"], str):
        return action
    # Preserve the payload verbatim, including any quotes authored by the agent.
    return json_text({"response": envelope["response"]})


def score_tools(rows, scores, names):
    data = defaultdict(list)
    lookup = {r["id"]:r for r in rows}
    for record in scores:
        row = lookup[record["id"]]
        if row["label"] != 0:
            continue
        for action, score in zip(row["actions"],record["hazard_scores"]):
            candidate = json.loads(action)
            name = candidate.get("name")
            if name in names:
                data[(name,tuple(sorted(candidate["arguments"])))].append(score)
    return [{"tool":key[0],"argument_keys":key[1],"n":len(values),
             "median_hazard":statistics.median(values)} for key,values in sorted(data.items())]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=Path("results/dreamguard-v1-v2-20261121_015401/v2"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    ckpt = args.source / "risk-checkpoint.pt"
    policy = json.loads((args.source/"calibration.json").read_bytes())
    if sha256(ckpt.read_bytes()).hexdigest() != policy["checkpoint_sha256"]:
        raise ValueError("Checkpoint mismatch")
    saved = torch.load(ckpt, weights_only=True, map_location="cpu")
    model = RiskWorldModel(config=ModelConfig(**saved["model_config"])).cuda().eval()
    model.load_state_dict(saved["model"])
    source,_ = source_examples(Path("data/safetydrift/5c55e54b75c9c7ee2037db8f3dbd6ae6a7dab8a8"),
                               Path("splits/safetydrift-public-v1.json"))
    rows = target_rows(Path("data/ATBench/test.json"), Path("splits/atbench-v1.json"), "calibration")
    encoder = Encoder(Path("models/qwen3-4b-instruct-2507"),"cuda",batch_size=1)
    def encoded(row,actions):
        return {**row,"task":encoder.encode(row["task"])[0],
                "observations":torch.stack([encoder.encode(s)[0] for s in row["observations"]]),
                "actions":torch.stack([encoder.encode(s)[0] for s in actions])}
    report = {"checkpoint":policy["checkpoint_sha256"],"normalized_actions":0,"changed_trajectories":0}
    names = {"send_email","send_message"}
    report["source_safe_tools"] = score_tools(source,policy["calibration_scores"],names)
    paired = defaultdict(list)
    for row in rows:
        original = row["actions"]
        new = [normalize(s) for s in original]
        report["normalized_actions"] += sum(x!=y for x,y in zip(original,new))
        report["changed_trajectories"] += int(new!=original)
        for arm,actions in (("raw",original),("normalized",new)):
            paired[arm].extend(predict(model,[encoded(row,actions)],"cuda"))
    for arm,scores in paired.items():
        report[arm] = metrics(scores,policy["config"])
        atomic_json(args.out/(arm+".json"), scores)
    report["target_safe_tools"] = score_tools(rows,paired["raw"],names)
    atomic_json(args.out/"summary.json",report)
    print(json.dumps(report),flush=True)


if __name__ == "__main__":
    main()
