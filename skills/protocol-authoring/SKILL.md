---
name: protocol-authoring
description: The protocol for writing protocols. Use when adding a new Aegis skill, changing an existing one, or reviewing a proposed protocol change. Not for product code, and not for documentation — use doc-authoring for that.
---

# Writing an Aegis protocol

A protocol is a skill. Every skill is loaded metadata-first on every turn, so the cost of a
bad one is paid continuously by every agent in the project.

## When a protocol is justified

Exactly three triggers:

1. The same review finding or the same human correction has appeared **two or three times**.
2. The project entered a new domain — an integration class, a module type — with rules
   nobody has written down.
3. A retrospective decided it.

Nothing else. Before writing, read `.aegis/generated/index/skills.json`: if an existing
protocol's triggers overlap, extend it. Two skills that always fire together are one skill
with a coordination problem.

## Shape

```
skills/<slug>/SKILL.md          # + references/ for anything long
```

Frontmatter:

- `name` — the slug.
- `description` — third person, under 500 characters, and it must contain both **when to
  use this** and **when not to**. This single field decides whether the protocol ever fires;
  a body nobody loads is worth nothing.
- `metadata: {change_kinds: [route, contract]}` — optional. Lets `aegis packet` hand this
  protocol's path to a builder whose task touches those kinds.

Body, under the `skill_body` token budget:

1. What this is for, in one paragraph.
2. The procedure, as steps.
3. One or two canonical examples.
4. Links into `references/` for tables, long examples and schemas.

**One concern per protocol.** Two independent procedures are two skills, no matter how
related they feel.

## Registration

Open a pull request containing **only** the protocol files. A human approves it.
`aegis check budget` must be green: the metadata total is a shared budget, so every new
protocol spends from the same pool as every existing one.

On profile L, also add two or three trigger scenarios to `.aegis/evals/skills/<slug>.json`
— a prompt, whether the skill should fire, the actions that prove it did — so that adding
the twentieth protocol does not quietly stop the third from triggering. **No runner ships
for these yet;** they are a recorded expectation, run by hand or by your own CI. Treating
them as automated coverage they are not is worse than not having them.

## Lifecycle

`proposed → active → deprecated`. A deprecated protocol keeps a `superseded_by` and is not
deleted mid-version; agents mid-task may still be holding it.

Merge two protocols when the metrics show them firing together in more than half of tasks.
Retire one that has not fired at all across a milestone: it is paying metadata rent for
nothing.

## Review checklist

- [ ] Triggers **and** anti-triggers in the description
- [ ] No overlap with an existing protocol
- [ ] Body inside the token budget; long material moved to `references/`
- [ ] Evals added and passing
- [ ] `aegis check budget` green
- [ ] Nothing here restates something a deterministic check already enforces
