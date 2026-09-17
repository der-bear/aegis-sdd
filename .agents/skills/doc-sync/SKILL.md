---
name: doc-sync
description: The procedure for applying a task's documentation obligations — registry drafts, diagram attestation, derived indexes. Use after review and before the gate, exactly once per task, in any runner. Not for writing product code.
---

# Synchronising documentation for one task

Runs **alone**, after the lenses, before the gate. Being the single writer of `docs/`,
`.aegis/registry/` and diagrams is what keeps parallel builders from colliding here — and it
only works if nobody else takes the shortcut.

Input: the task's `handoff.json` and its diff. Nothing else.

## Steps

1. **Apply `registry_drafts`.** Each entry must satisfy its schema. Conventions are in
   `registry-authoring`; read it if you are adding a kind of entry you have not before.

   ```bash
   aegis check registry && aegis fmt
   ```

   Both clean before you continue.

2. **Bring affected diagrams up to date.**

   ```bash
   aegis check docs --task <TASK-ID>     # lists diagrams whose watched sources moved
   ```

   Generated ones: run the generator, confirm the result is diff-clean. Hand-written ones:
   read the diff and update them to match what is now true. Then:

   ```bash
   aegis docs attest <diagram-id> --by <you>
   ```

   **Never attest a diagram you did not actually update.** The digest exists so that a green
   check means someone looked. Attesting blindly turns a working invariant into a green
   light that means nothing, and nobody downstream can tell the difference.

3. **Central documents — only for structural change.** `architecture.md` and ADRs move when
   a boundary, contract or decision moves. A new function is not structural. When in doubt,
   do not write: `doc-authoring` has the rules for what belongs where.

4. **Rebuild derived indexes.**

   ```bash
   aegis index
   ```

5. **Finish green.** `aegis check registry` and `aegis check docs`.

## Rules that decide the hard cases

- **One fact, one home.** Feature detail lives in `.aegis/specs/<feature>/`; central
  documents link to it. If you are about to paste a paragraph that exists elsewhere, link.
- **Generate rather than draw.** An ERD from migrations cannot drift. Hand-write only the
  intent no generator can produce.
- **Nothing outside the profile.** If `doc-profile.json` does not require it, do not create
  it, however useful it looks. The gate reports unrequested documentation as a finding.
- Never edit `.aegis/generated/`, `constitution.md`, `standards/` or any skill. A change
  needed there is a pull request for a human — say so instead of making it.

Report in under 200 words: entries applied, diagrams attested, documents touched, and what
you deliberately did not write.
