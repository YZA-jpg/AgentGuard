"""Frozen feature extraction and two-stage DreamGuard optimization."""

import json
import math
import random
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

import torch
from torch.nn.utils.rnn import pad_sequence

from .dreamguard_data import json_text
from .dreamguard_model import safety_loss, world_loss

SEED = 20260701
OBSERVER_REVISION = "cdbee75f17c01a7cc42f958dc650907174af0554"


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf8")
    temporary.replace(path)


def atomic_torch(path, value):
    temporary = Path(str(path) + ".tmp")
    torch.save(value, temporary)
    temporary.replace(path)


def seed_everything(seed):
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def synchronize(device):
    if str(device).startswith("cuda"):
        torch.cuda.synchronize(torch.device(device))


class Encoder:
    """Official Qwen weights; pooling/serialization/token cap are explicit assumptions."""

    def __init__(self, observer, device, max_tokens=2048, layer=31, expected_revision=OBSERVER_REVISION,
                 batch_size=8):
        from transformers import AutoModel, AutoTokenizer

        self.device, self.layer, self.max_tokens = str(device), layer, max_tokens
        self.batch_size = batch_size
        root = Path(observer)
        revision = (root / "revision.txt").read_text().strip()
        if revision != expected_revision:
            raise ValueError(f"Encoder revision differs: {revision}")
        self.tokenizer = AutoTokenizer.from_pretrained(root, local_files_only=True)
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.tokenizer.padding_side = "right"
        dtype = torch.bfloat16 if self.device.startswith("cuda") else torch.float32
        self.model = AutoModel.from_pretrained(root, dtype=dtype, local_files_only=True).to(device).eval()
        self.model.requires_grad_(False)
        self.dimension = self.model.config.hidden_size
        if self.dimension != 2560 or not 1 <= layer <= self.model.config.num_hidden_layers:
            raise ValueError("Unexpected Qwen architecture/layer")
        self.cache, self.token_cap_hits = {}, 0

    def encode(self, text, *, cached=True):
        if cached and text in self.cache:
            return self.cache[text], 0.0
        synchronize(self.device)
        started = perf_counter()
        tokens = self.tokenizer(text or "[No observation]", return_tensors="pt", truncation=True,
                                max_length=self.max_tokens, return_length=True)
        # At cap does not prove truncation; record cap hits, not exact truncated count.
        self.token_cap_hits += int(tokens.pop("length").item() >= self.max_tokens)
        tokens = tokens.to(self.device)
        with torch.inference_mode():
            hidden = self.model(**tokens, output_hidden_states=True, use_cache=False).hidden_states[self.layer]
            mask = tokens["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            vector = ((hidden * mask).sum(1) / mask.sum(1)).float().cpu().squeeze(0).clone()
        synchronize(self.device)
        elapsed = perf_counter() - started
        if cached:
            self.cache[text] = vector
        return vector, elapsed

    def prefetch(self, texts):
        """Batch independent frozen encodings; recurrent inference stays sequential."""
        pending = sorted(set(texts) - self.cache.keys(), key=lambda s: (len(s), s))
        for offset in range(0, len(pending), self.batch_size):
            group = pending[offset:offset+self.batch_size]
            tokens = self.tokenizer([s or "[No observation]" for s in group], return_tensors="pt",
                                    truncation=True, padding=True, max_length=self.max_tokens).to(self.device)
            self.token_cap_hits += int((tokens["attention_mask"].sum(1) >= self.max_tokens).sum().item())
            with torch.inference_mode():
                hidden = self.model(**tokens, output_hidden_states=True, use_cache=False).hidden_states[self.layer]
                mask = tokens["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                vectors = ((hidden * mask).sum(1)/mask.sum(1)).float().cpu()
            for text, vector in zip(group, vectors):
                self.cache[text] = vector.clone()


def extract(examples, encoder, path, identity):
    """Resume only when exact text/labels/splits/encoder identity match."""
    path = Path(path)
    if path.exists():
        saved = torch.load(path, map_location="cpu", weights_only=True)
        if saved["identity"] != identity:
            raise ValueError("Feature-cache provenance differs")
        return saved["rows"]
    partial = path.with_suffix(".partial.pt")
    saved = torch.load(partial, map_location="cpu", weights_only=True) if partial.exists() else None
    if saved and saved["identity"] != identity:
        raise ValueError("Partial feature-cache provenance differs")
    rows = saved["rows"] if saved else []
    if [(r["dataset"], r["id"]) for r in rows] != [(r["dataset"], r["id"]) for r in examples[:len(rows)]]:
        raise ValueError("Partial cache sequence differs")
    for index in range(len(rows), len(examples)):
        if index % 10 == 0 and hasattr(encoder, "prefetch"):
            pending = examples[index:index+10]
            texts = [r["task"] for r in pending]
            texts += [text for r in pending for name in ("observations", "actions", "successors") for text in r[name]]
            encoder.prefetch(texts)
        example = examples[index]
        task, _ = encoder.encode(example["task"])
        vectors = {}
        for name in ("observations", "actions", "successors"):
            vectors[name] = torch.stack([encoder.encode(text)[0] for text in example[name]]) if example[name] else None
        rows.append({**example, "task": task, **vectors})
        if len(rows) % 10 == 0 or len(rows) == len(examples):
            atomic_torch(partial, {"identity": identity, "rows": rows})
            print(json_text({"stage": "features", "completed": len(rows), "total": len(examples)}), flush=True)
    atomic_torch(path, {"identity": identity, "rows": rows})
    return rows


def batch(rows, device, horizon=3, temperature=1.5):
    if not rows:
        raise ValueError("Empty batch")
    task = torch.stack([row["task"] for row in rows]).to(device)
    observations, actions = [pad_sequence([row[key] for row in rows], batch_first=True).to(device)
                             for key in ("observations", "actions")]
    mask = torch.arange(actions.shape[1], device=device)[None] < torch.tensor(
        [len(row["actions"]) for row in rows], device=device)[:, None]
    successors = (pad_sequence([row["successors"] for row in rows], batch_first=True).to(device)
                  if all(row["successors"] is not None for row in rows) else None)
    hazard = torch.zeros_like(mask, dtype=torch.float32)
    prefix, safety_mask = hazard.clone(), mask.clone()
    for index, row in enumerate(rows):
        first = row["first_hazard"]
        if first is not None:
            hazard[index, first] = prefix[index, first] = 1
            for previous in range(max(0, first - horizon), first):
                prefix[index, previous] = math.exp(-(first - previous - 1) / temperature)
            safety_mask[index, first + 1:] = False
        elif row["label"]:
            safety_mask[index] = False
    return task, observations, actions, successors, mask, hazard, prefix, safety_mask


def make_optimizer(model, stage):
    model.configure_stage(stage)
    heads, world = [], []
    for name, parameter in model.named_parameters():
        if parameter.requires_grad:
            (heads if name.startswith(("hazard.", "prefix.", "adapter.")) else world).append(parameter)
    return torch.optim.Adam([{"params": heads, "lr": 2e-4},
                             {"params": world, "lr": 2e-4 * (0.25 if stage == "risk" else 1)}])


def train_stage(model, rows, directory, device, stage, epochs, identity, batch_size=8, seed=SEED):
    """Atomic epoch checkpoints contain Adam moments and RNG state."""
    optimizer = make_optimizer(model, stage)
    path = Path(directory) / f"{stage}-checkpoint.pt"
    start = 0
    seed_everything(seed + (1 if stage == "risk" else 0))
    if path.exists():
        saved = torch.load(path, map_location="cpu", weights_only=True)
        if saved["identity"] != identity or saved["stage"] != stage or saved["model_config"] != asdict(model.config):
            raise ValueError("Checkpoint configuration/provenance differs")
        model.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        for state in optimizer.state.values():
            for key, value in state.items():
                if torch.is_tensor(value) and key != "step":
                    state[key] = value.to(device)
        start = saved["epoch"]
        torch.set_rng_state(saved["torch_rng"])
        if str(device).startswith("cuda") and saved["cuda_rng"]:
            torch.cuda.set_rng_state_all(saved["cuda_rng"])
    if not rows:
        raise ValueError("Training set is empty")
    model.train()
    for epoch in range(start, epochs):
        shuffled = rows[:]
        random.Random(seed + (1000 if stage == "risk" else 0) + epoch).shuffle(shuffled)
        losses = []
        for offset in range(0, len(shuffled), batch_size):
            task, observations, actions, successors, mask, hazard, prefix, safe_mask = batch(shuffled[offset:offset+batch_size], device)
            if stage == "world" and successors is None:
                raise ValueError("World training requires successor targets")
            output = model(task, observations, actions, successors if stage == "world" else None)
            loss = world_loss(output, successors, mask) if stage == "world" else safety_loss(output, hazard, prefix, safe_mask)
            if not torch.isfinite(loss):
                raise FloatingPointError(f"Nonfinite {stage} loss")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach()))
        record = {"stage": stage, "epoch": epoch + 1, "epochs": epochs, "loss": sum(losses)/len(losses)}
        atomic_torch(path, {"identity": identity, "stage": stage, "epoch": epoch + 1,
                           "model_config": asdict(model.config), "model": model.state_dict(),
                           "optimizer": optimizer.state_dict(), "torch_rng": torch.get_rng_state(),
                           "cuda_rng": torch.cuda.get_rng_state_all() if str(device).startswith("cuda") else [],
                           "record": record})
        with (Path(directory) / "training.jsonl").open("a", encoding="utf8") as log:
            log.write(json_text(record) + "\n")
        print(json_text(record), flush=True)
