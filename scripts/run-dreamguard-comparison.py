#!/usr/bin/env python3
"""Train frozen DreamGuard v1/v2 snapshots, then compare matched ATBench cases.

No source snapshot is edited. v1 reuses verified frozen features, never weights.
The two native runs and paired latency evaluation share one GPU sequentially.
"""

import argparse
import importlib
import importlib.util
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import traceback
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

V1_COMMIT = "526257e0cc2a14a4d583c3b5cf8ee1b2f7f5dd75"
V2_COMMIT = "629584caeec39ba2bfeba1697765a976047c0610"


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def digest(path):
    result = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            result.update(block)
    return result.hexdigest()


def write_json(path, value):
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf8")
    temporary.replace(path)


def load_snapshot(alias, path):
    """Relative imports remain inside their own frozen package namespace."""
    if alias not in sys.modules:
        package = Path(path) / "agentguard"
        spec = importlib.util.spec_from_file_location(alias, package / "__init__.py",
                                                      submodule_search_locations=[str(package)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[alias] = module
        spec.loader.exec_module(module)
    return importlib.import_module(alias + ".dreamguard")


def verify_snapshot(path, expected_commit):
    metadata = json.loads((path / "snapshot.json").read_bytes())
    if metadata["commit"] != expected_commit:
        raise ValueError("Unexpected source snapshot commit")
    for name, expected in metadata["files"].items():
        target = (path / name).resolve()
        if path.resolve() not in target.parents or digest(target) != expected:
            raise ValueError(f"Snapshot hash differs: {name}")
    return metadata


def read_result(path, expected_count):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf8").splitlines() if line.strip()]
    cases = [row for row in rows if row.get("record_type") == "case"]
    summaries = [row for row in rows if row.get("record_type") == "overall_summary"]
    if len(summaries) != 1 or rows[-1].get("record_type") != "overall_summary":
        raise ValueError(f"No final successful summary: {path}")
    summary = summaries[0]
    if len(cases) != expected_count or summary["completed_cases"] != expected_count or summary["error_cases"] != 0:
        raise ValueError(f"Unexpected completion count: {path}")
    normalized = {}
    for case in cases:
        key = str(case.get("id", case.get("case_id")))
        if key == "None" or key in normalized or case.get("status") != "ok":
            raise ValueError(f"Duplicate, missing or failed case: {path}")
        normalized[key] = case
    return normalized, summary


def classification(cases):
    counts = Counter((int(r["label"]), int(r["prediction"])) for r in cases)
    tp, fp, tn, fn = [counts[p] for p in ((1,1),(0,1),(0,0),(1,0))]
    return {"tp":tp,"fp":fp,"tn":tn,"fn":fn,
            "f1":2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.,
            "recall":tp/(tp+fn) if tp+fn else None,
            "fpr":fp/(fp+tn) if fp+tn else None}


def timing(values):
    if not values:
        raise ValueError("No measured audit calls")
    ordered = sorted(values)
    return {"mean_guard_latency_seconds":statistics.mean(values),
            "median_guard_latency_seconds":statistics.median(values),
            "p95_guard_latency_seconds":ordered[math.ceil(.95*len(ordered))-1],
            "successful_reviews":len(values)}


class Comparison:
    def __init__(self, args):
        self.args, self.root, self.run = args, args.root.resolve(), args.run_dir.resolve()
        if not str(self.run).startswith("/data1/") or not str(self.root).startswith("/data1/"):
            raise ValueError("Server run and project roots must be under /data1")
        self.run.mkdir(parents=True, exist_ok=True)
        self.python = self.root / ".venv/bin/python"
        self.v1_source = args.snapshots.resolve() / "v1"
        self.v2_source = args.snapshots.resolve() / "v2"
        self.v1, self.v2 = self.run / "v1", self.run / "v2"
        self.v1.mkdir(exist_ok=True); self.v2.mkdir(exist_ok=True)
        self.phase = "initializing"
        self.env = os.environ.copy()
        self.env.pop("LD_LIBRARY_PATH", None)
        for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
            self.env.pop(name, None)
        self.env.update(CUDA_VISIBLE_DEVICES=str(args.gpu), PYTHONUNBUFFERED="1", OMP_NUM_THREADS="2",
                        TOKENIZERS_PARALLELISM="false", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        for variable, name in (("HF_HOME","huggingface"),("TORCH_HOME","torch"),
                               ("XDG_CACHE_HOME","xdg"),("TMPDIR","tmp")):
            path = self.root / "cache" / name
            path.mkdir(parents=True, exist_ok=True)
            self.env[variable] = str(path)
        self.history = []

    def state(self, phase, **extra):
        self.phase = phase
        row = {"phase":phase, "utc":stamp(), **extra}
        self.history.append(row)
        write_json(self.run/"status.json", {**row,"history":self.history})
        print(json.dumps(row,ensure_ascii=False),flush=True)

    def resources(self, name):
        result = subprocess.run(["nvidia-smi","--query-gpu=index,name,memory.free,utilization.gpu",
                                 "--format=csv,noheader,nounits"], text=True,capture_output=True,check=True)
        (self.run/f"gpu-{name}.txt").write_text(result.stdout,encoding="utf8")
        if name == "before":
            matching = [line for line in result.stdout.splitlines() if line.split(",")[0].strip() == str(self.args.gpu)]
            if len(matching) != 1 or int(matching[0].split(",")[2].strip()) < 20000:
                raise RuntimeError("Selected GPU needs at least 20000 MiB free before startup")

    def child(self, phase, snapshot, arguments, log_name):
        self.state(phase)
        command = [str(self.python),"-m","agentguard.dreamguard",*map(str,arguments)]
        write_json(self.run/f"{log_name}-command.json",{"argv":command,"cwd":str(snapshot),"gpu":self.args.gpu})
        with (self.run/f"{log_name}.log").open("a",encoding="utf8") as log:
            process = subprocess.Popen(command,cwd=snapshot,env=self.env,stdout=log,stderr=subprocess.STDOUT)
            write_json(self.run/"child.json",{"pid":process.pid,"phase":phase,"log":log_name+".log"})
            code = process.wait()
        if code:
            raise subprocess.CalledProcessError(code,command)

    def common_args(self, directory):
        return ["--observer",self.root/"models/qwen3-4b-instruct-2507",
                "--safetydrift-root",self.root/"data/safetydrift/5c55e54b75c9c7ee2037db8f3dbd6ae6a7dab8a8",
                "--data",self.root/"data/ATBench/test.json","--split-manifest",self.root/"splits/atbench-v1.json",
                "--out-dir",directory]

    def validate_features(self, legacy):
        import torch
        original = self.args.v1_feature_run.resolve()
        metadata = json.loads((original/"manifest.json").read_bytes())
        for name, expected in metadata["implementation_sha256"].items():
            if digest(self.v1_source/"agentguard"/name) != expected:
                raise ValueError("Legacy frozen features were produced by different source code")
        source, _ = legacy.source_examples(self.root/"data/safetydrift/5c55e54b75c9c7ee2037db8f3dbd6ae6a7dab8a8")
        target = legacy.target_examples(self.root/"data/ATBench/test.json",self.root/"splits/atbench-v1.json")
        examples = source+target
        if sha256(legacy.json_text(examples).encode()).hexdigest() != metadata["source_hash"]:
            raise ValueError("Legacy frozen feature texts/splits/labels differ")
        for path, key in ((self.root/"data/ATBench/test.json","atbench_sha256"),
                          (self.root/"splits/atbench-v1.json","split_sha256")):
            if digest(path) != metadata[key]: raise ValueError("Legacy data hash differs")
        revision = (self.root/"models/qwen3-4b-instruct-2507/revision.txt").read_text().strip()
        if revision != metadata["observer_revision"]: raise ValueError("Encoder revision differs")
        features = torch.load(original/"features.pt",map_location="cpu",weights_only=True)
        if len(features) != len(examples): raise ValueError("Feature row count differs")
        for feature, example in zip(features, examples):
            if (feature["id"],feature["split"],feature["label"]) != (example["id"],example["split"],example["label"]):
                raise ValueError("Feature row identity differs")
            if tuple(feature["task"].shape) != (2560,) or tuple(feature["actions"].shape) != (len(example["actions"]),2560):
                raise ValueError("Unexpected frozen feature shape")
        cache = self.v1/"features.pt"
        original_hash = digest(original/"features.pt")
        if cache.exists() and digest(cache) != original_hash: raise ValueError("Existing v1 cache differs")
        if not cache.exists(): shutil.copy2(original/"features.pt",cache)
        write_json(self.run/"v1-feature-provenance.json",{"source_run":str(original),"source_hash":metadata["source_hash"],
            "features_sha256":original_hash,"source_counts":metadata["split_counts"],
            "weights_reused":False,"note":"Only immutable frozen encoder features reused; train new world/risk models"})
        return target

    def native_runs(self):
        self.state("validating")
        verify_snapshot(self.v1_source,V1_COMMIT); verify_snapshot(self.v2_source,V2_COMMIT)
        self.resources("before")
        legacy = load_snapshot("frozen_dreamguard_v1",self.v1_source)
        self.validate_features(legacy)
        v1_output = self.v1/"atbench.jsonl"
        if not v1_output.exists():
            self.child("v1-training-evaluation",self.v1_source,self.common_args(self.v1),"v1-native")
        read_result(v1_output,200)
        v2_args = self.common_args(self.v2) + ["--safetydrift-split",self.root/"splits/safetydrift-public-v1.json",
                   "--atbench-scope","all","--latency","end-to-end","--output-tag","native"]
        for dataset, count in (("safetydrift",72),("atbench",1000)):
            output = self.v2/f"{dataset}-native.jsonl"
            if output.exists():
                read_result(output,count)
                continue
            # First process prepares/trains; second only loads the completed checkpoint.
            stage = "all" if dataset == "safetydrift" else "evaluate"
            self.child(f"v2-{dataset}",self.v2_source,v2_args+["--stage",stage,"--evaluation",dataset],f"v2-{dataset}")
            read_result(output,count)

    def paired(self, version):
        import torch
        output = self.run/f"paired-{version}.jsonl"
        if output.exists():
            read_result(output,200)
            return
        self.state(f"paired-{version}-uncached-latency")
        self.resources("paired-"+version)
        legacy = load_snapshot("frozen_dreamguard_v1",self.v1_source)
        current = load_snapshot("frozen_dreamguard_v2",self.v2_source)
        runtime = importlib.import_module("frozen_dreamguard_v2.dreamguard_runtime")
        torch.manual_seed(current.SEED)
        device = "cuda"
        if version == "v1":
            model = legacy.RiskWorldModel().to(device).eval()
            model.load_state_dict(torch.load(self.v1/"risk.pt",map_location=device,weights_only=True))
            config = json.loads((self.v1/"calibration.json").read_bytes())
            rows = legacy.target_examples(self.root/"data/ATBench/test.json",self.root/"splits/atbench-v1.json")
            class NoCacheLegacyEncoder(legacy.Encoder):
                def encode(self,text,*,cached=False):
                    self.cache.clear()
                    return super().encode(text)
            encoder = NoCacheLegacyEncoder(str(self.root/"models/qwen3-4b-instruct-2507"),device)
            pooling = "float32 mean, exactly v1 native encoder"
        else:
            checkpoint = torch.load(self.v2/"risk-checkpoint.pt",map_location="cpu",weights_only=True)
            model = current.RiskWorldModel(config=current.ModelConfig(**checkpoint["model_config"])).to(device).eval()
            model.load_state_dict(checkpoint["model"])
            config = json.loads((self.v2/"calibration.json").read_bytes())["config"]
            rows = current.target_examples(self.root/"data/ATBench/test.json",self.root/"splits/atbench-v1.json")
            encoder = current.Encoder(self.root/"models/qwen3-4b-instruct-2507",device)
            pooling = "bfloat16 masked mean, exactly v2 native encoder"
        if len(rows) != 200: raise ValueError("Paired evaluation needs exactly 200 cases")
        # No trajectory state is retained from warmup; weights are fixed.
        with torch.inference_mode():
            for text in ("warmup task","warmup observation","warmup action"):
                encoder.encode(text,cached=False)
            zero = torch.zeros(1,2560,device=device)
            model.step(model.initial(zero),zero,zero,zero)
            torch.cuda.synchronize()
        cases, latencies = [], []
        with output.open("x",encoding="utf8") as stream:
            stream.write(json.dumps({"record_type":"run_metadata","version":version,"gpu":self.args.gpu,
                "pooling":pooling,"latency_protocol":"uncached text-to-decision; one warmup; first-call task encoding included",
                "snapshot_commit":V1_COMMIT if version=="v1" else V2_COMMIT,
                "action_serialization":"native to each version","scope":"ATBench-heldout-200"})+"\n")
            for row in rows:
                session = runtime.DreamGuardSession(model,encoder,row["task"],config,device)
                steps = []
                for observation, action in zip(row["observations"],row["actions"]):
                    reviewed = session.review(observation,action)
                    steps.append(reviewed)
                    latencies.append(reviewed["latency_seconds"])
                    if reviewed["decision"] != "PASS": break
                    session.commit(reviewed["generation"])
                intervention = len(steps)-1 if steps[-1]["decision"] != "PASS" else None
                record = {"record_type":"case","id":str(row["id"]),"label":row["label"],"status":"ok",
                          "prediction":int(intervention is not None),"first_intervention":intervention,"steps":steps}
                stream.write(json.dumps(record,ensure_ascii=False)+"\n"); stream.flush()
                cases.append(record)
                if len(cases)%10 == 0:
                    self.state(f"paired-{version}-uncached-latency",completed=len(cases),total=200)
            summary = {"record_type":"overall_summary","total_cases":200,"completed_cases":200,"error_cases":0,
                       **classification(cases),**timing(latencies),"phir":None,"mas":None,"recovery_fpr":None}
            stream.write(json.dumps(summary)+"\n")
        del model,encoder
        torch.cuda.empty_cache()

    def report(self):
        self.state("summarizing")
        native1, n1 = read_result(self.v1/"atbench.jsonl",200)
        native2, n2 = read_result(self.v2/"atbench-native.jsonl",1000)
        paired1, p1 = read_result(self.run/"paired-v1.jsonl",200)
        paired2, p2 = read_result(self.run/"paired-v2.jsonl",200)
        if set(native1)!=set(paired1) or set(paired1)!=set(paired2) or not set(native1)<=set(native2):
            raise ValueError("Comparison case IDs differ")
        for key in native1:
            if len({native1[key]["label"],native2[key]["label"],paired1[key]["label"],paired2[key]["label"]})!=1:
                raise ValueError("Comparison labels differ")
        shared2 = [native2[key] for key in native1]
        _, sd = read_result(self.v2/"safetydrift-native.jsonl",72)
        changes = {version:sum(native[key]["prediction"]!=paired[key]["prediction"] for key in native1)
                   for version,native,paired in (("v1",native1,paired1),("v2",native2,paired2))}
        report = {"scope":"ATBench-heldout-200","v1_native":classification(list(native1.values())),
                  "v2_native_matched":classification(shared2),"paired_v1":p1,"paired_v2":p2,
                  "delta_v2_minus_v1":{key:p2[key]-p1[key] for key in ("f1","recall","fpr","mean_guard_latency_seconds")},
                  "native_vs_paired_prediction_changes":changes,"v2_atbench1000":n2,"v2_safetydrift72":sd,
                  "v1_source_split":"281 train / 69 calibration; no independent SafetyDrift test",
                  "v2_source_split":"221 train / 57 calibration / 72 test",
                  "interpretation":"Aggregate protocol comparison, single seed; both are independent method reproductions",
                  "latency_caveat":"Same physical A100, sequential; shared vLLM may change load; version-native pooling/serialization preserved"}
        write_json(self.run/"comparison.json",report)
        def row(name, stats):
            return f"| {name} | {100*stats['f1']:.2f} | {100*stats['recall']:.2f} | {100*stats['fpr']:.2f} | {stats['mean_guard_latency_seconds']:.6f} |"
        text = "# DreamGuard v1 / v2 comparison\n\n同一 ATBench 200 条，99 危险、101 安全；新训练权重，逐条审核至首次干预。\n\n"
        text += "| 版本 | F1 ↑ (%) | Recall ↑ (%) | FPR ↓ (%) | Latency ↓ (秒/次) |\n| --- | ---: | ---: | ---: | ---: |\n"
        text += row("v1",p1)+"\n"+row("v2",p2)+"\n\n"
        text += "Latency 为统一执行前计时框架下实测，关闭文本缓存，保留各版本原生池化和动作序列化；同一 A100 串行测量。共享服务器负载见 gpu-*.txt。\n\n"
        text += "| v2 额外评测 | F1 (%) | Recall (%) | FPR (%) | Latency (秒/次) |\n| --- | ---: | ---: | ---: | ---: |\n"
        text += row("ATBench 全量1000",n2)+"\n"+row("SafetyDrift 测试72",sd)+"\n\n"
        text += f"原生评测与统一计时复测之间的预测变化：v1={changes['v1']} 条，v2={changes['v2']} 条。详见 comparison.json，原生 v1 缓存耗时不用于上表。\n\n"
        text += "v1 使用 281/69 训练/校准，不能再把该 SafetyDrift 校准集作为独立测试；v2 为 221/57/72。多项协议同时改变，此表不能解释成单因素消融，也不能代表训练方差。\n"
        (self.run/"comparison.md").write_text(text,encoding="utf8")
        self.resources("after")
        self.state("complete",comparison=str(self.run/"comparison.md"))

    def execute(self):
        try:
            self.native_runs()
            # Existing imported CPU snapshots have never initialized CUDA. Set env before this script starts.
            self.paired("v1")
            self.paired("v2")
            self.report()
        except BaseException as error:
            failed = self.phase
            self.state("failed",failed_phase=failed,error_type=type(error).__name__,error=str(error))
            raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--snapshots",type=Path,required=True)
    parser.add_argument("--run-dir",type=Path,required=True)
    parser.add_argument("--v1-feature-run",type=Path,required=True)
    parser.add_argument("--gpu",type=int,default=3)
    args=parser.parse_args(argv)
    # Must happen before importing either snapshot (which imports torch).
    os.environ["CUDA_VISIBLE_DEVICES"]=str(args.gpu)
    os.environ.pop("LD_LIBRARY_PATH",None)
    Comparison(args).execute()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
