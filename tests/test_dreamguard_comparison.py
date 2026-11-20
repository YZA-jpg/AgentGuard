import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location("dreamguard_comparison_runner",
    Path(__file__).resolve().parents[1]/"scripts/run-dreamguard-comparison.py")
runner=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def write_result(path, labels, predictions, ids=None):
    cases=[{"record_type":"case","id":str(i if ids is None else ids[i]),"label":label,
            "prediction":prediction,"status":"ok"} for i,(label,prediction) in enumerate(zip(labels,predictions))]
    summary={"record_type":"overall_summary","total_cases":len(cases),"completed_cases":len(cases),
             "error_cases":0,"mean_guard_latency_seconds":.1,**runner.classification(cases)}
    path.write_text("\n".join(json.dumps(row) for row in cases+[summary])+"\n",encoding="utf8")


class ComparisonTests(unittest.TestCase):
    def test_incomplete_and_duplicate_outputs_are_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"out.jsonl"
            write_result(path,[0,1],[0,1])
            self.assertEqual(len(runner.read_result(path,2)[0]),2)
            with self.assertRaisesRegex(ValueError,"count"):
                runner.read_result(path,3)
            write_result(path,[0,1],[0,1],ids=["same","same"])
            with self.assertRaisesRegex(ValueError,"Duplicate"):
                runner.read_result(path,2)

    def test_snapshot_hash_blocks_modified_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/"agentguard/model.py"; source.parent.mkdir(); source.write_text("value=1")
            (root/"snapshot.json").write_text(json.dumps({"commit":"test","files":{"agentguard/model.py":runner.digest(source)}}))
            runner.verify_snapshot(root,"test")
            source.write_text("value=2")
            with self.assertRaisesRegex(ValueError,"hash"):
                runner.verify_snapshot(root,"test")

    def test_snapshot_namespaces_remain_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            for number in (1,2):
                root=Path(directory)/str(number)
                package=root/"agentguard"; package.mkdir(parents=True)
                (package/"__init__.py").write_text("")
                (package/"dreamguard.py").write_text(f"VERSION={number}")
                self.assertEqual(runner.load_snapshot("test_frozen_dreamguard_"+str(number),root).VERSION,number)
            for key in list(sys.modules):
                if key.startswith("test_frozen_dreamguard_"): del sys.modules[key]

    def make_report(self, directory):
        obj=runner.Comparison.__new__(runner.Comparison)
        obj.run=Path(directory); obj.v1=obj.run/"v1"; obj.v2=obj.run/"v2"
        obj.v1.mkdir(); obj.v2.mkdir()
        labels=[int(i<99) for i in range(200)]
        full=labels+[int(i<398) for i in range(800)]
        write_result(obj.v1/"atbench.jsonl",labels,[1]*200)
        write_result(obj.v2/"atbench-native.jsonl",full,full)
        write_result(obj.run/"paired-v1.jsonl",labels,[1]*200)
        write_result(obj.run/"paired-v2.jsonl",labels,labels)
        safety=[int(i<38) for i in range(72)]
        write_result(obj.v2/"safetydrift-native.jsonl",safety,safety)
        obj.state=lambda *args,**kwargs: None
        obj.resources=lambda *args,**kwargs: None
        return obj

    def test_report_matches_200_ids_and_recomputes_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            obj=self.make_report(directory)
            obj.report()
            report=json.loads((obj.run/"comparison.json").read_bytes())
            self.assertEqual(report["paired_v1"]["fp"],101)
            self.assertEqual(report["paired_v2"]["fp"],0)
            self.assertEqual(report["delta_v2_minus_v1"]["fpr"],-1.)
            self.assertEqual(report["native_vs_paired_prediction_changes"],{"v1":0,"v2":0})
            self.assertTrue((obj.run/"comparison.md").exists())

    def test_report_rejects_mismatched_case_ids_and_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            obj=self.make_report(directory)
            labels=[int(i<99) for i in range(200)]
            write_result(obj.run/"paired-v2.jsonl",labels,labels,ids=["wrong"]+list(range(1,200)))
            with self.assertRaisesRegex(ValueError,"IDs"):
                obj.report()
            write_result(obj.run/"paired-v2.jsonl",[1-labels[0]]+labels[1:],labels)
            with self.assertRaisesRegex(ValueError,"labels"):
                obj.report()


if __name__=="__main__": unittest.main()
