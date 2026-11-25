"""Test migration of source-calibrated latent choices on ATBench development pairs."""
import argparse
import json
from pathlib import Path
import torch
from .dream_transfer import target_rows
from .dreamguard_training import Encoder, SEED, seed_everything, atomic_json
from .dreamguard_model import ModelConfig, RiskWorldModel
from .dreamguard_policy import metrics
from .dreamguard_runtime import predict
from hashlib import sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, required=True)
    args = parser.parse_args()
    rows = target_rows(Path("data/ATBench/test.json"), Path("splits/atbench-v1.json"), "calibration")
    rows = [r for label in (0, 1) for r in sorted((r for r in rows if r["label"] == label),
            key=lambda r: sha256(r["id"].encode()).digest())[:6]]
    encoder = Encoder(Path("models/qwen3-4b-instruct-2507"), "cuda")
    for row in rows:
        encoder.prefetch([row["task"], *row["actions"], *row["observations"]])
        row["task"] = encoder.encode(row["task"])[0]
        for name in ("observations", "actions"):
            row[name] = torch.stack([encoder.encode(s)[0] for s in row[name]])
    path = args.source / "risk-checkpoint.pt"
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    for mode in ("argmax", "sample"):
        artifact = json.loads((args.diagnostic / (mode + ".json")).read_bytes())
        if artifact["checkpoint_sha256"] != sha256(path.read_bytes()).hexdigest():
            raise ValueError("Source checkpoint mismatch")
        model = RiskWorldModel(config=ModelConfig(**{**checkpoint["model_config"], "eval_latent": mode})).cuda().eval()
        model.load_state_dict(checkpoint["model"])
        seed_everything(SEED)
        results = predict(model, rows, "cuda")
        summary = metrics(results, artifact["calibration"])
        atomic_json(args.diagnostic / ("atbench-development-" + mode + ".json"),
                    {"source": artifact["checkpoint_sha256"], "rows":results, "metrics":summary})
        print(mode, summary, flush=True)


if __name__ == "__main__":
    main()
