import json
import math
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from .atbench import recorded_candidate
from .guard import Decision, GuardError, Review, Verdict, json_text

UPSTREAM_REVISION = "87579ab60ce6b13f38f7d1f531b6a906656f2748"
OBSERVER_REVISION = "1cfa9a7208912126459214e8b04321603b3df60c"
OBSERVER_LAYER = 32
MAX_PROMPT_TOKENS = 7500


def use_upstream(path: Path) -> None:
    path = path.resolve()
    git = ["git", "-C", str(path)]
    revision = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
    changes = subprocess.check_output([*git, "status", "--porcelain", "--untracked-files=no"], text=True)
    if revision != UPSTREAM_REVISION or changes:
        raise ValueError(f"Expected an unmodified TRACES checkout at {UPSTREAM_REVISION}")
    sys.path.insert(0, str(path))


def content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(isinstance(block, dict) and block.get("type") == "text" for block in content):
        return "\n".join(block["text"] for block in content)
    return json_text(content) if content is not None else ""


def tool_text(call) -> str:
    if hasattr(call, "model_dump"):
        call = call.model_dump(mode="json")
    return json_text({
        "name": call.get("name", call.get("function")),
        "arguments": call.get("arguments", call.get("args", {})),
    })


def to_events(context: Review) -> list[dict]:
    events = []

    def add(kind, text):
        if text:
            events.append({"event_idx": len(events), "event_type": kind, "text": text})

    for message in context.history:
        role = message["role"]
        content = content_text(message.get("content"))
        if role == "user":
            add("user", content)
        elif role in ("tool", "environment"):
            add("environment", content or message.get("error"))
        elif role == "agent":
            add("agent_thought", message.get("thought"))
            if raw := message.get("action"):
                candidate = recorded_candidate(raw)
                if "name" in candidate:
                    add("agent_action", tool_text(candidate))
                else:
                    add("agent_complete", candidate["response"])
        elif role == "assistant":
            calls = message.get("tool_calls") or []
            add("agent_thought" if calls else "agent_complete", content)
            for call in calls:
                add("agent_action", tool_text(call))

    if context.candidate is not None:
        if "response" in context.candidate:
            add("agent_complete", context.candidate["response"])
        else:
            add("agent_action", tool_text(context.candidate))
    return events


class ActionEndEncoder:
    def __init__(self, observer: str, revision: str, layer: int, device: str):
        import torch
        from extract_atbench_repr_multilayer_action_end import build_messages_through_event
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        self.layer = layer
        self.device = device
        self.build_messages = build_messages_through_event
        self.tokenizer = AutoTokenizer.from_pretrained(observer, revision=revision)
        self.dtype = torch.float32 if device == "cpu" else torch.float16
        self.model = AutoModel.from_pretrained(observer, revision=revision, dtype=self.dtype).to(device).eval()
        if not 1 <= layer <= self.model.config.num_hidden_layers:
            raise ValueError("TRACES layer is outside the observer model")

    def encode(self, events, include_response=False, cache=None):
        targets = [e["event_idx"] for e in events if e["event_type"] == "agent_action"]
        completions = [e["event_idx"] for e in events if e["event_type"] == "agent_complete"]
        if completions and (not targets or include_response and completions[-1] == len(events) - 1):
            targets = sorted(set([*targets, completions[-1]]))
        for index in targets:
            messages = self.build_messages(events, index)
            key = tuple((m["role"], m["content"]) for m in messages)
            if cache is not None and key in cache:
                yield index, cache[key]
                continue
            tokens = self.tokenizer.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=False, return_dict=False, return_tensors="pt",
            )
            tokens = tokens[:, -MAX_PROMPT_TOKENS:].to(self.device)
            with self.torch.inference_mode():
                result = self.model(tokens, output_hidden_states=True, use_cache=False)
                vector = result.hidden_states[self.layer][0, -1].float().cpu().numpy()
            if cache is not None:
                cache[key] = vector
            yield index, vector


def load_head(directory: Path, dimension: int, device: str):
    import config_atbench_trace_v3 as config
    import evaluate_atbench_trace as evaluate

    config.DEVICE = device
    evaluate.ensure_config_defaults()
    args = SimpleNamespace(
        ckpt=str(directory / "traces-stage-b.pt"),
        stage_a_ckpt=str(directory / "stage_a_latent_mechanism.pt"),
    )
    model, _, _ = evaluate.load_model(args, dimension)
    return model


def score(head, vectors, device: str) -> tuple[float, list[float]]:
    import numpy as np
    import torch

    x = torch.from_numpy(np.stack(vectors)).unsqueeze(0).to(device)
    mask = torch.ones(x.shape[:2], dtype=torch.bool, device=device)
    with torch.inference_mode():
        result = head(x, mask)
    risk = result["traj_score"].item()
    states = result["state_scores"][0].tolist()
    if not math.isfinite(risk) or not all(map(math.isfinite, states)):
        raise GuardError("TRACES produced a non-finite risk score")
    return risk, states


class TracesGuard:
    def __init__(self, encoder, head, threshold: float):
        self.encoder = encoder
        self.head = head
        self.threshold = threshold
        self.cache = {}

    def reset(self) -> None:
        self.cache.clear()

    def review(self, context: Review) -> Verdict:
        try:
            response = context.candidate is not None and "response" in context.candidate
            encoded = list(self.encoder.encode(to_events(context), response, self.cache))
            if not encoded:
                raise GuardError("TRACES found no actions to score")
            indices, vectors = zip(*encoded)
            risk, states = score(self.head, vectors, self.encoder.device)
        except GuardError:
            raise
        except Exception as error:
            raise GuardError(f"TRACES review failed ({type(error).__name__})") from error
        return Verdict(
            Decision.BLOCK if risk >= self.threshold else Decision.ALLOW,
            risk,
            {"event_indices": indices, "state_risk_scores": states},
        )


def load_traces(directory: Path, upstream: Path, device: str):
    use_upstream(upstream)
    run = json.loads((directory / "manifest.json").read_bytes())
    encoder = ActionEndEncoder(run["observer"], run["observer_revision"], run["layer"], device)
    head = load_head(directory, encoder.model.config.hidden_size, device)
    return TracesGuard(encoder, head, run["threshold"]), {
        **run, "observer_dtype": str(encoder.dtype), "head_dtype": "float32",
    }
