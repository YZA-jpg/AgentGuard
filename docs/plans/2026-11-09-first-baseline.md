# First baseline implementation plan

**Goal** — Run AgentDoG 1.5 coarse moderation against recorded ATBench trajectories and before tool calls in AgentDojo v1.2.2.

**Architecture** — A shared guard contract handles trajectory classification and proposed actions. The live adapter composes the existing AgentDojo pipeline, executor, and IPIGuard scoring functions. Each run writes its configuration, case records, and summary to a separate JSONL file.

**Stack** — Python, Transformers and PyTorch for the guard, and the existing IPIGuard checkout and DashScope environment for the task agent.

1. Implement guard input, output, coarse prompt, and strict judgment parsing in `agentguard/guard.py`. Keep model loading separate from scoring so tests can inject deterministic outputs.
2. Implement `agentguard/atbench.py` for both official JSON schemas. Validate IDs and keep gold metadata out of guard inputs. Test the binary scoring and error counts.
3. Implement `agentguard/agentdojo.py` around IPIGuard's existing pipeline and scoring. Test mixed allow/block calls, blocked side effects, and guard errors.
4. Expose both runners in `agentguard/__main__.py`. Verify locally with `python -m unittest discover -s tests`, then with the IPIGuard Python environment for the live adapter tests.
5. Commit and push source files to the AgentGuard GitHub repository. Deploy the same commit to `/data1/yaoziao/agentguard` and verify one official-checkpoint case per benchmark.
