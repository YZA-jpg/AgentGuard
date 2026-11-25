"""Audit DreamGuard supervised prefixes and SafetyDrift feature split integrity."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import json
from hashlib import sha256
import torch
from sklearn.metrics import roc_auc_score
from .dreamguard_model import RiskWorldModel, ModelConfig
from .dreamguard_runtime import predict
from .dreamguard_training import atomic_json
from .dreamguard_data import source_examples, fingerprint


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    rows,_=source_examples(Path("data/safetydrift/5c55e54b75c9c7ee2037db8f3dbd6ae6a7dab8a8"),
                           Path("splits/safetydrift-public-v1.json"))
    cached=torch.load(args.source/"source-features.pt",map_location="cpu",weights_only=True)["rows"]
    lookup={r["id"]:r for r in rows}
    if set(lookup)!={r["id"] for r in cached}:
        raise ValueError("Source cache IDs differ")
    for r in cached:
        raw=lookup[r["id"]]
        if r["label"]!=raw["label"] or r["first_hazard"]!=raw["first_hazard"]:
            raise ValueError("Cached supervision differs")
    saved=torch.load(args.source/"risk-checkpoint.pt",map_location="cpu",weights_only=True)
    model=RiskWorldModel(config=ModelConfig(**saved["model_config"])).eval()
    model.load_state_dict(saved["model"])
    report={"source_checkpoint_sha256":sha256((args.source/"risk-checkpoint.pt").read_bytes()).hexdigest(),
            "supervision_cache_verified":True,"splits":{}}
    prefix_groups=defaultdict(list)
    for split in ("train","calibration"):
        selected=[r for r in cached if r["split"]==split]
        scores={r["id"]:r for r in predict(model,selected,"cpu")}
        tools=defaultdict(list)
        for r in selected:
            raw=lookup[r["id"]]
            stop=len(raw["actions"]) if raw["first_hazard"] is None else raw["first_hazard"]+1
            for t in range(stop):
                positive=int(t==raw["first_hazard"])
                action=json.loads(raw["actions"][t])
                tool=action.get("name","<reply>")
                tools[tool].append((positive,scores[r["id"]]["hazard_scores"][t]))
                key=fingerprint([raw["task"],raw["observations"][:t+1],raw["actions"][:t+1]])
                prefix_groups[key].append((split,raw["id"],t,positive))
        stats=[]
        for tool,values in sorted(tools.items()):
            labels,risks=zip(*values)
            stats.append({"tool":tool,"safe":labels.count(0),"hazard":labels.count(1),
                          "auroc":roc_auc_score(labels,risks) if len(set(labels))==2 else None})
        report["splits"][split]=stats
    conflicts=[v for v in prefix_groups.values() if len({x[-1] for x in v})>1]
    report["conflicting_visible_prefixes"]=conflicts
    report["cross_split_prefix_groups"]=sum(len({x[0] for x in v})>1 for v in prefix_groups.values())
    atomic_json(args.out,report)
    print(json.dumps(report),flush=True)


if __name__=="__main__":
    main()
