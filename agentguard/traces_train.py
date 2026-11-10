import argparse
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from .atbench import read_rows, read_split
from .guard import json_text, write_record
from .traces import (
    OBSERVER_LAYER,
    OBSERVER_REVISION,
    UPSTREAM_REVISION,
    ActionEndEncoder,
    load_head,
    score,
    to_events,
    use_upstream,
)

SMOKE_REVISION = "c1899de289a04d12100db370d81485cdf75e47ca"


def train(args) -> dict:
    split = read_split(args.split_manifest)
    data_sha, rows = read_rows(args.data, "ATBench", [], None)
    groups = {name: set(map(str, ids)) for name, ids in split["splits"].items()}
    if data_sha != split["source_sha256"] or set.union(*groups.values()) != {row[0] for row in rows}:
        raise ValueError("ATBench input and split manifest do not match")

    use_upstream(args.upstream)
    import config_atbench_trace_v3 as config
    import evaluate_atbench_trace as evaluate
    import numpy as np
    import pandas as pd
    import stage_a_atbench_trace as stage_a
    import stage_b_atbench_trace_v3 as stage_b

    directory = args.out_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    observer = str(args.observer.resolve())
    revision = SMOKE_REVISION if args.smoke else OBSERVER_REVISION
    layer = 24 if args.smoke else OBSERVER_LAYER
    encoder = ActionEndEncoder(observer, revision, layer, args.device)
    dimension = encoder.model.config.hidden_size
    train_ids, calibration_ids = set(), set()
    examples = {"train": train_ids, "calibration": calibration_ids}
    table = []
    calibration = []
    config.TABLE_PATH = str(directory / "action_repr.pkl")
    config.TRAJ_JSONL_PATH = str(directory / "train_calibration_labels.jsonl")
    config.OUT_DIR = str(directory)
    config.LAYERS = [layer]
    config.DEVICE = args.device
    if args.smoke:
        config.EPOCHS_STAGE_A = config.EPOCHS_STAGE_B = 1

    smoke_counts = defaultdict(int)
    with open(config.TRAJ_JSONL_PATH, "x", encoding="utf-8") as labels:
        for case_id, label, context in rows:
            if case_id in groups["heldout"]:
                continue
            name = "train" if case_id in groups["train"] else "calibration"
            if args.smoke and smoke_counts[name, label] >= {"train": 4, "calibration": 2}[name]:
                continue
            encoded = list(encoder.encode(to_events(context)))
            if not encoded:
                raise ValueError(f"TRACES found no usable actions for ATBench case {case_id}")
            smoke_counts[name, label] += 1
            examples[name].add(int(case_id))
            if name == "calibration":
                calibration.append((label, [vector for _, vector in encoded]))
            write_record(labels, {"id": int(case_id), "label": label})
            table.extend({
                "traj_id": int(case_id),
                "event_idx": index,
                "event_type": "agent_action",
                "event_order_among_decisions": order,
                "layer": layer,
                "rep": vector,
            } for order, (index, vector) in enumerate(encoded))
            extracted = len(train_ids) + len(calibration_ids)
            if extracted % 25 == 0:
                print(f"Encoded {extracted} ATBench train/calibration trajectories", flush=True)
    del encoder

    pd.DataFrame(table).to_pickle(config.TABLE_PATH)
    (directory / config.SPLIT_FILENAME).write_text(json_text({
        "train_ids": sorted(train_ids),
        "val_ids": sorted(calibration_ids),
        "test_ids": sorted(map(int, groups["heldout"])),
    }), encoding="utf-8")
    stage_a.train_stage_a(SimpleNamespace(overwrite_split=False))
    stage_b.train(SimpleNamespace(stage_a_ckpt=None, out_prefix="traces-stage-b"))
    head = load_head(directory, dimension, args.device)
    labels = [label for label, _ in calibration]
    scores = [score(head, vectors, args.device)[0] for _, vectors in calibration]
    threshold, calibration_f1 = evaluate.find_best_threshold(np.asarray(labels), np.asarray(scores), metric="f1")
    manifest = {
        "variant": "TRACES-ATBench-adapter",
        "upstream_revision": UPSTREAM_REVISION,
        "observer": observer,
        "observer_revision": revision,
        "layer": layer,
        "threshold": threshold,
        "calibration_f1": calibration_f1,
        "dataset_sha256": data_sha,
        "split_id": split["id"],
        "split_sha256": sha256(args.split_manifest.read_bytes()).hexdigest(),
        "train_count": len(train_ids),
        "calibration_count": len(calibration_ids),
        "smoke": args.smoke,
    }
    (directory / "manifest.json").write_text(json_text(manifest) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, default=Path("splits/atbench-v1.json"))
    parser.add_argument("--upstream", type=Path, default=Path("vendor/TRACES"))
    parser.add_argument("--observer", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--smoke", action="store_true", help="use Qwen3-0.6B and one epoch on 8/4 trajectories")
    print(json_text(train(parser.parse_args())))


if __name__ == "__main__":
    main()
