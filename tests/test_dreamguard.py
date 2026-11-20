import importlib.util
import json
import math
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest


class PolicyTests(unittest.TestCase):
    def test_projection_deduplication_preserves_test_ids(self):
        from agentguard.dreamguard_data import projection_deduplicate, verify_examples
        def row(case_id, split, outcome):
            return {"id":case_id,"dataset":"x","split":split,"task":"task","observations":[""],
                    "actions":["act"],"successors":[outcome],"label":0,"first_hazard":None}
        kept,removed,duplicates=projection_deduplicate([row("train","train","a"),
            row("cal","calibration","b"),row("test1","heldout","c"),row("test2","heldout","d")])
        self.assertEqual({r["id"] for r in kept},{"test1","test2"})
        self.assertEqual({r["id"] for r in removed},{"train","cal"})
        self.assertEqual(len(duplicates),1)
        verify_examples(kept)

    def test_three_decisions_and_block_precedence(self):
        from agentguard.dreamguard_policy import Evidence, PolicyConfig
        policy = PolicyConfig(beta=0, window=2, weights=(1, 1, 0), hold_threshold=.7, block_threshold=.9)
        state = Evidence()
        self.assertEqual(state.propose(.05, .05, policy)[2], "PASS")
        self.assertEqual(state.propose(.1, .9, policy)[2], "HOLD")
        self.assertEqual(state.propose(.95, .9, policy)[2], "BLOCK")
        self.assertEqual(state, Evidence())  # Proposals do not commit execution.

    def test_paper_quantile_keeps_clipping_and_tie_behavior(self):
        from agentguard.dreamguard_policy import threshold
        self.assertEqual(threshold([.1, .2, .3], .01), .3)
        with self.assertRaises(ValueError):
            threshold([], .05)

    def test_timing_is_strictly_before_hazard(self):
        from agentguard.dreamguard_policy import metrics
        config = {"beta": 0, "window": 1, "weights": [1, 0, 0], "hold_threshold": .7, "block_threshold": .8}
        def row(label, hazard, scores):
            return {"label": label, "first_hazard": hazard, "hazard_scores": scores, "prefix_scores": [0]*len(scores)}
        result = metrics([row(1, 2, [.1,.9]), row(1, 0, [.9]), row(0, None, [.1])], config)
        self.assertEqual((result["tp"], result["tn"], result["fp"], result["fn"]), (2,1,0,0))
        self.assertEqual(result["phir"], .5)
        self.assertEqual(result["mas"], 1)

    def test_duplicate_inputs_cannot_cross_splits_even_if_labels_differ(self):
        from agentguard.dreamguard_data import verify_examples
        row = {"id":"a", "dataset":"safetydrift", "split":"train", "task":"task", "observations":[""],
               "actions":["act"], "successors":["result"], "label":0, "first_hazard":None}
        with self.assertRaisesRegex(ValueError, "crosses"):
            verify_examples([row, {**row, "id":"b", "split":"heldout", "label":1, "first_hazard":0}])


@unittest.skipUnless(importlib.util.find_spec("torch"), "Requires model dependencies")
class DreamGuardTests(unittest.TestCase):
    def tiny_model(self):
        from agentguard.dreamguard_model import ModelConfig, RiskWorldModel
        return RiskWorldModel(config=ModelConfig(dimension=8, hidden_size=12, variables=2, classes=3,
                                                mlp_size=16, adapter_size=4))

    def rows(self):
        import torch
        return [{"id":str(i), "dataset":"synthetic", "split":"train", "task":torch.randn(8),
                 "observations":torch.randn(4,8), "actions":torch.randn(4,8),
                 "successors":torch.randn(4,8), "label":i, "first_hazard":2 if i else None}
                for i in range(2)]

    def test_successor_labels_and_future_observations_do_not_change_current_risk(self):
        import torch
        from agentguard.dreamguard_model import RiskWorldModel

        torch.manual_seed(2)
        model = self.tiny_model().eval()
        task, observations, actions, successors = (
            torch.randn(2, 8), torch.randn(2, 2, 8), torch.randn(2, 2, 8), torch.randn(2, 2, 8)
        )
        with torch.no_grad():
            first = model(task, observations, actions, successors)
            changed = observations.clone()
            changed[:, 1] += 100
            second = model(task, changed, actions, successors + 100)
        torch.testing.assert_close(first["hazard"][:, 0], second["hazard"][:, 0])
        torch.testing.assert_close(first["prefix"][:, 0], second["prefix"][:, 0])

    def test_world_loss_and_straight_through_gradients_are_finite(self):
        import torch
        from agentguard.dreamguard_model import RiskWorldModel, world_loss

        torch.manual_seed(3)
        model = self.tiny_model().train()
        task, observations, actions, successors = (
            torch.randn(2, 8), torch.randn(2, 2, 8), torch.randn(2, 2, 8), torch.randn(2, 2, 8)
        )
        output = model(task, observations, actions, successors)
        loss = world_loss(output, successors, torch.tensor([[True, True], [True, False]]))
        loss.backward()
        self.assertTrue(torch.isfinite(loss))
        self.assertIsNotNone(model.posterior[0].weight.grad)
        self.assertTrue(all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None))

    def test_risk_training_freezes_gru_and_updates_posterior_and_heads(self):
        import torch
        from agentguard.dreamguard_training import batch, make_optimizer
        from agentguard.dreamguard_model import safety_loss
        model = self.tiny_model().train()
        optimizer = make_optimizer(model, "risk")
        before = model.transition.weight_hh.detach().clone()
        task, obs, actions, _, _, hazard, prefix, mask = batch(self.rows(), "cpu")
        loss = safety_loss(model(task,obs,actions), hazard,prefix,mask)
        optimizer.zero_grad(); loss.backward(); optimizer.step()
        torch.testing.assert_close(before, model.transition.weight_hh)
        self.assertIsNone(model.transition.weight_hh.grad)
        self.assertGreater(float(model.posterior[0].weight.grad.abs().sum()), 0)
        self.assertGreater(float(model.hazard[0].weight.grad.abs().sum()), 0)
        self.assertEqual([g["lr"] for g in optimizer.param_groups], [2e-4,5e-5])

    def test_prefix_labels_and_post_hazard_mask_follow_equation_7(self):
        import torch
        from agentguard.dreamguard_training import batch
        row = self.rows()[1]
        row["first_hazard"] = 2
        *_, hazard, prefix, mask = batch([row], "cpu")
        torch.testing.assert_close(prefix[0], torch.tensor([math.exp(-1/1.5),1.,1.,0.]))
        self.assertEqual(mask.tolist(), [[True,True,True,False]])
        self.assertEqual(hazard.tolist(), [[0.,0.,1.,0.]])

    def test_trajectory_loss_does_not_overweight_long_traces(self):
        import torch
        from agentguard.dreamguard_model import masked_trajectory_mean
        values = torch.tensor([[2.,999.,999.],[4.,4.,4.]])
        mask = torch.tensor([[True,False,False],[True,True,True]])
        self.assertEqual(float(masked_trajectory_mean(values,mask)),3.)

    def test_epoch_resume_restores_optimizer_and_rng(self):
        import torch
        from agentguard.dreamguard_training import train_stage
        torch.manual_seed(42)
        model_a, model_b = self.tiny_model(), self.tiny_model()
        model_b.load_state_dict(model_a.state_dict())
        rows = self.rows()
        with TemporaryDirectory() as first, TemporaryDirectory() as resumed:
            train_stage(model_a, rows, first, "cpu", "world", 2, {"test":1}, batch_size=2)
            train_stage(model_b, rows, resumed, "cpu", "world", 1, {"test":1}, batch_size=2)
            restored = self.tiny_model()  # Deliberately consume RNG before restoring.
            train_stage(restored, rows, resumed, "cpu", "world", 2, {"test":1}, batch_size=2)
            for key, value in model_a.state_dict().items():
                torch.testing.assert_close(value, restored.state_dict()[key], rtol=0, atol=0)
            with self.assertRaisesRegex(ValueError, "provenance"):
                train_stage(restored, rows, resumed, "cpu", "world", 2, {"test":2})

    def test_session_commit_and_cached_scores_agree(self):
        import torch
        from agentguard.dreamguard_runtime import DreamGuardSession, cached_steps
        model = self.tiny_model().eval()
        vectors = {s:torch.randn(8) for s in ("task","obs","act","obs2","act2")}
        class Encoder:
            def encode(self, text, *, cached=True): return vectors[text], 0.
        config = {"beta":.5,"window":3,"weights":[1, .5,.5], "hold_threshold":1., "block_threshold":1.}
        session = DreamGuardSession(model, Encoder(), "task", config, "cpu")
        first = session.review("obs", "act")
        self.assertEqual(session.evidence.window, [])
        session.commit(first["generation"])
        with self.assertRaises(ValueError): session.commit(first["generation"])
        second = session.review("obs2", "act2")
        row = {"task":vectors["task"],"observations":torch.stack([vectors["obs"],vectors["obs2"]]),
               "actions":torch.stack([vectors["act"],vectors["act2"]])}
        cached = list(cached_steps(model,row,config,"cpu"))
        for actual, expected in zip((first,second),cached):
            for name in ("hazard","prefix","fused"):
                self.assertAlmostEqual(actual[name],expected[name],places=6)
        blocked = DreamGuardSession(model, Encoder(), "task", {**config,"block_threshold":0}, "cpu")
        decision = blocked.review("obs","act")
        with self.assertRaises(ValueError): blocked.commit(decision["generation"])

    def test_feature_resume_rejects_changed_source(self):
        import torch
        from agentguard.dreamguard_training import extract
        class Encoder:
            def encode(self,text): return torch.ones(8),0.
        example = {"id":"x","dataset":"synthetic","task":"task","observations":["obs"],
                   "actions":["act"],"successors":["after"]}
        with TemporaryDirectory() as directory:
            path=Path(directory)/"features.pt"
            extract([example],Encoder(),path,{"source":"a"})
            with self.assertRaisesRegex(ValueError,"provenance"):
                extract([example],Encoder(),path,{"source":"b"})

    def test_batched_encoder_masks_padding_and_matches_single_inputs(self):
        import torch
        from types import SimpleNamespace
        from transformers import BatchEncoding
        from agentguard.dreamguard_training import Encoder, OBSERVER_REVISION
        class Tokenizer:
            pad_token_id=0
            def __call__(self,text,**kwargs):
                many=isinstance(text,list)
                sequences=[[ord(c)%13+1 for c in s][:kwargs["max_length"]] for s in (text if many else [text])]
                width=max(map(len,sequences))
                tokens=BatchEncoding({"input_ids":torch.tensor([s+[0]*(width-len(s)) for s in sequences]),
                                      "attention_mask":torch.tensor([[1]*len(s)+[0]*(width-len(s)) for s in sequences])})
                if kwargs.get("return_length"): tokens["length"]=torch.tensor([len(s) for s in sequences])
                return tokens
        class Model(torch.nn.Module):
            config=SimpleNamespace(hidden_size=2560,num_hidden_layers=36)
            def forward(self,input_ids,attention_mask,**kwargs):
                hidden=input_ids.float().unsqueeze(-1).expand(-1,-1,2560)
                return SimpleNamespace(hidden_states=(hidden,)*37)
        with TemporaryDirectory() as directory:
            Path(directory,"revision.txt").write_text(OBSERVER_REVISION)
            with patch("transformers.AutoTokenizer.from_pretrained",return_value=Tokenizer()), \
                 patch("transformers.AutoModel.from_pretrained",return_value=Model()):
                encoder=Encoder(directory,"cpu",max_tokens=20,batch_size=2)
                encoder.prefetch(["short","longer input"])
                for text in ("short","longer input"):
                    cached,_=encoder.encode(text)
                    fresh,_=encoder.encode(text,cached=False)
                    torch.testing.assert_close(cached,fresh)

    def test_synthetic_prepare_train_calibrate_and_evaluate_cli(self):
        import torch
        from agentguard.dreamguard import main
        config = self.tiny_model().config
        rows=[]
        for split in ("train","calibration","heldout"):
            for label in (0,1):
                rows.append({"id":f"{split}-{label}", "dataset":"safetydrift", "split":split,
                             "task":f"task-{split}-{label}", "observations":["","before"],
                             "actions":["inspect","act"],"successors":["before","after"],
                             "label":label, "first_hazard":1 if label else None})
        class Encoder:
            token_cap_hits = 0
            def __init__(self,*args,**kwargs): pass
            def encode(self,text,**kwargs):
                from hashlib import sha256
                values=list(sha256(text.encode()).digest())[:8]
                return torch.tensor(values,dtype=torch.float32)/255,0.
        with TemporaryDirectory() as directory:
            root=Path(directory)
            split=root/"split.json"; split.write_text("{}")
            atbench=root/"atbench.json"; atbench.write_text("[]")
            target=[{**r,"id":"atbench-"+r["id"],"dataset":"atbench","successors":[]}
                    for r in rows if r["split"]=="heldout"]
            argv=["--observer",str(root),"--safetydrift-root",str(root),"--safetydrift-split",str(split),
                  "--out-dir",str(root/"run"),"--evaluation","both","--data",str(atbench),"--device","cpu"]
            with patch("agentguard.dreamguard.source_examples",return_value=(rows,{"counts":{"synthetic":6}})), \
                 patch("agentguard.dreamguard.target_examples",return_value=target), \
                 patch("agentguard.dreamguard.Encoder",Encoder), \
                 patch("agentguard.dreamguard.ModelConfig",return_value=config):
                self.assertEqual(main(argv),0)
                records=[json.loads(line) for line in (root/"run/safetydrift-formal.jsonl").read_text().splitlines()]
                self.assertEqual(records[-1]["completed_cases"],2)
                self.assertIsNotNone(records[-1]["mean_guard_latency_seconds"])
                self.assertTrue((root/"run/risk-checkpoint.pt").exists())
                self.assertTrue((root/"run/atbench-formal.jsonl").exists())
                self.assertEqual(main(argv+["--stage","evaluate","--output-tag","repeat","--latency","cached"]),0)
                cached=[json.loads(line) for line in (root/"run/safetydrift-repeat.jsonl").read_text().splitlines()]
                self.assertEqual([r["prediction"] for r in records[1:-1]],[r["prediction"] for r in cached[1:-1]])
                self.assertIsNone(cached[-1]["mean_guard_latency_seconds"])


if __name__ == "__main__":
    unittest.main()
