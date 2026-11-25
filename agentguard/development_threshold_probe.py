"""Development-only comparison of global and action-type thresholds on frozen scores."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from collections import defaultdict, Counter

from .dream_transfer import target_rows
from .dreamguard_policy import Evidence, threshold
from .dreamguard_runtime import policy_config
from .dreamguard_training import atomic_json


def fit(rows, classes, config, grouped, hold_alpha, block_alpha):
    maxima = defaultdict(list)
    for r in rows:
        if r["label"]:
            continue
        per_case = defaultdict(list)
        state = Evidence()
        for kind,h,p in zip(classes[r["id"]],r["hazard_scores"],r["prefix_scores"]):
            state, fused, _ = state.propose(h,p,config)
            role = kind if grouped else "any"
            for channel,score in (("hold",fused),("block",h)):
                per_case[(role,channel)].append(score)
        for key,values in per_case.items():
            maxima[key].append(max(values))
    return {f"{role}/{channel}":threshold(values,hold_alpha if channel=="hold" else block_alpha)
            for (role,channel),values in maxima.items()}


def evaluate(rows, classes, config, limits, grouped):
    counts = Counter()
    for row in rows:
        state = Evidence()
        block = False
        for kind,h,p in zip(classes[row["id"]],row["hazard_scores"],row["prefix_scores"]):
            state, fused, _ = state.propose(h,p,config)
            role = kind if grouped else "any"
            if h >= limits[role+"/block"] or fused >= limits[role+"/hold"]:
                block = True
                break
        counts[row["label"],int(block)] += 1
    tp,fp,tn,fn = (counts[k] for k in ((1,1),(0,1),(0,0),(1,0)))
    return dict(tp=tp,fp=fp,tn=tn,fn=fn,f1=2*tp/(2*tp+fp+fn),recall=tp/(tp+fn),fpr=fp/(tn+fp))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--run",type=Path,required=True)
    args=parser.parse_args()
    source=Path("results/dreamguard-v1-v2-20261121_015401/v2/calibration.json")
    artifact=json.loads(source.read_bytes())
    config=policy_config(artifact["config"])
    rows=target_rows(Path("data/ATBench/test.json"),Path("splits/atbench-v1.json"),"calibration")
    classes={r["id"]:["tool" if "name" in json.loads(a) else "reply" for a in r["actions"]] for r in rows}
    output={}
    for arm in ("raw","normalized"):
        scores=json.loads((args.run/(arm+".json")).read_bytes())
        scores.sort(key=lambda r:sha256(r["id"].encode()).digest())
        if len(scores)!=200 or len(set(r["id"] for r in scores))!=200:
            raise ValueError("Expected 200 distinct development cases")
        for row in scores:
            if not len(classes[row["id"]])==len(row["hazard_scores"])==len(row["prefix_scores"]):
                raise ValueError("Incomplete scores")
        train, val = scores[:100],scores[100:]
        for grouped in (False, True):
            limits=fit(train,classes,config,grouped,artifact["config"]["hold_alpha"],artifact["config"]["block_alpha"])
            output[f"{arm}/"+("action_type" if grouped else "global")]={
                "thresholds":limits,"metrics":evaluate(val,classes,config,limits,grouped)}
    report=dict(fit_ids=[r["id"] for r in train],validation_ids=[r["id"] for r in val],
                configuration=output,source_policy_sha256=sha256(source.read_bytes()).hexdigest())
    atomic_json(args.run/"development-calibration.json",report)
    print(json.dumps({k:v["metrics"] for k,v in output.items()}))


if __name__=="__main__":
    main()
