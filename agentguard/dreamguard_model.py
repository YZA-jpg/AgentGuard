"""DreamGuard method reproduction based on arXiv:2608.05695."""

import torch
from torch import nn
from torch.nn import functional as F


def projection(inputs, outputs):
    return nn.Sequential(
        nn.Linear(inputs, 512), nn.LayerNorm(512), nn.SiLU(), nn.Linear(512, outputs),
    )


class RiskWorldModel(nn.Module):
    def __init__(self, dimension=2560):
        super().__init__()
        self.dimension = dimension
        self.classes = 32
        self.variables = 32
        self.hidden_size = 1024
        stochastic = self.classes * self.variables
        self.initial = projection(dimension, self.hidden_size)
        self.transition_norm = nn.LayerNorm(stochastic + dimension)
        self.transition = nn.GRUCell(stochastic + dimension, self.hidden_size)
        self.posterior = projection(self.hidden_size + dimension, stochastic)
        self.prior = projection(self.hidden_size, stochastic)
        self.observation = projection(self.hidden_size + stochastic, dimension)
        self.adapter = nn.Sequential(nn.Linear(dimension, 256), nn.SiLU(), nn.Linear(256, dimension))
        context = self.hidden_size + stochastic + 2 * dimension
        self.hazard = projection(context, 1)
        self.prefix = projection(context, 1)

    def latent(self, logits):
        logits = logits.reshape(-1, self.variables, self.classes)
        if self.training:
            state = F.gumbel_softmax(logits, tau=1.0, hard=True, dim=-1)
        else:
            state = F.one_hot(logits.argmax(-1), self.classes).to(logits.dtype)
        return state.flatten(1), logits

    def step(self, hidden, observation, action, task):
        posterior, logits = self.latent(self.posterior(torch.cat((hidden, observation), -1)))
        _, prior = self.latent(self.prior(hidden))
        hidden = self.transition(self.transition_norm(torch.cat((posterior, action), -1)), hidden)
        predicted, _ = self.latent(self.prior(hidden))
        context = torch.cat((hidden, predicted, action + 0.25 * self.adapter(action),
                             task + 0.25 * self.adapter(task)), -1)
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


def world_loss(result, successors, mask):
    mask = mask.bool()
    predicted = result["predicted"][mask]
    target = successors[mask]
    predicted = predicted - predicted.mean(0, keepdim=True)
    target = target - target.mean(0, keepdim=True)
    prediction_loss = (1 - F.cosine_similarity(predicted, target, dim=-1)).mean()
    posterior = result["posterior"][mask]
    prior = result["prior"][mask]

    def kl(left, right):
        log_left = left.log_softmax(-1)
        return (log_left.exp() * (log_left - right.log_softmax(-1))).sum((-1, -2)).clamp_min(0.2).mean()

    return 1.25 * prediction_loss + 0.03 * (
        kl(posterior.detach(), prior) + kl(posterior, prior.detach())
    )


def safety_loss(result, hazard, prefix, mask):
    mask = mask.bool()
    return F.binary_cross_entropy_with_logits(result["hazard"][mask], hazard[mask]) + (
        F.binary_cross_entropy_with_logits(result["prefix"][mask], prefix[mask])
    )
