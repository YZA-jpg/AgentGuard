import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec("torch"), "Requires model dependencies")
class DreamGuardTests(unittest.TestCase):
    def test_successor_labels_and_future_observations_do_not_change_current_risk(self):
        import torch
        from agentguard.dreamguard_model import RiskWorldModel

        torch.manual_seed(2)
        model = RiskWorldModel(dimension=8).eval()
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
        model = RiskWorldModel(dimension=8).train()
        task, observations, actions, successors = (
            torch.randn(2, 8), torch.randn(2, 2, 8), torch.randn(2, 2, 8), torch.randn(2, 2, 8)
        )
        output = model(task, observations, actions, successors)
        loss = world_loss(output, successors, torch.tensor([[True, True], [True, False]]))
        loss.backward()
        self.assertTrue(torch.isfinite(loss))
        self.assertIsNotNone(model.posterior[0].weight.grad)
        self.assertTrue(all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None))
