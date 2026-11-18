"""Train SafetyDrift TRACES heads with the pinned author's implementation."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from .guard import Decision, GuardError, Verdict, json_text, write_record
from .safetydrift_data import reviews, selected_cases
from .traces import (ActionEndEncoder, OBSERVER_LAYER, OBSERVER_REVISION, UPSTREAM_REVISION,
                     TracesGuard, load_head, score, to_events, use_upstream)


def safety_events(context):
    # A SafetyDrift decision can be a tool call or a plain response. Both are audited.
    return [{**e, "event_type": "agent_action"} if e["event_type"] == "agent_complete" else e
            for e in to_events(context)]


class SafetyTracesGuard(TracesGuard):
    def __init__(self, encoder, head, threshold):
        super().__init__(encoder, head, threshold)
        self.head.eval()

    def review(self, context):
        try:
            encoded = list(self.encoder.encode(safety_events(context), True, self.cache))
            if not encoded:
                raise GuardError("No decision boundary found")
            indices, vectors = zip(*encoded)
            risk, states = score(self.head, vectors, self.encoder.device)
        except GuardError:
            raise
        except Exception as error:
            raise GuardError(f"TRACES SafetyDrift review failed ({type(error).__name__})") from error
        return Verdict(Decision.BLOCK if risk >= self.threshold else Decision.ALLOW,
                       risk, {"event_indices": indices, "state_risk_scores": states})


def subset(rows, per_label):
    return [c for label in (0, 1) for c in [x for x in rows if x.label == label][:per_label]]


def train(args):
    use_upstream(args.upstream)
    import config_atbench_trace_v3 as config
    import evaluate_atbench_trace as evaluate
    import numpy as np
    import pandas as pd
    import stage_a_atbench_trace as stage_a
    import stage_b_atbench_trace_v3 as stage_b

    train_cases = selected_cases(args.data_root, args.split_manifest, "train")
    calibration_cases = selected_cases(args.data_root, args.split_manifest, "calibration")
    heldout = selected_cases(args.data_root, args.split_manifest, "heldout")
    if args.smoke:
        train_cases, calibration_cases = subset(train_cases, 4), subset(calibration_cases, 2)
    selected = train_cases + calibration_cases
    ids = {c.case_id: i for i, c in enumerate(selected + heldout)}
    directory = args.out_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / "manifest.json").exists():
        raise ValueError("A completed training run already exists")
    metadata = {"variant": "TRACES-author-code-SafetyDrift-adapter", "upstream_revision": UPSTREAM_REVISION,
                "observer": str(args.observer.resolve()), "observer_revision": OBSERVER_REVISION,
                "layer": OBSERVER_LAYER, "mechanisms": 8, "seed": 42, "smoke": args.smoke,
                "split_sha256": sha256(args.split_manifest.read_bytes()).hexdigest(),
                "train_ids": [c.case_id for c in train_cases],
                "calibration_ids": [c.case_id for c in calibration_cases],
                "heldout_ids": [c.case_id for c in heldout],
                "adaptation": ["Original 72 author test IDs retained; duplicate development inputs removed",
                               "Remaining development traces split 80/20 by category and label, seed 42",
                               "Both tool and response decisions mapped to action-end events",
                               "Author ATBench training modules reused on SafetyDrift; K=8 matches paper",
                               "Checkpoint and threshold selected only on calibration traces"]}
    pending = directory / "training_metadata.json"
    if pending.exists() and json.loads(pending.read_bytes()) != metadata:
        raise ValueError("Training configuration changed")
    pending.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    cache = directory / "features.pkl"
    if cache.exists():
        features = pd.read_pickle(cache)
    else:
        encoder = ActionEndEncoder(str(args.observer.resolve()), OBSERVER_REVISION, OBSERVER_LAYER, args.device)
        features = []
        for index, case in enumerate(selected):
            final_context = list(reviews(case))[-1]
            encoded = list(encoder.encode(safety_events(final_context)))
            if len(encoded) != len(case.steps):
                raise ValueError(f"Decision count mismatch for {case.case_id}")
            features.append((case.case_id, case.label, [vector for _, vector in encoded]))
            if (index + 1) % 10 == 0:
                print(json_text({"phase": "TRACES embeddings", "completed": index + 1,
                                 "total": len(selected)}), flush=True)
        del encoder
        import torch
        torch.cuda.empty_cache()
        pd.to_pickle(features, cache)
    if [x[0] for x in features] != [c.case_id for c in selected]:
        raise ValueError("Cached features do not match training IDs")
    table = [{"traj_id": ids[case_id], "event_idx": i, "event_type": "agent_action",
              "event_order_among_decisions": i, "layer": OBSERVER_LAYER, "rep": vector}
             for case_id, _, vectors in features for i, vector in enumerate(vectors)]
    config.TABLE_PATH = str(directory / "action_repr.pkl")
    config.TRAJ_JSONL_PATH = str(directory / "train_calibration_labels.jsonl")
    config.OUT_DIR = str(directory)
    config.LAYERS = [OBSERVER_LAYER]
    config.DEVICE = args.device
    config.K_MECH = 8
    if args.smoke:
        config.EPOCHS_STAGE_A = config.EPOCHS_STAGE_B = 1
    pd.DataFrame(table).to_pickle(config.TABLE_PATH)
    with Path(config.TRAJ_JSONL_PATH).open("w", encoding="utf-8") as out:
        for case_id, label, _ in features:
            write_record(out, {"id": ids[case_id], "label": label})
    (directory / config.SPLIT_FILENAME).write_text(json_text({
        "train_ids": [ids[c.case_id] for c in train_cases],
        "val_ids": [ids[c.case_id] for c in calibration_cases],
        "test_ids": [ids[c.case_id] for c in heldout],
    }), encoding="utf-8")
    stage_a.train_stage_a(SimpleNamespace(overwrite_split=False))
    stage_b.train(SimpleNamespace(stage_a_ckpt=None, out_prefix="traces-stage-b"))
    head = load_head(directory, 2560, args.device, 8)
    head.eval()
    cal_ids = {c.case_id for c in calibration_cases}
    cal_features = [(label, vectors) for case_id, label, vectors in features if case_id in cal_ids]
    labels = np.asarray([label for label, _ in cal_features])
    # Max prefix score exactly matches the first-intervention trajectory rule.
    risks = np.asarray([max(score(head, vectors[:i + 1], args.device)[0] for i in range(len(vectors)))
                        for _, vectors in cal_features])
    threshold, _ = evaluate.find_best_threshold(labels, risks, metric="f1")
    config_values = {k: v for k, v in vars(config).items()
                     if k.isupper() and isinstance(v, (str, int, float, bool, list, tuple))}
    manifest = {**metadata, "threshold": float(threshold), "threshold_source": "calibration_max_prefix_f1",
                "calibration_metrics": evaluate.binary_metrics(labels, risks, threshold),
                "configuration": config_values,
                "implementation_sha256": {
                    name: sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                    for name in ("safetydrift_data.py", "traces_safetydrift.py", "traces.py")},
                "checkpoint_sha256": {
                    name: sha256((directory / name).read_bytes()).hexdigest()
                    for name in ("stage_a_latent_mechanism.pt", "traces-stage-b.pt")},
                "train_count": len(train_cases), "calibration_count": len(calibration_cases)}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json_text(manifest["calibration_metrics"]), flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, default=Path("splits/safetydrift-public-v1.json"))
    parser.add_argument("--upstream", type=Path, default=Path("vendor/TRACES"))
    parser.add_argument("--observer", type=Path, default=Path("models/qwen3-4b-observer"))
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    train(args)


if __name__ == "__main__":
    main()
