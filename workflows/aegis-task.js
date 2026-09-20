export const meta = {
  name: 'aegis-task',
  description: 'Run the Aegis loop for one task: packet, build, planned lenses in parallel, gate',
  whenToUse: 'Implementing a task that already has a manifest, when you want the loop driven deterministically rather than by the orchestrator remembering it',
  phases: [
    { title: 'Build', detail: 'one builder in an isolated worktree, from the generated packet' },
    { title: 'Review', detail: 'exactly the lenses `aegis lens plan` says to run, in parallel' },
    { title: 'Refine', detail: 'fix blocking findings and re-review, up to the round limit' },
    { title: 'Documentation', detail: 'registry drafts and diagrams, applied by the single writer' },
    { title: 'Gate', detail: 'deterministic checks and the affected packages\' commands' },
  ],
}

// The plan comes from the CLI, not from this script and not from a model. That is the whole
// point: the same loop runs identically whether an orchestrator agent drives it, this
// workflow does, or a human types the commands.
const task = (args && (args.task || args)) || null
if (!task || typeof task !== 'string') {
  throw new Error('pass the task id as args, e.g. Workflow({name: "aegis-task", args: "TASK-042-01"})')
}

const AEGIS = 'aegis'
const sh = (cmd) => `Run exactly this and return only its output, no commentary:\n\n    ${cmd}\n`

phase('Build')
log(`packet for ${task}`)

// One agent reads the packet and implements. `isolation: worktree` comes from the builder's
// own definition, so parallel runs of this workflow cannot collide on the working tree.
// The packet is generated here, in the main checkout. The builder runs with
// `isolation: worktree`, where a manifest created moments ago and not yet committed simply
// does not exist — asking it to generate its own packet failed before implementation began.
const packet = await agent(
  sh(`${AEGIS} task claim ${task} && ${AEGIS} packet ${task}`),
  { label: 'packet', phase: 'Build', effort: 'low' },
)

// The builder runs with `isolation: worktree`. An uncommitted manifest and focus marker do
// not exist there, and the write-lease hook would be inert without ever saying so. Commit
// the run directory first: it is evidence, not scratch, and the hook then works in the
// worktree exactly as it does in the main checkout.
await agent(
  sh(`git add -f .aegis/runs/${task} && ` +
     `git commit -q -m "chore(${task}): task manifest" -- .aegis/runs/${task} || true`),
  { label: 'commit-manifest', phase: 'Build', effort: 'low' },
)

const built = await agent(
  `${packet}\n\n` +
  `Then carry out that packet exactly. Write \`.aegis/runs/${task}/handoff.json\` before you ` +
  `finish, including "agent": "aegis-builder". Return at most 300 words.`,
  { label: `build:${task}`, phase: 'Build', agentType: 'aegis-builder' },
)
log(built ? 'builder returned a handoff' : 'builder produced nothing — check the packet')

phase('Review')

// The diff is fetched once, by something that can run commands, and handed to each lens.
// Telling a lens to "read the diff" was an instruction two of the three could not follow.
// `aegis diff` covers exactly the files the digest covers; rebuilding it here in shell handed
// lenses pre-adoption files their verdict was never bound to.
const diffFor = (label, ph) => agent(
  sh(`${AEGIS} packet ${task} 2>/dev/null; echo '--- DIFF ---'; ${AEGIS} diff ${task}`),
  { label, phase: ph, effort: 'low' },
)
const diff = await diffFor('diff', 'Review')

// `aegis lens plan` unions the task's declared change kinds with kinds detected from the
// actual diff, so the fan-out is decided by the code, not by how the task was described.
const planText = await agent(
  sh(`${AEGIS} lens plan ${task}`),
  { label: 'plan', phase: 'Review', effort: 'low' },
)

const plan = (() => {
  const match = String(planText || '').match(/\{[\s\S]*\}/)
  return match ? JSON.parse(match[0]) : { lenses: ['correctness'] }
})()
log(`lenses: ${plan.lenses.join(', ')} (risk tier ${plan.risk_tier || '?'})`)

// Each lens is an independent auditor in a clean context. Parallel, because they are
// genuinely independent — and a barrier here is correct: the gate needs all of them.
//
// The lens returns its report; a separate step records it. Asking the lens to record itself
// looked tidier and was broken: the security and design lenses have no Bash at all, by
// design, so any task needing one reached the gate with no report at all.
await pipeline(
  plan.lenses,
  (lens) => agent(
    `Review task ${task} as the ${lens} lens.\n\nHere is the task packet and the diff:\n\n` +
    `${diff}\n\n` +
    `Return ONLY the JSON report your contract specifies. Do not include reviewer or ` +
    `digest fields — the recorder attaches them. Do not try to run any command.`,
    { label: `lens:${lens}`, phase: 'Review', agentType: `lens-${lens}` },
  ).then((report) => ({ lens, report })),
  ({ lens, report }) => {
    const match = String(report || '').match(/\{[\s\S]*\}/)
    if (!match) {
      log(`lens ${lens} returned no JSON report`)
      return null
    }
    return agent(
      `Record this lens report verbatim. Do not edit it, do not summarise it:\n\n` +
      `    cat <<'AEGIS_REPORT' | ${AEGIS} lens record ${task} --lens ${lens} --reviewer lens-${lens} --digest ${plan.diff_digest}\n${match[0]}\nAEGIS_REPORT\n`,
      { label: `record:${lens}`, phase: 'Review', effort: 'low' },
    )
  },
)

phase('Refine')

// Blocking findings are fixed and re-reviewed, up to the profile's round limit. Going
// straight to the gate produced one guaranteed failure and stopped — the loop existed in
// the documentation and not in the shipped workflow.
// One budget: `policy.refinement_rounds`, published by `aegis lens plan` as `refinement_rounds`.
// Reading the risk tier's own round count here gave tiers B and C zero iterations while the
// gate still allowed three — two budgets, and this loop never ran for most tasks.
const MAX_ROUNDS = Number(
  (await agent(sh(`${AEGIS} lens plan ${task}`), { label: 'rounds', phase: 'Refine', effort: 'low' }))
    .match(/"refinement_rounds":\s*(\d+)/)?.[1] || 3,
) - 1  // the first review already consumed round 1
for (let round = 1; round <= MAX_ROUNDS; round++) {
  const state = await agent(sh(`${AEGIS} next`), { label: `state:${round}`, phase: 'Refine', effort: 'low' })
  const text = String(state || '')
  if (!/^next: (fix|re-run lens)/m.test(text)) break
  log(`round ${round}: ${text.split('\n')[0]}`)
  // Only a finding needs the builder. `re-run lens` — the code moved, or the risk tier needs
  // another round — goes straight to re-review; dispatching a builder for it spent a run
  // and invited an edit nobody asked for.
  const needsFix = /^next: fix/m.test(text)
  if (needsFix) await agent(
    `${text}\n\nDo exactly what that says: change the code so the finding no longer holds, ` +
    `staying inside the task's write lease. Do not record a disposition — a finding is ` +
    `resolved by fixing it and re-reviewing, not by declaring it fixed.`,
    { label: `refine:${round}`, phase: 'Refine', agentType: 'aegis-builder' },
  )
  const revised = await diffFor(`diff:${round}`, 'Refine')
  // Re-read the whole plan: a fix that adds an authenticated route now needs the security
  // lens, and re-running only the original set left the gate demanding a review nobody ran.
  const replan = JSON.parse(
    (await agent(sh(`${AEGIS} lens plan ${task}`), { label: `replan:${round}`, phase: 'Refine', effort: 'low' }))
      .match(/\{[\s\S]*\}/)?.[0] || '{}',
  )
  const digest = replan.diff_digest
  // Only the lenses the moved files invalidated (R-9); a fresh record is not re-run.
  const roundLenses = replan.run || replan.lenses || plan.lenses
  await parallel(roundLenses.map((lens) => async () => {
    // Each lens is handed the prior findings *it* raised, from its own record. One shared
    // list built from every record told each lens to reconcile ids the recorder then
    // refused as "never raised", and the refine loop could not converge. (The old one-liner
    // also carried a raw newline inside a Python string, so the list was always empty.)
    const prior = await agent(
      sh(`python3 -c "import json,os;p='.aegis/runs/${task}/reviews/${lens}.json';d=json.load(open(p)) if os.path.exists(p) else {};print(chr(10).join(x['id']+' ['+str(x.get('disposition','open'))+'] '+x['message'][:100] for x in d.get('findings',[])))"`),
      { label: `prior:${lens}:${round}`, phase: 'Refine', effort: 'low' },
    )
    const priorText = String(prior || '').trim()
    const reconcile = priorText
      ? `Work in two phases, in this order. PHASE 1 — review the diff fresh, as if for the ` +
        `first time, and write your "findings". PHASE 2 — only after that, reconcile against ` +
        `the previous findings below in a separate top-level "reconciled" list, one entry per ` +
        `prior id: {"id": "<id>", "followup": "resolved" or "unresolved", "evidence": "<one line>"}. ` +
        `Every open prior finding must appear there; never put a prior id inside "findings".\n\n` +
        `Previous findings from this lens, by id:\n${priorText}\n\n` +
        `The order matters: reading the prior list first would anchor your fresh scan.\n`
      : `This lens has no prior findings on this task; review the diff fresh and omit "reconciled".\n`
    const report = await agent(
      `Re-review task ${task} as the ${lens} lens after the fix.\n\n` +
      `Here is the revised packet and diff:\n\n${revised}\n\n` +
      reconcile +
      `Return ONLY the JSON report; the recorder attaches provenance. Do not run any command.`,
      { label: `re:${lens}:${round}`, phase: 'Refine', agentType: `lens-${lens}` },
    )
    const match = String(report || '').match(/\{[\s\S]*\}/)
    if (!match) {
      log(`lens ${lens} returned no JSON report in round ${round}`)
      return null
    }
    const recorded = await agent(
      `cat <<'AEGIS_REPORT' | ${AEGIS} lens record ${task} --lens ${lens} --reviewer lens-${lens} --digest ${digest}\n${match[0]}\nAEGIS_REPORT\n`,
      { label: `rerecord:${lens}:${round}`, phase: 'Refine', effort: 'low' },
    )
    // A rejected record is a gate failure waiting to happen; say so now, not at the gate.
    if (/rejected|incomplete|never raised|does not reconcile/i.test(String(recorded || ''))) {
      log(`lens ${lens} round ${round} was NOT recorded: ${String(recorded).split('\n')[0]}`)
    }
    return recorded
  }))
}

phase('Documentation')

// Dispatch the doc-manager only when there is documentation work. An agent context per
// task for a role that usually has nothing to apply was the workflow's largest fixed cost.
const docWork = await agent(
  sh(`python3 -c "import json;d=json.load(open('.aegis/runs/${task}/handoff.json'));` +
     `print(len(d.get('registry_drafts') or []))" 2>/dev/null || echo 0; ` +
     `${AEGIS} check docs --task ${task} 2>&1 | grep -c FAIL || true`),
  { label: 'doc-work?', phase: 'Documentation', effort: 'low' },
)
const hasDocWork = /[1-9]/.test(String(docWork || ''))
if (hasDocWork) {
  await agent(
    `Apply the documentation obligations for task ${task}, following the doc-sync protocol.\n` +
    `Read .aegis/runs/${task}/handoff.json and the diff. Finish with ` +
    `\`${AEGIS} check registry\` and \`${AEGIS} check docs --task ${task}\` clean.`,
    { label: 'doc-sync', phase: 'Documentation', agentType: 'aegis-doc-manager' },
  )
} else {
  log('no registry drafts and no stale docs — doc-manager not dispatched')
}

phase('Gate')

// Deterministic. No agent judgement participates in the decision to pass.
const verdict = await agent(
  sh(`${AEGIS} gate --stage task --task ${task}; ${AEGIS} next`),
  { label: 'gate', phase: 'Gate', effort: 'low' },
)

return {
  task,
  lenses: plan.lenses,
  riskTier: plan.risk_tier,
  gate: String(verdict || '').includes('gate passed') ? 'passed' : 'failed',
  next: String(verdict || '').split('next:').pop()?.trim().split('\n')[0] || null,
  note: 'Blocking findings and their dispositions live in .aegis/runs/' + task + '/reviews/.',
}
