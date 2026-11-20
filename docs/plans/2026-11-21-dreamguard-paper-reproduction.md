# DreamGuard paper reproduction implementation plan

**Goal:** finish an auditable, runnable implementation of arXiv:2608.05695v1, with author assets preferred and explicit independent-implementation boundaries.

**Architecture:** retain the paper's frozen Qwen encoder, categorical RSSM and two training stages. Separate data adaptation, neural model, temporal policy, training/checkpointing and evaluation. Keep train/calibration/test disjoint; support SafetyDrift testing and ATBench transfer with the same checkpoint and thresholds.

**Tech stack:** existing Python 3.10 server environment, PyTorch, Transformers, NumPy, PyYAML, unittest; all server artifacts under `/data1/yaoziao/agentguard`.

1. Recheck paper, GitHub and Hugging Face releases; record evidence and unavailable details.
2. Replace the legacy 285/72 train/calibration protocol with the verified existing 222/57/72 manifest. Preserve the original test set and exclude development duplicates against it. Actual-input audit additionally removes one training copy of a calibration input: final 221/57/72.
3. Align losses and Adam optimizer; make model configuration explicit; checkpoint optimizer/RNG/epoch and prevent incompatible resume.
4. Implement PASS/HOLD/BLOCK, trajectory-level conformal quantiles, calibration provenance and strict timing metrics; expose a causal session with explicit execution commit.
5. Implement resumable feature extraction and separate prepare/train/evaluate commands. Save measured uncached encoder latency separately from cached head-only evaluation.
6. Add meaningful causal, split, loss-gradient, intervention, resume and synthetic pipeline checks. Run CPU validation only, without formal model training or benchmark execution.
7. Write a Chinese method/code guide, launch scripts and differences matrix; sync tested code to the server and GitHub. User launches actual training and formal evaluation.

## Source audit (2026-11-21)

- Paper: https://arxiv.org/html/2608.05695v1 (method §3, algorithms, Appendix A and C.1/C.8).
- GitHub repository-name API search and exact-title web search found `ioo0s/DreamGuard-reproduction`, explicitly an independent reproduction. Its README states synthetic source training, unpublished fusion weights and checkpoints excluded from Git. It is not author code.
- Hugging Face model/dataset API searches for DreamGuard found no matching paper checkpoint or dataset. An unrelated image model is excluded.
- No author repository or checkpoint could be verified from these public sources; this is a search finding, not a claim that a private or future release cannot exist.
- Reuse the verified Qwen author snapshot `Qwen/Qwen3-4B-Instruct-2507`, revision `cdbee75f17c01a7cc42f958dc650907174af0554`, already on the server. The DreamGuard neural/training implementation is ours.
- Paper retains the successor **posterior** for its auxiliary observation loss (§3.3); retain this. Risk heads receive only the predicted successor **prior**. The prefix-label exponent is `(hazard-step-1)/1.5`; retain its value 1 at the immediately preceding step.
- Paper explicitly clips the conformal order statistic at n and uses `>=`; retain this, but report small-sample/tie limitations instead of asserting a nominal 1% guarantee.

Detailed final settings and uncertainties: `docs/dreamguard-reproduction-zh.md`.
