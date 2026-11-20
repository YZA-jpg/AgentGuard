# Pro Reference Reproduction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Prepare and verify code offline; the user will launch the actual benchmark.

**Goal:** Prepare one command to retest Pro against the observable configuration of `deepseek_result` (425/939 targeted successes).

**Architecture:** Extend the existing official runner with optional temperature omission and explicit user-task exclusions. Keep the pinned author package, dependency lock, original pipeline and checker. A read-only reference check validates all selected IDs, initial prompts and generated injection dictionaries before the user starts API evaluation.

**Tech Stack:** Python 3.10+, official AgentDojo 0.1.35 / v1.2.2, OpenAI-compatible API, unittest, bash, tmux.

---

1. Add `--temperature provider` (omit the field rather than send null) and repeated `--exclude-user-task SUITE:ID`. Maintain explicit-zero defaults for existing Flash configurations; record exclusions/default omissions in metadata.
2. Extend the offline verifier to accept omitted temperature when requested. Add meaningful fake-SDK and scope tests; do not call an LLM during development.
3. Add `scripts/check-pro-reference.py` to compare all reference case IDs, initial prompts and native injection payloads and write input hashes/configuration limits. Do not copy stored model replies or mid-run monitor messages into fresh evaluations.
4. Add `scripts/run-reference-pro.sh`: Pro ID `deepseek-v4-pro`, attack addressee `Deepseek v4 Pro`, original no-defense prompt, native tools/checkers, exclude Slack users 7 and 17, four API processes, provider defaults for temperature/thinking/output cap. Run an eight-case smoke before the 35 capability checks plus 939 reference-matched attack cases. Save native/API traces and automatic offline verification.
5. Document that the historical endpoint, exact serving snapshot and sampling/thinking values are absent from the logs. Use the user's current configured endpoint without claiming exact service replication. Preserve the special Banking reference record's extra monitor feedback as an audit note, not a new instruction to the agent.
6. Sync code and run only offline checks on data1, back up code/docs on GitHub, and give the user the tmux launch command. Do not launch the Pro benchmark or monitor it.
