# ADR-1: The candidate commit should become the unit of workflow state

Status: accepted-for-v2 · sequencing decided by a second opinion (below)

## Context

A design review (GPT-5.6-sol, extreme effort, instructed to judge the paradigm rather than
list bugs) examined the whole implementation. Its verdict, condensed:

- **The thesis is right** — deterministic gates, artifacts in git, thin agents — but the
  implementation over-extends it: the scripts try to be the orchestration state machine,
  onboarding expert, documentation governor and risk classifier at once.
- **The guarantee-bearing kernel is ~800–1,500 lines** of the current ~5,500. The rest is
  onboarding and governance policy that should be optional modules, not the trust kernel.
- **The one change that buys the most:** make the immutable candidate commit — not
  `.aegis/runs/<TASK>/` — the primary unit of workflow state. Reviews and gate results
  become attestations over `(commit, task-contract-hash, reviewer, verdict)`. Status is
  never stored: *built* = a candidate exists, *reviewed* = attestations exist for it,
  *merged* = it is reachable from the target branch. A fix produces a new commit, and old
  attestations become irrelevant automatically.

## Why this is right (own analysis, not deference)

The strongest evidence is this project's own bug history. The custom diff digest, the
mutable status field, the gate receipt and the review-staleness logic each produced a
BLOCKING defect during development — including a gate that invalidated its own receipt by
writing the status it certified. Every one of those mechanisms is a hand-built substitute
for what a commit SHA provides for free: immutable, content-addressed identity. The bugs
were not implementation slips; they were the cost of reviewing a moving working tree.

Also right, and adopted immediately (see below): models should never echo machine-known
facts. The runner knows the digest, the reviewer identity and the changed files; asking the
model to repeat them created the replay and empty-echo failure modes the audits found.

## Where the review is wrong or overreaches

- **"The workflow should call the CLI directly instead of via low-effort agents."** The
  Workflow sandbox has no filesystem or shell access by design; dispatching an agent is the
  only mechanism it has. The criticism stands as a cost observation, not as an available
  alternative. The costs are minimised (`effort: low`), not eliminated.
- **SQLite under `.git/aegis/` for leases.** At the stated ceiling — three builders, one
  orchestrator — transactional lease acquisition buys little, and moving state out of
  version control costs reviewability: a lease dispute stops being a `git log` question.
  File-based manifests with `O_EXCL` locking stay until the ceiling itself changes.
- **"No question banks in the kernel."** Half right. The interview-as-data design is what
  lets a new project type be one JSON file with no engine changes — a requirement, not an
  accident. The correction is placement, not deletion: it belongs in an onboarding module,
  outside the trust kernel, and nothing in the kernel may depend on it.
- **Finding identity from prose hashes.** The review is right that models paraphrase. The
  fix it proposes — pass prior finding IDs back explicitly and have the reviewer mark each
  resolved/unresolved — is better than hashing and cheaper than it sounds. Adopted for v2.

## Decision

v2 reorganises around the candidate commit:

1. A builder finishes by producing an immutable candidate commit.
2. Reviews and gate results are attestations over that commit, stored in git notes.
3. Status is derived — from the existence of a candidate, of attestations, and from
   ancestry — never written.
4. The kernel shrinks to: task contract, capability acquisition, candidate identity,
   attestation validation, command execution. Onboarding (detection, interview, scaffold),
   documentation governance (doc profiles, diagram digests) and registries become optional
   modules with their own budgets.
5. Provenance is always attached by the caller, never echoed by a model. *(Implemented
   already in v1: `aegis lens record --reviewer --digest`.)*

## Second opinion (Fable 5, independent)

Asked to agree or disagree on the merits. Where it landed:

- **Candidate commits: right, and a completion of v1's philosophy rather than a rescue.**
  The custom digest already invalidates a review the moment the tree moves — the system
  de facto demands a frozen tree per round; a commit gives that tree a name git understands.
  Real losses to plan for: unborn-branch and git-absent degradation, process states
  (`refine`, `abandoned`, the parallel ceiling) that are not derivable from commits, and
  git notes not syncing by default — which silently breaks "recoverable from a clone".
- **SQLite: refused, again.** The repository already declined a transactional queue at this
  scale, and that reasoning holds. One idea worth extracting: sandbox-level enforcement is
  the genuine fix for the acknowledged Bash-bypass hole, where hooks cannot be.
- **Finding reconciliation: right, with an anchoring cost.** Feeding prior findings to a
  fresh reviewer undermines the unbiased-auditor property. Mitigation adopted: two ordered
  phases — fresh scan first, reconciliation second. It also noted the current prose-hash
  identity makes the cross-engine "same defect collapses to one finding" claim near-fiction,
  since two models never word a claim identically; the README claim was softened.
- **Sequencing verdict: dogfood before refactor.** Six rounds of adversarial self-audit and
  no commit history of real use — the scarcest evidence is empirical, not architectural.
  Half of the safe subset already exists (`--digest` runner attachment, derived receipt
  validation). A week on a real project decides which piece of v2 gets built first; its bet
  is finding reconciliation, because id churn bites in every multi-round review.

## Consequences

Deleted outright in v2: the custom diff digest, the mutable status machine and its
transition table, gate receipts, review-staleness logic, most handoff fields, `ACTIVE`
focus marker reconciliation. Roughly 4,000 of the current 5,500 lines either disappear or
move behind an optional-module boundary.

Costs accepted: a commit per review round (cheap, and `commit-tree` avoids branch noise);
work-in-progress becomes visible through candidates rather than the working tree, which
changes how a human inspects a half-done task.

Not migrating v1 in place: v1 is tested (93 tests), self-hosting, and in use. v2 is a
rewrite of `flow.py`'s core around commits, done as its own project with v1's test suite
as the acceptance bar.
