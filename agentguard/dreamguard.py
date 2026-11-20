"""DreamGuard method reproduction: prepare, two-stage train/calibrate, evaluate.

No DreamGuard author source/checkpoint is embedded. See docs/dreamguard-reproduction-zh.md.
"""

import argparse
import json
import platform
from importlib.metadata import version
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import torch

from .dreamguard_data import fingerprint, json_text, source_examples, target_examples
from .dreamguard_model import ModelConfig, RiskWorldModel
from .dreamguard_policy import calibrate
from .dreamguard_runtime import evaluate, predict
from .dreamguard_training import (
    Encoder, OBSERVER_REVISION, SEED, atomic_json, extract, seed_everything, train_stage,
)

PROTOCOL = "dreamguard-paper-reproduction-v2"


def code_hashes():
    return {p.name: sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob("dreamguard*.py")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("prepare", "train", "evaluate", "all"), default="all")
    parser.add_argument("--safetydrift-root", type=Path, required=True)
    parser.add_argument("--safetydrift-split", type=Path, default=Path("splits/safetydrift-public-v1.json"))
    parser.add_argument("--observer", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=Path("data/ATBench/test.json"))
    parser.add_argument("--split-manifest", type=Path, default=Path("splits/atbench-v1.json"))
    parser.add_argument("--atbench-scope", choices=("heldout", "all"), default="all")
    parser.add_argument("--evaluation", choices=("safetydrift", "atbench", "both"), default="both")
    parser.add_argument("--latency", choices=("cached", "end-to-end"), default="end-to-end")
    parser.add_argument("--output-tag", default="formal")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--eval-latent", choices=("argmax", "sample"), default="argmax")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--encoding-batch-size", type=int, default=8)
    args = parser.parse_args(argv)
    if not args.output_tag or Path(args.output_tag).name != args.output_tag:
        parser.error("output-tag must be one filename component")
    if args.max_tokens < 1 or args.encoding_batch_size < 1:
        parser.error("max-tokens and encoding-batch-size must be positive")
    seed_everything(SEED)
    directory = args.out_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    source, source_manifest = source_examples(args.safetydrift_root, args.safetydrift_split)
    model_config = ModelConfig(eval_latent=args.eval_latent)
    identity = {"protocol": PROTOCOL, "seed": SEED, "model_config": asdict(model_config),
                "runtime": {"torch": str(torch.__version__), "transformers": version("transformers"),
                            "python": platform.python_version(), "cuda": torch.version.cuda},
                "observer_revision": OBSERVER_REVISION, "pooling": "masked-mean", "layer": 31,
                "feature_dtype": "bfloat16" if args.device.startswith("cuda") else "float32",
                "max_tokens": args.max_tokens, "source_sha256": fingerprint(source),
                "encoding_batch_size": args.encoding_batch_size,
                "split_sha256": sha256(args.safetydrift_split.read_bytes()).hexdigest(),
                "code_hashes": code_hashes(), "world_epochs": 10, "risk_epochs": 12, "batch_size": 8,
                "optimizer": "Adam", "lr": 2e-4, "world_lr_scale": 0.25,
                "prefix_horizon": 3, "prefix_temperature": 1.5,
                "jepa_weight": 1.25, "kl_weight": 0.03, "free_bits": 0.2,
                "train_count": sum(r["split"] == "train" for r in source),
                "calibration_count": sum(r["split"] == "calibration" for r in source),
                "test_count": sum(r["split"] == "heldout" for r in source)}
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_bytes())
        if manifest["identity"] != identity:
            raise ValueError("Run source/config/code changed; use a new run directory")
    else:
        manifest = {"variant": "DreamGuard-method-reproduction", "identity": identity,
                    "torch": str(torch.__version__), "cuda": torch.version.cuda,
                    "python": platform.python_version(),
                    "transformers": version("transformers"),
                    "gpu": torch.cuda.get_device_name(args.device) if args.device.startswith("cuda") else None,
                    "observer_path": str(args.observer.resolve()), "split_counts": source_manifest["counts"],
                    "projection_duplicates_removed": source_manifest.get("projection_duplicates_removed", []),
                    "within_test_duplicate_inputs": source_manifest.get("within_test_duplicate_inputs", []),
                    "author_assets": "official Qwen encoder only; no verified DreamGuard author implementation/checkpoint",
                    "differences_document": "docs/dreamguard-reproduction-zh.md"}
        atomic_json(manifest_path, manifest)
    print(json_text({"stage": "validated", "split_counts": manifest["split_counts"]}), flush=True)
    source_cache = directory / "source-features.pt"
    encoder = None
    if not source_cache.exists() and args.stage in ("evaluate", "train"):
        raise FileNotFoundError("Run --stage prepare first (or use --stage all)")
    if not source_cache.exists():
        encoder = Encoder(args.observer, args.device, args.max_tokens, batch_size=args.encoding_batch_size)
    encoded = extract(source, encoder, source_cache, identity)
    if encoder:
        del encoder
        encoder = None
        if str(args.device).startswith("cuda"):
            torch.cuda.empty_cache()
    if args.stage == "prepare":
        return 0
    model = RiskWorldModel(config=model_config).to(args.device)
    training = [r for r in encoded if r["split"] == "train"]
    if args.stage in ("all", "train"):
        train_stage(model, training, directory, args.device, "world", 10, identity)
        train_stage(model, training, directory, args.device, "risk", 12, identity)
    else:
        saved = torch.load(directory / "risk-checkpoint.pt", map_location="cpu", weights_only=True)
        if saved["identity"] != identity or saved["epoch"] != 12:
            raise ValueError("Completed matching risk checkpoint required")
        model.load_state_dict(saved["model"])
    model.eval()
    checkpoint_hash = sha256((directory / "risk-checkpoint.pt").read_bytes()).hexdigest()
    config_path = directory / "calibration.json"
    if config_path.exists():
        artifact = json.loads(config_path.read_bytes())
        if artifact["identity"] != identity or artifact["checkpoint_sha256"] != checkpoint_hash:
            raise ValueError("Calibration provenance differs")
        config = artifact["config"]
    else:
        seed_everything(SEED)
        scores = predict(model, [r for r in encoded if r["split"] == "calibration"], args.device)
        config = calibrate(scores)
        atomic_json(config_path, {"identity": identity, "checkpoint_sha256": checkpoint_hash,
                                 "config": config, "calibration_scores": scores})
    if args.stage == "train":
        return 0
    if args.latency == "end-to-end":
        encoder = Encoder(args.observer, args.device, args.max_tokens, batch_size=args.encoding_batch_size)
    for dataset in (("safetydrift", "atbench") if args.evaluation == "both" else (args.evaluation,)):
        seed_everything(SEED)
        if dataset == "safetydrift":
            text_rows = [r for r in source if r["split"] == "heldout"]
            feature_rows = [r for r in encoded if r["split"] == "heldout"]
            dataset_metadata = {"source_manifest_sha256": identity["split_sha256"]}
        else:
            text_rows = target_examples(args.data, args.split_manifest if args.atbench_scope == "heldout" else None)
            dataset_metadata = {"atbench_sha256": sha256(args.data.read_bytes()).hexdigest(), "scope": args.atbench_scope,
                                "split_sha256": sha256(args.split_manifest.read_bytes()).hexdigest() if args.atbench_scope == "heldout" else None}
            if encoder:
                feature_rows = text_rows
            else:
                temporary_encoder = Encoder(args.observer, args.device, args.max_tokens, batch_size=args.encoding_batch_size)
                feature_rows = extract(text_rows, temporary_encoder, directory / f"atbench-{args.atbench_scope}-features.pt",
                                       {**identity, **dataset_metadata})
                del temporary_encoder
                if str(args.device).startswith("cuda"):
                    torch.cuda.empty_cache()
        output = directory / f"{dataset}-{args.output_tag}.jsonl"
        evaluate(model, feature_rows, config, output, {**manifest, "dataset": dataset, **dataset_metadata,
                 "checkpoint_sha256": checkpoint_hash},
                 args.device, encoder=encoder, raw_examples=text_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
