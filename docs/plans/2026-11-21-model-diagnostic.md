# Flash / Pro Diagnostic Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. The user explicitly authorized starting this diagnostic batch; the general user-launch preference still applies to other future batches.

**Goal:** Run a frozen 40-case A/B/C diagnostic that separates the requested model change from temperature omission.

**Architecture:** Add an experiment controller around the existing unchanged official runner. Select ten reference case IDs per suite with seed 42, independently of outcomes, and freeze them before any live API call. All groups use author prompts/tools/checkers, model addressee DeepSeek, enabled thinking, and the same unspecified output cap. A=Flash/temperature 0, B=Pro/temperature 0, C=Pro/temperature omitted.

**Tech Stack:** Python standard library, existing official AgentDojo and author dependency lock, four independent API workers, native JSON traces, offline verification, data1/private tmux.

---

1. Implement and unit-check the deterministic, balanced selection and condition definitions; leave the existing native runner unchanged.
2. Freeze selected IDs, reference hashes, controller/native source hashes and request settings. Validate identical system/user prompts, tool schemas and injection dictionaries across groups offline.
3. Run the same one-case Workspace (0,0) acceptance for A/B/C. Only proceed when all API conditions run and independently verify. Preserve errors if the Pro route or explicit thinking parameter is unavailable.
4. Execute the 40-case groups in sequence, with four workers per group; independently verify each and save paired outcome changes and actual thinking/temperature request checks. Do not interpret the diagnostic fraction as overall benchmark ASR.
5. Keep credentials, environments, cache and results on data1. Preserve prior runs and user drafts. Back up code/docs to GitHub, start the explicitly authorized tmux job, confirm execution has begun, and hand over paths without ongoing completion polling.
