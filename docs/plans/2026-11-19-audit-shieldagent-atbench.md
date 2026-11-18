# SafetyDrift comparison audit and ShieldAgent ATBench plan

The reference F1 values 45.3/87.1/96.4 are from DreamGuard Table 1, not the original SafetyDrift paper. Our trajectory-level F1 formula and first-intervention convention agree with DreamGuard Appendix A. The implementations and data protocols do not yet constitute an exact reproduction of that table.

| Method | Reference F1 | Our SafetyDrift F1 | Verified difference |
|---|---:|---:|---|
| SafePred | 45.3% | 73.68% | Existing DeepSeek-v4-pro prompt adaptation: five fixed policies, no plan, any policy flag blocks. |
| TRACES | 87.1% | 96.00% | Author ATBench training modules adapted to 222/57/72; calibration-selected threshold 0.8. |
| DreamGuard | 96.4% | No independent SafetyDrift test | Old checkpoint calibrated on 69 of these 72 test IDs. Its ATBench 66.22% F1 and source calibration 98.70% F1 are different experiments. |

SafePred reference Recall/FPR are 37.0/44.4%, versus our 92.11/64.71%. Our 22 false positives are split equally between code_debugging and sysadmin; the first blocked review flags P000 in 12, P001 in 12 and P004 in 12 (overlapping counts). The binary `violated_policy_ids != []` rule, generalized policies and different world-model backbone are concrete protocol differences. Original SafePred includes policy extraction/deduplication, graded risk mapping and corrective decision/plan guidance; our fixed-trajectory adaptation does not execute that online corrective loop.

TRACES reference Recall/FPR are 96.3/33.3%, versus our 94.74/2.94%. Most of the F1 difference is associated with lower false alarms, not higher recall. Reusing saved scores at the author's published ATBench threshold 0.3 yields TP/FP/TN/FN=36/3/31/2, F1 93.51%, Recall 94.74%, FPR 8.82%. Thus threshold choice explains 2.49 percentage points here, not the whole 8.90-point difference. This is a descriptive sensitivity calculation, not a new independent test or a threshold selected using the test labels.

Training and calibration were audited: no held-out features or exact full message-sequence duplicates occur across splits. The source split is nevertheless by trajectory: all 37 test scenarios occur in training. DreamGuard reports a cleaned datapool but does not supply its exact split IDs or full baseline adaptations in the public paper. A 96.3% recall cannot be a single-run integer count out of our 38 positives (36/38=94.7%, 37/38=97.4%); a different denominator or averaging protocol must be checked before matching table values.

## Recommended reruns

1. Keep the current 72 test IDs fixed for our paired comparison; keep 222 training/57 calibration for trainable methods. Obtain the DreamGuard author's cleaned IDs, configurations and prompts before calling any separate run an exact Table-1 reproduction.
2. Prioritize a SafePred implementation ablation: restore the paper's policy integration, full published prompt/output/risk mapping, keep DeepSeek-v4-pro initially to isolate implementation changes, then separately test a verified available original-backbone configuration. Retain the existing SafePred-prompt row.
3. For TRACES, report the already-computed fixed-0.3 sensitivity row; repeat author-code training with predeclared seeds 42/43/44, fixed folds and calibration-only selection. Report mean/std and test uncertainty, rather than selecting a seed that resembles 87.1%.
4. Retrain the DreamGuard method reproduction on 222 training and calibrate on 57 before an independent 72-case SafetyDrift test. Do not reuse the old 69-case calibration checkpoint as an independent test. Align the documented Adam/AdamW and latent/serialization differences where the paper specifies them.
5. Add a separately labeled scenario-group-heldout diagnostic if assessing unseen-scenario generalization. This complements the author trajectory split; it does not replace it or establish the cause of the published-table difference.

## ShieldAgent identity correction

The previous investigation conflated two names: Chen et al.'s ICML policy-reasoning system and the THU Agent-SafetyBench scorer. `thu-coai/ShieldAgent` is an official Qwen2.5-7B-based checkpoint with public inference code. This ATBench run uses the THU scorer and is not an implementation of the ICML rule-circuit system.

## ShieldAgent execution

- Official model revision: `a62f8413908bf3dbb1aea2edfbbeae54fdfd383c`.
- Official scorer repository revision: `74feea8de601b3a1449a93fcf70017fe61556f73`.
- Load the author's `create_ipt`, `format_resp` and greedy 10-new-token scoring configuration without rewriting the prompt. Map ATBench roles, calls and tool descriptions to the author's dialogue/environment fields; exclude gold labels/reasons.
- Classify all 1,000 current ATBench trajectories once and separately summarize the existing paired 200 heldout IDs. No model training or threshold fitting.
- FP16, one GPU, batch 1. Use PyTorch SDPA instead of an additional flash-attention package, and omit torch.compile; record these execution differences. Preserve the author's manual Qwen wrapper with empty system text. Retain unambiguous end-of-output answers if the short generation ends immediately after the label.
- Verify the two-case calibration smoke, all case outputs and metrics, then save results, weight hashes and code/prompt versions. Back up implementation and summaries to GitHub.

Sources: [DreamGuard Table 1 and Appendix A–C](https://arxiv.org/html/2608.05695v1), [SafePred methodology](https://arxiv.org/html/2602.01725v1#S3), [TRACES author code](https://github.com/lab-flair/TRACES), [THU ShieldAgent](https://huggingface.co/thu-coai/ShieldAgent), [official scorer](https://github.com/thu-coai/Agent-SafetyBench/blob/main/score/eval_with_shield.py).
