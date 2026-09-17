import os, sys, io
ROOT = os.environ["AEGIS_PATCH_ROOT"]
def patch(rel, old, new):
    p=f"{ROOT}/{rel}"; t=io.open(p,encoding="utf-8").read()
    if new and new in t:
        print("already",rel); return
    n=t.count(old)
    if n!=1: sys.exit(f"{rel}: expected 1 match, found {n}:\n{old[:220]!r}")
    io.open(p,"w",encoding="utf-8").write(t.replace(old,new)); print("patched",rel)
# ---- orchestrator: warm builders (D9) ----
patch("agents/aegis-orchestrator.md", '''## Parallelism
''', '''## Warm builders, fresh auditors

A builder dispatched fresh for every small task re-reads the project each time, and on a
real repository that is most of what it spends. Keep **one named builder per cluster** — the
tasks of one feature whose leases sit in the same area — and continue it for the cluster's
next task instead of spawning a new one. Brief it with the delta:

```bash
aegis packet <NEXT-ID> --delta-from <PREVIOUS-ID>
```

The rules that keep warmth an optimisation rather than a dependency:

- **Warm only inside a cluster.** A task in a different area gets a fresh builder — carrying
  another area's history imports its assumptions (rule 6).
- **A handoff per task, always.** The handoff is the state; the warm context is a cache. A
  crashed or compacted builder loses nothing a fresh one cannot rebuild from the files.
- **Respawn at about 70–80% of the context window**, after its handoff is written.
- **Lenses stay independent of the builder.** A lens may be continued across the rounds of
  one task — it keeps its own view of the diff — but never reviews a task it helped build.

Profile by context boundary (api, frontend, data), never by activity (coder, tester): the
second shape spends its tokens re-explaining the same code between agents.

## Parallelism
''')

# ---- build protocol: root cause on the second rejection (D10) ----
patch("skills/build/SKILL.md", '''Three rules govern this loop:
''', '''**The second rejection of the same finding gets a root-cause pass.** Dispatch a builder in a
clean context with the finding, the diff and one instruction: state the root cause first,
then the fix plan, then change the code. The context that wrote the patch twice keeps
reaching for the same patch.

Three rules govern this loop:
''')

# ---- spec protocol: clarification markers ----
patch("skills/spec/SKILL.md", '''- List open questions as questions. An assumption you resolved silently becomes a defect
  that only surfaces once the code exists.
''', '''- List open questions as questions. An assumption you resolved silently becomes a defect
  that only surfaces once the code exists. Inline, mark each one where it bites:
  `[NEEDS CLARIFICATION: which currency?]`. `aegis check requirements` warns while one
  remains and fails once tasks exist for the feature.
- A requirement id is declared once. Reusing `R-3` for a different statement is a failure.
''')

# ---- workflow: cause-first on round >= 2 ----
patch("workflows/aegis-task.js", '''  if (needsFix) await agent(
    `${text}\\n\\nDo exactly what that says: change the code so the finding no longer holds, ` +
    `staying inside the task's write lease. Do not record a disposition — a finding is ` +
    `resolved by fixing it and re-reviewing, not by declaring it fixed.`,
    { label: `refine:${round}`, phase: 'Refine', agentType: 'aegis-builder' },
  )
''', '''  // From the second round the same findings have survived a fix once. The builder is always a
  // fresh context here; the instruction changes so it does not reach for the same patch.
  const causeFirst = round >= 2
    ? `This finding survived a previous fix. Before changing anything, state ROOT_CAUSE (one ` +
      `paragraph), then FIX_PLAN (at most five lines), then change the code. `
    : ''
  if (needsFix) await agent(
    `${text}\\n\\n${causeFirst}Do exactly what that says: change the code so the finding no longer holds, ` +
    `staying inside the task's write lease. Do not record a disposition — a finding is ` +
    `resolved by fixing it and re-reviewing, not by declaring it fixed.`,
    { label: `refine:${round}`, phase: 'Refine', agentType: 'aegis-builder' },
  )
''')

# ---- README ----
patch("README.md", '''Diff scans for unregistered environment variables, events, flags, integrations and routes;
the testing mandate; change-kind detection.''', '''Diff scans for unregistered environment variables, events, flags, integrations and routes;
the testing mandate; change-kind detection; whether a passing test command actually ran
tests (a recognised count of zero fails, output with no count warns).''')
patch("README.md", '''aegis packet <TASK>                    the delegation contract
''', '''aegis packet <TASK> [--delta-from T]   the delegation contract; the delta for a warm builder
''')

# ---- ARCHITECTURE §9: warm builders ----
patch("docs/ARCHITECTURE.md", '''The converse matters more: **more agents does not improve the result by itself.**''', '''### Warm builders, fresh auditors

What an agent costs is mostly what it reads before it can act. A builder spawned fresh for
each small task re-reads the same area every time; one kept warm across the tasks of a
cluster reads it once. `aegis packet <ID> --delta-from <PREV>` briefs a warm builder with
what changed — requirements, acceptance, lease, verification — and one line for what did not.

Warmth never becomes memory: every task still writes its handoff, so a crashed or compacted
builder loses a cache, not state. Lenses are the opposite case. Their value is independence
from the author, so a lens never reviews work it helped build — though it may be continued
across the rounds of one task, where it keeps its own reading of the diff and reconciles its
own findings by id. The first dogfood cycle measured both shapes (EVALUATION §8).

The converse matters more: **more agents does not improve the result by itself.**''')
print("task2 doc patches applied")
