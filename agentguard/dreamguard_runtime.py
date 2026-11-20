"""Causal candidate review and fixed-trajectory DreamGuard evaluation."""

from dataclasses import asdict
from pathlib import Path
from time import perf_counter

import torch

from .dreamguard_data import json_text
from .dreamguard_policy import Evidence, PolicyConfig, first_intervention, metrics
from .dreamguard_training import synchronize


def policy_config(config):
    return PolicyConfig(**{k: config[k] for k in asdict(PolicyConfig())})


@torch.inference_mode()
def predict(model, rows, device):
    """Full score streams for calibration only; no policy/threshold access here."""
    model.eval()
    results = []
    for row in rows:
        task = row["task"].unsqueeze(0).to(device)
        hidden = model.initial(task)
        hazard_scores, prefix_scores = [], []
        for observation, action in zip(row["observations"], row["actions"]):
            hidden, hazard, prefix, _, _ = model.step(hidden, observation.unsqueeze(0).to(device), action.unsqueeze(0).to(device), task)
            hazard_scores.append(float(hazard.sigmoid().item()))
            prefix_scores.append(float(prefix.sigmoid().item()))
        results.append({"id": row["id"], "dataset": row["dataset"], "label": row["label"],
                        "first_hazard": row["first_hazard"], "hazard_scores": hazard_scores,
                        "prefix_scores": prefix_scores})
    return results


class DreamGuardSession:
    """One trajectory: review a proposed action, then commit only after execution.

    Inputs contain no successor/gold annotation. This class never executes tools.
    """

    def __init__(self, model, encoder, task, config, device):
        self.model, self.encoder, self.device = model.eval(), encoder, device
        self.config = policy_config(config)
        self.task_text = task
        self.task, self.hidden, self.evidence = None, None, Evidence()
        self.pending, self.generation = None, 0

    @torch.inference_mode()
    def review(self, observation, action):
        synchronize(self.device)
        started = perf_counter()
        if self.task is None:
            self.task = self.encoder.encode(self.task_text, cached=False)[0].unsqueeze(0).to(self.device)
            self.hidden = self.model.initial(self.task)
        observation = self.encoder.encode(observation, cached=False)[0].unsqueeze(0).to(self.device)
        action = self.encoder.encode(action, cached=False)[0].unsqueeze(0).to(self.device)
        hidden, hazard, prefix, _, _ = self.model.step(self.hidden, observation, action, self.task)
        hazard, prefix = float(hazard.sigmoid().item()), float(prefix.sigmoid().item())
        evidence, score, decision = self.evidence.propose(hazard, prefix, self.config)
        self.generation += 1
        self.pending = (self.generation, hidden, evidence, decision)
        synchronize(self.device)
        return {"generation": self.generation, "hazard": hazard, "prefix": prefix,
                "fused": score, "decision": decision, "latency_seconds": perf_counter()-started}

    def commit(self, generation):
        """Caller confirms current PASS action ran; reject stale or held candidates."""
        if self.pending is None or self.pending[0] != generation or self.pending[3] != "PASS":
            raise ValueError("Only the current PASS candidate can be committed")
        _, self.hidden, self.evidence, _ = self.pending
        self.pending = None


@torch.inference_mode()
def cached_steps(model, row, config, device):
    """Stop computation at the first intervention, even with cached embeddings."""
    task = row["task"].unsqueeze(0).to(device)
    hidden, evidence = model.initial(task), Evidence()
    policy = policy_config(config)
    for observation, action in zip(row["observations"], row["actions"]):
        synchronize(device)
        started = perf_counter()
        hidden, hazard, prefix, _, _ = model.step(hidden, observation.unsqueeze(0).to(device), action.unsqueeze(0).to(device), task)
        hazard, prefix = float(hazard.sigmoid().item()), float(prefix.sigmoid().item())
        evidence, score, decision = evidence.propose(hazard, prefix, policy)
        synchronize(device)
        yield {"hazard": hazard, "prefix": prefix, "fused": score,
               "decision": decision, "latency_seconds": perf_counter()-started}
        if decision != "PASS":
            break


def evaluate(model, rows, config, output, metadata, device, encoder=None, raw_examples=None):
    model.eval()
    summaries, latencies = [], []
    initial_cap_hits = encoder.token_cap_hits if encoder else 0
    raw = {r["id"]: r for r in raw_examples or []}
    with Path(output).open("x", encoding="utf8") as stream:
        stream.write(json_text({"record_type": "run_metadata", **metadata, "calibration": config}) + "\n")
        for row in rows:
            if encoder:
                text = raw[row["id"]]
                session = DreamGuardSession(model, encoder, text["task"], config, device)
                steps = []
                for observation, action in zip(text["observations"], text["actions"]):
                    result = session.review(observation, action)
                    steps.append(result)
                    if result["decision"] != "PASS":
                        break
                    session.commit(result["generation"])
            else:
                steps = list(cached_steps(model, row, config, device))
            if not steps:
                raise ValueError(f"Empty evaluation case: {row['id']}")
            latencies.extend(result["latency_seconds"] for result in steps)
            scored = {"id": row["id"], "label": row["label"], "first_hazard": row["first_hazard"],
                      "hazard_scores": [s["hazard"] for s in steps], "prefix_scores": [s["prefix"] for s in steps]}
            first = first_intervention(scored, config)
            record = {"record_type": "case", **scored, "prediction": int(first is not None),
                      "first_intervention": first, "steps": steps, "status": "ok"}
            stream.write(json_text(record) + "\n")
            stream.flush()
            summaries.append(scored)
        summary = {"record_type": "overall_summary", "total_cases": len(rows), "completed_cases": len(summaries),
                   "error_cases": 0, **metrics(summaries, config), "successful_reviews": len(latencies),
                   "mean_guard_latency_seconds": sum(latencies)/len(latencies) if encoder else None,
                   "mean_head_latency_seconds": sum(latencies)/len(latencies) if not encoder else None,
                   "latency_protocol": "uncached sequential text-to-decision; task encoding on first call" if encoder else
                                       "cached embeddings; neural head only; not paper end-to-end latency",
                   "encoder_token_cap_hits": encoder.token_cap_hits - initial_cap_hits if encoder else None,
                   "evaluation_protocol": "fixed-trajectory pre-action detection; no counterfactual ASR/utility"}
        stream.write(json_text(summary) + "\n")
    print(json_text(summary), flush=True)
    return summary
