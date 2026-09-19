# Constitution

Authoritative for: the principles below, and nothing else.
References only: everything in `.aegis/generated/` (compiled — see `answers.json`).

**This file is written and changed by a human. Agents may open a pull request against it;
they may not edit it.** Generated configuration lives in `.aegis/generated/policy.json`
and is referenced from here rather than copied, so the two can never disagree.

## Purpose

Aegis is a spec-driven development framework for AI coding agents — Claude Code, Codex, or
a person at a terminal: task packets with exclusive write leases, read-only review lenses,
and deterministic gates over artifacts kept in git. It exists so that whatever must happen
on every task is executed by a script rather than requested in a prompt. It has failed if a
task can reach `merged` without its tests having run, if two agents can hold a write lease
on the same file, or if the framework's own state cannot be rebuilt from the repository.

## Non-negotiable

1. A guarantee is a property of an artifact, never of a prompt. Anything that ordinary use
   can bypass is published as a check or a heuristic, not as a guarantee.
2. Project state lives in git under `.aegis/`. Nothing the framework needs in order to
   resume is stored outside the repository.
3. No unauthenticated switch disables enforcement. An environment variable that turns a
   hook or a gate off is the absence of enforcement, and is refused in review.
4. Every command the framework documents must exist and run. A phantom command is a
   defect, never an alias.
5. Growth is paid for by deletion. A defect class that survives its fix means the mechanism
   is wrong: simplify it, do not patch it a third time.

## Autonomy limits

Agents decide alone: see `policy.autonomy_limits` in `.aegis/generated/policy.json`.
Agents always escalate: data migrations, public contract changes, security policy,
licence or paid-service choices, and anything that cannot be undone by a revert.

## Frozen zones

Paths no agent modifies without explicit human instruction:

- `docs/spec-v0.3-original.md` — the historical v0.3 specification. Parts it gets wrong
  are recorded in ADRs; the file itself is never edited in place.

## Amendment

Change this file in its own pull request, reviewed by a human, never bundled with feature
work. If a change here also implies configuration, edit `answers.json` and run
`aegis compile` in the same pull request.

## Signature

Drafted 2026-09-17 from README, ARCHITECTURE and EVALUATION. **Confirmed by the owner, Alex
Derkach, on 2026-09-19** — in conversation, with the words «делай что нужно, разрешаю», after the
simplification recorded in ADR-5 and retro 0003; the agent recorded the confirmation here on his
behalf and did not sign for him. Amendments follow the section above.
