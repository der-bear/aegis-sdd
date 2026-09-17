---
name: build-task
description: The procedure for implementing one Aegis task inside its write lease — orient, plan, build with tests, verify, hand off. Use when implementing a task that has a packet, in any runner. Not for review, documentation or planning.
---

# Implementing one task

This is the procedure, not a role. Claude Code preloads it into the builder subagent; Codex
and a human follow the same file. The agent profile decides which tools are available — the
steps below do not change with the runner.

The packet is the whole brief: objective, requirements, acceptance criteria, write lease,
verification commands, boundaries. Read nothing beyond it and the files you are about to
change.

## Steps

1. **Orient inside the lease.** Open what the packet names, plus the files you will edit.
   Do not survey the repository — that is what the packet exists to prevent.

2. **Plan in ten lines or fewer.** Files to touch, order, and the test that proves it works.
   If the plan needs a path outside the lease, stop here and return a lease-expansion
   request. Taking the write and explaining afterwards destroys the one property that makes
   parallel work safe.

3. **Write code and tests together.** The edge cases in the packet are the test list; they
   were written to be executed. A behaviour with no test that would fail without it is not
   finished.

4. **Verify before claiming.** Run every verification command in the packet and fix until
   green. "Should pass" is a failure report.

5. **Draft registry entries — do not write them.** A new endpoint, event, environment
   variable or feature flag goes into `registry_drafts` in the handoff. Applying it is the
   documentation step's job, serialized, which is why parallel builders never collide there.

6. **Write the handoff, then stop.**

   ```json
   {"task": "TASK-042-01", "agent": "aegis-builder", "summary": "...",
    "changed_files": ["..."],
    "verification": [{"command": "...", "result": "pass"}],
    "deviations": ["..."], "registry_drafts": [{"registry": "env", "id": "..."}],
    "lease_expansion_request": []}
   ```

   `agent` is required: it is how the gate proves the reviewer was somebody else. Put your
   agent type or model id there, honestly — an anonymous builder fails the gate rather than
   quietly satisfying the independence check.

   It is schema-validated, and it is what a restarted session reads once your context is
   gone. Then report in under 300 words: what changed, how it was verified, what you
   deviated from and why. Never restate the code — the diff is already readable.

## Never

- Write outside the lease. Everything else is read-only, including `.aegis/generated/`,
  `constitution.md`, `standards/`, `registry/` and every skill.
- Weaken, skip, mark expected-failure, or delete a test to reach green. A wrong test goes in
  `deviations` and stays failing.
- Fix something outside the task because you noticed it. Note it in `deviations`.
- Spawn a subagent.

## When review comes back

Fix findings of severity 3 and above. For one you disagree with, write a line of why in
`deviations` — a human reads it.

If a finding returns after you marked it fixed, the mechanism is wrong, not the patch. Say
so and propose the simpler design. The gate fails on a reopened finding precisely to stop a
third attempt at patching around it.
