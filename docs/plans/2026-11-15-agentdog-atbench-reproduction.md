# AgentDoG ATBench Reproduction Implementation Plan

**Goal:** Measure how the authors' public input format affects AgentDoG 4B on the existing ATBench holdout.

**Architecture:** Select the author template explicitly for ATBench full-trajectory scoring. Render the published trajectory and tool schema with that template, then reuse the existing checkpoint, decoding settings and scorer.

**Tech Stack:** Python, Transformers, pinned AgentDoG template, tmux.

## Steps

1. Add the opt-in input format and verify the rendered prompt contains trajectory roles and tool schemas. Check that it excludes dataset labels and provenance fields.
2. Run the existing tests and run two reserved smoke cases on the server.
3. Score the 200 frozen holdout IDs in a new output file. Compare confusion matrices and counts with the existing same-ID run. Document the template hash, protocol and any limits of the comparison.
4. Audit the existing ATBench inputs and AgentDojo runtime settings against the documented protocols.
