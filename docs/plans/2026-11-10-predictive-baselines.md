# Predictive baselines

1. Add the SafePred prompt adaptation for the shared execution boundary. Validate strict structured outputs, policy references and action replay without future observations.
2. Wire the pinned TRACES authors' implementation to the frozen ATBench split. Fit on train, calibrate on calibration, and report heldout results through the same scorer.
3. Run unit tests and small server smoke jobs. Keep smoke checkpoints separate from formal checkpoints.
4. Deploy verified changes to the existing server checkout. Give the user foreground commands to run inside tmux and retain per-job logs.
