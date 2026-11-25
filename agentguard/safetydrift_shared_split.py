"""Freeze common DreamGuard and TRACES IDs for the local SafetyDrift comparison."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from .dreamguard_data import source_examples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--base-split", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base_bytes = args.base_split.read_bytes()
    base = json.loads(base_bytes)
    if not base.get("author_test_preserved") or len(base["splits"]["heldout"]) != 72:
        raise ValueError("Expected the public fixed SafetyDrift 72-case split")
    rows, audit = source_examples(args.data_root, args.base_split)
    if any(r["label_conflict"] or r["split"] != "train"
           for r in audit["projection_duplicates_removed"]):
        raise ValueError("Review conflict or calibration removal before freezing the common split")
    common = {split: [r["id"] for r in rows if r["split"] == split]
              for split in ("train", "calibration", "heldout")}
    for split in ("calibration", "heldout"):
        if common[split] != base["splits"][split]:
            raise ValueError(f"{split} IDs or order changed")
    manifest = {
        **base,
        "id": "safetydrift-public-shared-v1",
        "protocol": "Common local DreamGuard/TRACES split; public test IDs preserved",
        "base_split_sha256": sha256(base_bytes).hexdigest(),
        "splits": common,
        "counts": audit["counts"],
        "projection_duplicates_removed": audit["projection_duplicates_removed"],
    }
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps(manifest["counts"]))


if __name__ == "__main__":
    main()
