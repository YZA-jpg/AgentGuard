"""DreamGuard method reproduction based on arXiv:2608.05695."""

from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F


@dataclass(frozen=True)
class ModelConfig:
    dimension: int = 2560
    hidden_size: int = 1024
    variables: int = 32
    classes: int = 32
    mlp_size: int = 512
    adapter_size: int = 256
    adapter_scale: float = 0.25
    # The paper does not publish its evaluation sampling implementation.
    eval_latent: str = "argmax"

    def __post_init__(self):
        if min(self.dimension, self.hidden_size, self.variables, self.classes,
               self.mlp_size, self.adapter_size) < 1:
            raise ValueError("Model dimensions must be positive")
        if self.eval_latent not in ("argmax", "sample"):
            raise ValueError("eval_latent must be argmax or sample")


def projection(inputs, outputs, width=512):
    return nn.Sequential(
        nn.Linear(inputs, width), nn.LayerNorm(width), nn.SiLU(), nn.Linear(width, outputs),
    )


class RiskWorldModel(nn.Module):
    def __init__(self, dimension=2560, *, config=None):
        super().__init__()
        self.config = config or ModelConfig(dimension=dimension)
        dimension = self.dimension = self.config.dimension
        self.classes = self.config.classes
        self.variables = self.config.variables
        self.hidden_size = self.config.hidden_size
        stochastic = self.classes * self.variables
        def mlp(inputs, outputs):
            return projection(inputs, outputs, self.config.mlp_size)
        self.initial = mlp(dimension, self.hidden_size)
        self.transition_norm = nn.LayerNorm(stochastic + dimension)
        self.transition = nn.GRUCell(stochastic + dimension, self.hidden_size)
        self.posterior = mlp(self.hidden_size + dimension, stochastic)
        self.prior = mlp(self.hidden_size, stochastic)
        self.observation = mlp(self.hidden_size + stochastic, dimension)
        self.adapter = nn.Sequential(nn.Linear(dimension, self.config.adapter_size), nn.SiLU(),
                                     nn.Linear(self.config.adapter_size, dimension))
        context = self.hidden_size + stochastic + 2 * dimension
        self.hazard = mlp(context, 1)
        self.prefix = mlp(context, 1)

    def configure_stage(self, stage):
        """Stage 2 freezes GRU+its input norm; only risk-path modules get gradients."""
        if stage not in ("world", "risk"):
            raise ValueError(stage)
        for name, parameter in self.named_parameters():
            parameter.requires_grad_(stage == "world" or not name.startswith(
                ("transition.", "transition_norm.", "observation.")))

    def latent(self, logits):
        logits = logits.reshape(-1, self.variables, self.classes)
        if self.training:
            state = F.gumbel_softmax(logits, tau=1.0, hard=True, dim=-1)
        elif self.config.eval_latent == "sample":
            state = F.one_hot(torch.distributions.Categorical(logits=logits).sample(),
                              self.classes).to(logits.dtype)
        else:
            state = F.one_hot(logits.argmax(-1), self.classes).to(logits.dtype)
        return state.flatten(1), logits

    def step(self, hidden, observation, action, task):
        posterior, logits = self.latent(self.posterior(torch.cat((hidden, observation), -1)))
        prior = self.prior(hidden).reshape(-1, self.variables, self.classes)
        hidden = self.transition(self.transition_norm(torch.cat((posterior, action), -1)), hidden)
        predicted, _ = self.latent(self.prior(hidden))
        context = torch.cat((hidden, predicted, action + self.config.adapter_scale * self.adapter(action),
                             task + self.config.adapter_scale * self.adapter(task)), -1)
        return hidden, self.hazard(context).squeeze(-1), self.prefix(context).squeeze(-1), logits, prior

    def forward(self, task, observations, actions, successors=None):
        hidden = self.initial(task)
        hazards, prefixes, predictions, posterior_logits, prior_logits = [], [], [], [], []
        for index in range(observations.shape[1]):
            observation = observations[:, index]
            action = actions[:, index]
            hidden, hazard, prefix, logits, prior = self.step(hidden, observation, action, task)
            posterior_logits.append(logits)
            prior_logits.append(prior)
            hazards.append(hazard)
            prefixes.append(prefix)
            if successors is not None:
                posterior_next, _ = self.latent(
                    self.posterior(torch.cat((hidden, successors[:, index]), -1))
                )
                predictions.append(self.observation(torch.cat((hidden, posterior_next), -1)))
        return {
            "hazard": torch.stack(hazards, 1), "prefix": torch.stack(prefixes, 1),
            "predicted": torch.stack(predictions, 1) if predictions else None,
            "posterior": torch.stack(posterior_logits, 1),
            "prior": torch.stack(prior_logits, 1),
        }


def masked_trajectory_mean(values, mask):
    """Equations 4/8 average steps within each trajectory, then trajectories."""
    counts = mask.sum(1)
    valid = counts > 0
    if not valid.any():
        raise ValueError("Loss has no supervised trajectory")
    return ((values * mask).sum(1)[valid] / counts[valid]).mean()


def world_loss(result, successors, mask, pred_weight=1.25, kl_weight=0.03, free_bits=0.2):
    mask = mask.bool()
    predicted = result["predicted"][mask]
    target = successors[mask]
    predicted = predicted - predicted.mean(0, keepdim=True)
    target = target - target.mean(0, keepdim=True)
    prediction_loss = torch.zeros_like(mask, dtype=predicted.dtype)
    prediction_loss[mask] = 1 - F.cosine_similarity(predicted, target, dim=-1)
    posterior = result["posterior"][mask]
    prior = result["prior"][mask]

    def kl(left, right):
        log_left = left.log_softmax(-1)
        values = torch.zeros_like(mask, dtype=left.dtype)
        values[mask] = (log_left.exp() * (log_left - right.log_softmax(-1))).sum(
            (-1, -2)).clamp_min(free_bits)
        return values

    return masked_trajectory_mean(pred_weight * prediction_loss + kl_weight * (
        kl(posterior.detach(), prior) + kl(posterior, prior.detach())), mask)


def safety_loss(result, hazard, prefix, mask):
    mask = mask.bool()
    values = F.binary_cross_entropy_with_logits(result["hazard"], hazard, reduction="none") + (
        F.binary_cross_entropy_with_logits(result["prefix"], prefix, reduction="none"))
    return masked_trajectory_mean(values, mask)
