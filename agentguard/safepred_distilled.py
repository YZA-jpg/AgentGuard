"""Evaluate the pinned merged author checkpoint on fixed SafetyDrift trajectories."""
import argparse
import json
from pathlib import Path
from hashlib import sha256

from .safepred_author import AuthorSafePred, TransformersTransport, load_author
from .safepred_author_eval import evaluate_case, summarize
from .safepred_parallel import load_cases, case_seed, write_json
from .safepred_policy_v2 import verify_admission

REVISION = "430a412fa7d055fa5c8348e73d9fe20ac251949a"


class DistilledTransport(TransformersTransport):
    def __init__(self, path):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        index = json.loads((path / "model.safetensors.index.json").read_bytes())
        for name in {*index["weight_map"].values(), "model.safetensors.index.json", "config.json", "tokenizer.json", "tokenizer_config.json", "generation_config.json"}:
            metadata = path / ".cache/huggingface/download" / (name + ".metadata")
            if metadata.read_text().splitlines()[0] != REVISION:
                raise ValueError(f"Checkpoint revision mismatch for {name}")
        self.torch, self.device, self.max_tokens = torch, "cuda", 4000
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        self.model = AutoModelForCausalLM.from_pretrained(path, dtype=torch.bfloat16,
            attn_implementation="sdpa", local_files_only=True).to(self.device).eval()
        self.input_limit = self.model.config.max_position_embeddings - self.max_tokens
        self.calls = []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd()
    directory = root / "results/safepred-policy-v2-preflight-20261124/safetydrift-policy"
    admission = verify_admission(directory, root / "policies/specs/safepred-v2/safetydrift.json", "safetydrift")
    scope = "calibration" if args.smoke else "heldout"
    cases, identity = load_cases(root, "safetydrift", scope, 2 if args.smoke else None, Path("."))
    author = load_author(root / "vendor/SafePred-official")
    transport = DistilledTransport(root / "models/safepred-8b-author")
    guard = AuthorSafePred(author, transport, json.loads((directory / "policies.json").read_bytes()))
    args.out_dir.mkdir(parents=True, exist_ok=False)
    write_json(args.out_dir / "manifest.json", dict(model="yurun-chen/SafePred-8B", revision=REVISION,
        scope=scope, data=identity, policy_sha256=admission["policy_sha256"], state="legacy",
        temperature=0.3, thinking=False, max_new_tokens=4000, global_seed=42,
        source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), case_ids=[c["case_id"] for c in cases]))
    transport.torch.manual_seed(42)
    records = []
    with (args.out_dir / "results.jsonl").open("x") as stream:
        for case in cases:
            transport.calls.clear()
            record = evaluate_case(case, guard)
            stream.write(json.dumps(record) + "\n")
            stream.flush()
            records.append(record)
            print(len(records), "/", len(cases), record["status"], flush=True)
    result = summarize(records)
    write_json(args.out_dir / "summary.json", result)
    return int(bool(result["error_cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
