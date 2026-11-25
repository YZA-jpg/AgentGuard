"""Paired latent-sampling diagnostic on the frozen DreamGuard v2 checkpoint."""
import argparse
import json
from hashlib import sha256
from pathlib import Path

import torch

from .dreamguard_model import ModelConfig, RiskWorldModel
from .dreamguard_policy import calibrate, metrics
from .dreamguard_runtime import predict
from .dreamguard_training import SEED, seed_everything, atomic_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    source = args.source
    ckpt = source / "risk-checkpoint.pt"
    saved = torch.load(ckpt, weights_only=True, map_location="cpu")
    cache = torch.load(source / "source-features.pt", weights_only=True, map_location="cpu")
    original = json.loads((source / "calibration.json").read_bytes())
    digest = sha256(ckpt.read_bytes()).hexdigest()
    if digest != original["checkpoint_sha256"] or saved["identity"] != original["identity"]:
        raise ValueError("Checkpoint and calibration provenance differ")
    cal, test = ([r for r in cache["rows"] if r["split"] == split] for split in ("calibration", "heldout"))
    if len(cal) != 57 or len(test) != 72 or {r["id"] for r in cal} & {r["id"] for r in test}:
        raise ValueError("Unexpected or overlapping splits")
    args.out.mkdir(parents=True, exist_ok=False)
    for mode in ("argmax", "sample"):
        seed_everything(SEED)
        model = RiskWorldModel(config=ModelConfig(**{**saved["model_config"], "eval_latent": mode})).to(args.device).eval()
        model.load_state_dict(saved["model"])
        seed_everything(SEED)
        policy = calibrate(predict(model, cal, args.device))
        seed_everything(SEED)
        rows = predict(model, test, args.device)
        scores = metrics(rows, policy)
        atomic_json(args.out / (mode + ".json"), dict(checkpoint_sha256=digest, seed=SEED,
                    calibration=policy, results=rows, metrics=scores, latency_protocol="cached"))
        print(mode, scores, flush=True)


if __name__ == "__main__":
    main()
