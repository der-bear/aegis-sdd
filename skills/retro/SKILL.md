---
name: retro
description: Milestone retrospective for an Aegis project — read the recorded metrics, find repeating patterns, propose protocol changes as pull requests. Use at the end of a milestone or week, not after a single task.
allowed-tools: Read, Grep, Glob, Bash, Write
---

# Retrospective

The system improves from recorded evidence, never from recollection. Everything below reads
`.aegis/runs/*/metrics.jsonl` and the lens records.

## Read the numbers first

```bash
aegis status
cat .aegis/runs/*/metrics.jsonl | python3 -m json.tool --json-lines 2>/dev/null | head -60
```

Four questions:

1. **Which findings repeat across tasks?** The same defect three times is a missing
   protocol, not three careless builders.
2. **Which lens is being ignored?** Compute acceptance rate — findings dispositioned
   `fixed` over total findings. Below roughly 30% across two retrospectives, that lens is
   noise: fix its protocol or switch it off. Keeping a lens nobody believes trains everyone
   to skim review output.
3. **Which gate step fails most, and why?** A step failing constantly is either catching a
   real systemic problem or is miscalibrated. Decide which; do not leave it ambiguous.
4. **Where did tokens go?** Packet sizes, review rounds per task, tasks needing more than
   one refinement round.

Small samples lie. Under about ten tasks, report the observation and wait rather than
changing a protocol on the strength of two data points.

## Then propose changes

Each proposal is a small pull request for a human, never a direct edit:

- A repeating finding becomes a protocol (`protocol-authoring`) or a deterministic check.
  **Prefer the check.** A rule in a prompt is advice; a rule in `aegis check` is a fact, and
  it costs no tokens.
- A noisy lens gets a narrower protocol, or is removed from the matrix.
- Protocols that always fire together get merged; protocols that never fire get retired.
- A recurring escalation means the autonomy limits are wrong — that is an `answers.json`
  change, recompiled.

## What a retrospective may not do

It may not edit `constitution.md`, `standards/`, or any skill directly. It proposes; a
human decides. A system that judges its own rules and then rewrites them drifts, and
nothing in the loop can notice because the judge moved too.

## Record it

Append one entry to `.aegis/memory/retros/<date>.md`: what the numbers showed, what was
proposed, what the human accepted. Next retrospective starts by checking whether the last
one's changes actually helped — an improvement nobody measured is a guess with paperwork.
