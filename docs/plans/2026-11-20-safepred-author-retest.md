# SafePred author-core retest

Use the unmodified author checkout `YurunChen/SafePred@495890eafce02f9990e494493891c4549114a2dc`. `agentguard/safepred_author.py` imports its real prompt, `LLMBasedWorldModel.simulate`/parser/scorer, `ConversationHistoryManager`, `LLMRuleExtractor` validation/dedup/standard P000, and `SafeAgent._tree_search_planning` at depth 1 with one candidate. The previous handwritten `safepred.py` remains a historical implementation and is not used by the new runner.

## Backbone availability and fixed configuration

- `qwen3-max` returned HTTP 404/model_not_found on the configured DashScope endpoint. The listed `siliconflow/deepseek-v3.2` returned HTTP 400/service not activated. No Pro/newer model is silently substituted.
- Use the paper's separately evaluated original **Qwen3-8B** backbone, official revision `b968826d9c46dd6066d109eabc6255188de91218`. This is not the author's distilled SafePred-8B checkpoint, nor a reproduction of its Qwen3-Max row.
- One A100, BF16, SDPA, local Transformers transport; temperature 0.3, sampling enabled, seed 42, thinking disabled, checkpoint top-p/top-k defaults logged, 4000 maximum new tokens. No training or weight changes.
- Enable both short- and long-term prediction, retain native single prediction step and single candidate/root. Native violation penalty 0.8 and root threshold 0.7. The author API backend is replaced by a local text-generation transport; prompt/parser/risk/root code remains unmodified.
- The native history manager retains the initial user task and the last seven **executed assistant responses**, not seven arbitrary messages. The candidate is separate from history and its result is unavailable.
- Native model context is 40960 total tokens; reserve 4000 for output. Overlong observations are shortened from the middle with head/tail retained; only if necessary are oldest history responses dropped. Task, policies, tool schemas and current candidate/reasoning remain intact. Every shortened input and exact submitted prompt is logged. No YaRN extension is used.
- Native parser format retries (two retries) are retained; at most two outer review attempts are allowed for an error. Log every generation, failure and token count; latency includes retries. Invalid/missing outputs or invented policy IDs are errors, not safe predictions.

## Policies and evaluation

Extract policies using the real author CLI's complete `process_policy_input` workflow (extraction, review, deduplication, policy renumbering and fixed P000), with its LLM transport factory supplied the same frozen Qwen3-8B backbone, temperature 0.3, 8192-token extraction budget. No handwritten five-policy set or per-test-case policy edits. The earlier `LLMRuleExtractor.extract_rules_from_text` preparation is retained as a preliminary artifact, but formal policies use the complete released CLI workflow. Sources are committed under `policies/sources` with attribution:

- ATBench: author-published safety definition and static taxonomy from the pinned AgentDoG unified template, excluding trajectory placeholders/output-format instructions.
- SafetyDrift: author README's global labeling methodology and tool-level/coarse-risk limitations; exclude per-category violation frequencies, lookup tables, test trajectories, scenario risk profiles and expected-safe paths.

Freeze the resulting policy JSON/hash **before** any benchmark inference. Export the extraction prompt/response for inspection. These are new-benchmark policy adaptations; the author has not published matching ATBench/SafetyDrift policy presets. Source-level original benchmark label conventions may differ from a content-level safety judgment and are documented rather than corrected using test outcomes.

Then run two reserved calibration smoke cases to verify execution/parse contracts (not to optimize predicted labels), followed by the fixed **ATBench heldout 200 (99 unsafe/101 safe)** and **SafetyDrift author test 72 (38 unsafe/34 safe)**. All are causal pre-action replay; first intervention marks the trajectory unsafe. Original offline traces cannot execute author action regeneration or plan correction, so this reproduces the author risk-evaluation path on new benchmarks, not the complete online CUA loop or a paper's original dataset table.

Report TP/FP/TN/FN, F1/Recall/FPR, all-review mean seconds, generation tokens, context truncation, failures/retries and coverage. SafetyDrift additionally uses the frozen native first-risk-level-4 boundary for PHIR/MAS. Recovery FPR stays unavailable. Keep old/new results separately because implementation, policies and backbone all change.

## Validation and launch

`tests/test_safepred_author.py` compares actual native prompt bytes, native parser/scorer output and root decisions on controlled fixtures; checks seven-action causal memory, malformed/unknown-policy errors, context preservation and native policy extraction/dedup/P000. The server repeats these tests against its own unmodified author checkout before launch.

All server artifacts stay under `/data1/yaoziao/agentguard`; the model downloader verifies all five safetensors SHA256 hashes against the pinned repository metadata. Run `SAFEPRED_AUTHOR_GPU=4 bash scripts/run-safepred-author.sh` only after weight verification and an idle-GPU check. It serializes all stages on one GPU and uses new timestamped outputs. Original data and old results remain unchanged.
