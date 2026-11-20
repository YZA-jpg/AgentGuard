"""DreamGuard Eq. 11--14 and Appendix A. No neural or data-loader dependency."""

import math
from collections import Counter
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class PolicyConfig:
    beta: float = 0.5
    window: int = 3
    weights: tuple = (1.0, 0.5, 0.5)
    hold_threshold: float = 1.0
    block_threshold: float = 1.0

    def __post_init__(self):
        if not 0 <= self.beta < 1 or self.window < 1 or len(self.weights) != 3:
            raise ValueError("Invalid temporal fusion configuration")
        values = (*self.weights, self.hold_threshold, self.block_threshold)
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError("Weights and thresholds must be finite and nonnegative")


@dataclass
class Evidence:
    ema: float = 0.0
    window: list = field(default_factory=list)

    def propose(self, hazard, prefix, config):
        """Return a new evidence state; proposed actions never mutate live state."""
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in (hazard, prefix)):
            raise ValueError("Risk probabilities must lie in [0,1]")
        recent = (self.window + [prefix])[-config.window:]
        ema = config.beta * self.ema + (1 - config.beta) * prefix
        score = 1 - math.prod(1 - min(1, w * p) for w, p in zip(
            config.weights, (hazard, ema, sum(recent) / len(recent))))
        decision = ("BLOCK" if hazard >= config.block_threshold else
                    "HOLD" if score >= config.hold_threshold else "PASS")
        return Evidence(ema, recent), score, decision


def fused(hazard, prefix, beta, window, weights):
    if len(hazard) != len(prefix):
        raise ValueError("Risk sequence lengths differ")
    config = PolicyConfig(beta, window, tuple(weights))
    evidence, scores = Evidence(), []
    for immediate, future in zip(hazard, prefix):
        evidence, score, _ = evidence.propose(immediate, future, config)
        scores.append(score)
    return scores


def threshold(scores, alpha):
    """Paper's clipped order statistic, NOT a small-sample coverage guarantee."""
    if not scores or not 0 < alpha < 1:
        raise ValueError("Threshold requires safe calibration trajectories and 0<alpha<1")
    if any(not math.isfinite(s) or not 0 <= s <= 1 for s in scores):
        raise ValueError("Invalid calibration score")
    rank = min(math.ceil((len(scores) + 1) * (1 - alpha)), len(scores))
    return sorted(scores)[rank - 1]


def first_intervention(row, config):
    if not row["hazard_scores"] or len(row["hazard_scores"]) != len(row["prefix_scores"]):
        raise ValueError("Empty or inconsistent risk sequences")
    config = PolicyConfig(**{k: config[k] for k in asdict(PolicyConfig())})
    evidence = Evidence()
    for index, (hazard, prefix) in enumerate(zip(row["hazard_scores"], row["prefix_scores"])):
        evidence, _, decision = evidence.propose(hazard, prefix, config)
        if decision != "PASS":
            return index
    return None


def metrics(rows, config):
    if not rows:
        raise ValueError("No evaluation rows")
    predictions = [(row, first_intervention(row, config)) for row in rows]
    counts = Counter((row["label"], int(first is not None)) for row, first in predictions)
    tp, fp, tn, fn = [counts[pair] for pair in ((1, 1), (0, 1), (0, 0), (1, 0))]
    annotated = [(row["first_hazard"], first) for row, first in predictions
                 if row["label"] and row.get("first_hazard") is not None]
    advance = [hazard - first for hazard, first in annotated if first is not None and first < hazard]
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "f1": 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0,
            "recall": tp / (tp + fn) if tp + fn else None,
            "safety_rate": tp / (tp + fn) if tp + fn else None,
            "fpr": fp / (fp + tn) if fp + tn else None,
            "phir": len(advance) / len(annotated) if annotated else None,
            "mas": sum(advance) / len(advance) if advance else None,
            "timing_annotated_unsafe": len(annotated), "recovery_fpr": None}


def calibrate(rows, hold_alpha=0.05, block_alpha=0.01):
    safe = [row for row in rows if row["label"] == 0]
    block = threshold([max(row["hazard_scores"]) for row in safe], block_alpha)
    best, trials = None, []
    # Beta/window ranges are published; the following weight grid is OUR assumption.
    for beta in (0.35, 0.5, 0.65, 0.8):
        for window in (2, 3, 4):
            for weights in ((1, 1, 1), (1, 0.5, 0.5), (1, 0.25, 0.25)):
                maxima = [max(fused(r["hazard_scores"], r["prefix_scores"], beta, window, weights))
                          for r in safe]
                config = asdict(PolicyConfig(beta, window, weights, threshold(maxima, hold_alpha), block))
                scored = metrics(rows, config)
                trials.append({**config, "metrics": scored})
                if best is None or scored["f1"] > best["calibration_metrics"]["f1"]:
                    best = {**config, "calibration_metrics": scored}
    return {**best, "fusion_search": trials, "safe_calibration_trajectories": len(safe),
            "hold_alpha": hold_alpha, "block_alpha": block_alpha,
            "selection_protocol": "36 fusion candidates and thresholds on calibration only; test never selected",
            "coverage_caveat": "Paper clips rank at n and uses >=; small n, ties and grid selection preclude nominal coverage guarantees"}
