"""ADR-3: lenses, roles and engines are data. Apply after TASK-UNBLOCK-01 is merged."""
import sys, io, json, os, shutil
ROOT = os.environ["AEGIS_PATCH_ROOT"]
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lenses_src")
def rd(rel): return io.open(f"{ROOT}/{rel}",encoding="utf-8").read()
def wr(rel,t): io.open(f"{ROOT}/{rel}","w",encoding="utf-8").write(t)
def patch(rel, old, new, count=1):
    p=f"{ROOT}/{rel}"; t=io.open(p,encoding="utf-8").read()
    if new and new in t:
        print("already",rel); return
    n=t.count(old)
    if n!=count: sys.exit(f"{rel}: expected {count}, found {n}:\n{old[:220]!r}")
    io.open(p,"w",encoding="utf-8").write(t.replace(old,new)); print("patched",rel)
CFG="scripts/aegis/aegis_cli/config.py"; FLOW="scripts/aegis/aegis_cli/flow.py"; MAIN="scripts/aegis/aegis_cli/__main__.py"

# ------------------------------------------------------------ files: lenses and the two auditor profiles
os.makedirs(f"{ROOT}/lenses", exist_ok=True)
for name in ("correctness", "security", "design", "accessibility", "data-integrity"):
    shutil.copyfile(f"{SRC}/{name}.md", f"{ROOT}/lenses/{name}.md"); print("lens", name)
for name in ("lens-auditor", "lens-runner"):
    shutil.copyfile(f"{SRC}/{name}.md", f"{ROOT}/agents/{name}.md"); print("profile", name)
for name in ("lens-correctness", "lens-security", "lens-design"):
    p=f"{ROOT}/agents/{name}.md"
    if os.path.exists(p):
        # The focus text moved verbatim into lenses/<name>.md; the profile carried only tools.
        os.remove(p); print("removed profile", name)

# ------------------------------------------------------------ config: the matrix is derived from lens files
t=rd(CFG)
start=t.index("LENS_MATRIX: dict[str, dict[str, list[str]]] = {")
end=t.index("RISK_TIERS: dict[str, dict[str, Any]] = {")
block=t[start:end]
comment_start=t.rfind("\n\n", 0, start)
t=t[:start]+'''STRICTNESS_ORDER = {"minimal": 0, "standard": 1, "strict": 2}


def load_lenses(ctx: Ctx) -> dict[str, dict[str, Any]]:
    """Lens files: the framework's `lenses/`, then a project's `.aegis/lenses/`, which wins.

    A lens is data — a focus and the triggers that select it — not a profile and not code
    (ADR-3). The profile only decides the tool set: `executes: true` needs `lens-runner`.
    """
    from .checks import parse_frontmatter
    lenses: dict[str, dict[str, Any]] = {}
    for base in asset_dirs(ctx, "lenses"):
        for filename in sorted(os.listdir(base)):
            if not filename.endswith(".md"):
                continue
            path = os.path.join(base, filename)
            front, body = parse_frontmatter(read_text(path))
            name = front.get("name") or filename[:-3]
            lenses[name] = {**front, "name": name, "body": body.strip(), "path": path}
    return lenses


def derive_lens_matrix(ctx: Ctx, strictness: str, project_type: str | None
                       ) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, str]]:
    """(kind -> lenses, lens -> path globs, lens -> profile) for this strictness and project.

    Each lens says from which strictness it is always on, and from which strictness each
    change kind or path selects it. The three tables that used to be a constant here are
    reproduced exactly by the shipped lens files — and a project adds a lens with a file.
    """
    level = STRICTNESS_ORDER.get(strictness, 1)
    matrix: dict[str, list[str]] = {"always": []}
    paths: dict[str, list[str]] = {}
    profiles: dict[str, str] = {}
    lenses = load_lenses(ctx)
    for name in sorted(lenses, key=lambda n: (int(str(lenses[n].get("order") or 50)), n)):
        lens = lenses[name]
        types = lens.get("project_types") or []
        if types and project_type not in types:
            continue
        profiles[name] = "lens-runner" if str(lens.get("executes", "")).lower() == "true" else "lens-auditor"
        always = str(lens.get("always_from") or "never")
        if always in STRICTNESS_ORDER and STRICTNESS_ORDER[always] <= level:
            matrix["always"].append(name)
        kinds = lens.get("kinds") if isinstance(lens.get("kinds"), dict) else {}
        for kind, from_level in kinds.items():
            if from_level in STRICTNESS_ORDER and STRICTNESS_ORDER[from_level] <= level:
                matrix.setdefault(kind, []).append(name)
        globs = lens.get("paths") if isinstance(lens.get("paths"), list) else []
        if globs and STRICTNESS_ORDER.get(str(lens.get("paths_from") or "minimal"), 0) <= level:
            paths[name] = list(globs)
    return matrix, paths, profiles


'''+t[end:]
old_compile='''    # Derived, not asked: the lens matrix and risk tiers follow from strictness.
    policy["lens_matrix"] = {k: list(v) for k, v in LENS_MATRIX[str(policy["lens_strictness"])].items()}
'''
assert t.count(old_compile)==1
t=t.replace(old_compile,'''    # Derived, not asked: the lens matrix follows from the lens files, the strictness and the
    # project type; risk tiers follow from strictness.
    matrix, lens_paths, lens_profiles = derive_lens_matrix(ctx, str(policy["lens_strictness"]), env.get("type"))
    policy["lens_matrix"] = matrix
    policy["lens_paths"] = lens_paths
    policy["lens_profiles"] = lens_profiles
''')
import re as _re
m=_re.search(r"^COMPILER_VERSION = (\d+).*$", t, _re.M)
t=t.replace(m.group(0), f"COMPILER_VERSION = {int(m.group(1))+1}  # {int(m.group(1))+1}: lens matrix derived from lens files (ADR-3)")
old_targets='''        "default_package": "package used when a change matches no other",
    },'''
assert t.count(old_targets)==1
t=t.replace(old_targets,'''        "default_package": "package used when a change matches no other",
        "external_reviewer": "a command for a second reviewing engine, or empty (ADR-3)",
    },''')
wr(CFG,t); print("patched",CFG)
t=rd(CFG)
imp_start=t.index("from .core import (")
imp_end=t.index(")", imp_start)
names=[n.strip() for n in t[imp_start+len("from .core import ("):imp_end].replace("\n"," ").split(",") if n.strip()]
for need in ("asset_dirs","read_text","Ctx"):
    if need not in names: names.append(need)
t=t[:imp_start]+"from .core import (\n    "+",\n    ".join(sorted(set(names)))+",\n"+t[imp_end:]
wr(CFG,t); print("patched",CFG,"imports")

# ------------------------------------------------------------ interview: the second engine is an answer
p=f"{ROOT}/interview/core.json"; bank=json.load(open(p))
if not any(q["id"]=="q.core.second-engine" for q in bank["questions"]):
    bank["questions"].append({
        "id": "q.core.second-engine",
        "ask": "Is a second AI engine available for independent review? Give the command that takes a prompt as its last argument and prints the reply (for example `gemini -p`, `codex exec --sandbox read-only`, `claude -p --model <other>`), or leave it empty.",
        "kind": "free", "default": "", "writes": "capabilities.external_reviewer",
        "autonomy": "auto-default", "severity": "optional",
        "rationale": "A reviewer on a different engine strengthens 'the builder is never the final reviewer'. It is never required: a fresh context that did not build the change already satisfies the gate."})
    json.dump(bank,open(p,"w"),indent=2,ensure_ascii=False); open(p,"a").write("\n"); print("bank core: q.core.second-engine")

# ------------------------------------------------------------ flow: plan by paths too; profiles; prompt for any engine
patch(FLOW, '''    tier = _risk_tier(policy, kinds)
    return {
        "task": task_id,
        # The reviewer quotes this back in its report; that is what proves what it read.''', '''    # Paths select lenses as well as change kinds: an accessibility lens follows the files a
    # web project's interface lives in, whatever the task declared.
    for lens, globs in sorted((policy.get("lens_paths") or {}).items()):
        hits = [rel for rel in scope if matches_any(rel, globs)]
        if hits:
            if lens not in selected:
                selected.append(lens)
            reasons.setdefault(lens, []).append(f"paths: {hits[0]}" + (f" +{len(hits) - 1}" if len(hits) > 1 else ""))

    tier = _risk_tier(policy, kinds)
    profiles = policy.get("lens_profiles") or {}
    return {
        "task": task_id,
        # The reviewer quotes this back in its report; that is what proves what it read.''')
patch(FLOW, '''        "lenses": selected,
        "why": {lens: sorted(set(why)) for lens, why in reasons.items()},''', '''        "lenses": selected,
        # Which tool profile each lens needs; the focus comes from `aegis lens prompt`.
        "profiles": {lens: profiles.get(lens, "lens-auditor") for lens in selected},
        "external_reviewer": checks.capabilities(ctx).get("external_reviewer") or None,
        "why": {lens: sorted(set(why)) for lens, why in reasons.items()},''')
patch(FLOW, '''def task_diff(ctx: Ctx, task_id: str) -> str:''', '''def lens_prompt(ctx: Ctx, task_id: str, lens: str, with_contract: bool = False,
                with_diff: bool = True, closing: bool = False) -> str:
    """Everything one lens needs, for any engine: its focus, its own prior findings with the
    two-phase reconciliation, the packet and the diff — and the review contract itself when
    the engine does not preload it. Deterministic, so every runner briefs a lens the same way.
    """
    from .config import load_lenses
    lenses = load_lenses(ctx)
    if lens not in lenses:
        raise AegisError(f"no lens {lens!r}; known: {', '.join(sorted(lenses)) or 'none'}. "
                         "A lens is a file in lenses/ or .aegis/lenses/.")
    parts = [f"# Review task {task_id} as the {lens} lens" + (" — mode `closing`" if closing else " — mode `task`")]
    if with_contract:
        contract = ctx.path("protocols", "review-lens.md")
        if not os.path.exists(contract):
            contract = next((p for p in checks.skill_files(ctx) if p.endswith(os.path.join("review-lens", "SKILL.md"))), "")
        if contract:
            parts.append(checks.parse_frontmatter(read_text(contract))[1].strip())
    parts.append("## Your focus\\n\\n" + lenses[lens]["body"])
    record_path = os.path.join(run_dir(ctx, task_id), "reviews", f"{lens}.json")
    prior = read_json(record_path, default={}).get("findings", []) if os.path.exists(record_path) else []
    if prior:
        listed = "\\n".join(f"- {f['id']} [{f.get('disposition', 'open')}] {f['message'][:160]}" for f in prior)
        parts.append(
            "## Two phases, in this order\\n\\n"
            "PHASE 1 — review the diff fresh, as if for the first time, and write `findings`.\\n"
            "PHASE 2 — only then reconcile this lens's previous findings in a top-level `reconciled` "
            "list, one entry per open id: `{\\"id\\": \\"<id>\\", \\"followup\\": \\"resolved\\" or \\"unresolved\\", "
            "\\"evidence\\": \\"<one line>\\"}`. Never copy a prior id into `findings`. Reading this list "
            "first would anchor the fresh scan.\\n\\n" + listed)
    if with_diff:
        packet, _meta = build_packet(ctx, task_id)
        parts.append("## Task packet\\n\\n" + packet)
        parts.append("## Diff under review\\n\\n" + task_diff(ctx, task_id))
    parts.append("## Output\\n\\nReturn only the JSON object the review contract specifies — about "
                 "1,000 tokens at most. Do not include `lens`, `reviewer` or `diff_digest`: the recorder "
                 "attaches them.")
    return "\\n\\n".join(parts)


def task_diff(ctx: Ctx, task_id: str) -> str:''')
patch(MAIN, '''    lr = lsub.add_parser("record", help="read a lens report as JSON on stdin")''', '''    lpr = lsub.add_parser("prompt", help="everything one lens needs, for any engine")
    lpr.add_argument("id")
    lpr.add_argument("lens")
    lpr.add_argument("--with-contract", action="store_true", help="include the review contract, for engines that do not preload it")
    lpr.add_argument("--no-diff", action="store_true", help="omit the packet and diff, when the caller already has them")
    lpr.add_argument("--closing", action="store_true")
    lr = lsub.add_parser("record", help="read a lens report as JSON on stdin")''')
patch(MAIN, '''        if args.lens_command == "record":''', '''        if args.lens_command == "prompt":
            emit(flow.lens_prompt(ctx, args.id, args.lens, args.with_contract, not args.no_diff, args.closing))
            return 0
        if args.lens_command == "record":''')

# ------------------------------------------------------------ workflow: profile per lens, brief from `aegis lens prompt`
W="workflows/aegis-task.js"
t=rd(W)
old_first='''  (lens) => agent(
    `Review task ${task} as the ${lens} lens.\\n\\nHere is the task packet and the diff:\\n\\n` +
    `${diff}\\n\\n` +
    `Return ONLY the JSON report your contract specifies. Do not include reviewer or ` +
    `digest fields — the recorder attaches them. Do not try to run any command.`,
    { label: `lens:${lens}`, phase: 'Review', agentType: `lens-${lens}` },
  ).then((report) => ({ lens, report })),'''
assert t.count(old_first)==1, "first lens dispatch anchor"
t=t.replace(old_first,'''  async (lens) => agent(
    `${await brief(lens)}\\n\\n## Task packet and diff\\n\\n${diff}\\n\\n` + runRule(lens),
    { label: `lens:${lens}`, phase: 'Review', agentType: profileOf(lens) },
  ).then((report) => ({ lens, report })),''')
old_plan_log='''log(`lenses: ${plan.lenses.join(', ')} (risk tier ${plan.risk_tier || '?'})`)
'''
assert t.count(old_plan_log)==1
t=t.replace(old_plan_log, old_plan_log+'''
// A lens is data (ADR-3): its focus and its own prior findings come from `aegis lens prompt`,
// and its tool profile from the plan. The workflow names no lens and no vendor.
const brief = (lens) => agent(
  sh(`${AEGIS} lens prompt ${task} ${lens} --no-diff`),
  { label: `brief:${lens}`, phase: 'Review', effort: 'low' },
)
const profileOf = (lens) => (plan.profiles && plan.profiles[lens]) || 'lens-auditor'
// A runner lens executes the test suite; neither kind runs `aegis` or records itself.
const runRule = (lens) => profileOf(lens) === 'lens-runner'
  ? `Run the project's tests as your focus says. Do not run any aegis command — the recorder records your report.`
  : `Do not try to run any command.`
''')
rs=t.index("  await parallel(roundLenses.map((lens) => async () => {")
re_end=t.index("    const report = await agent(", rs)
re_block_end=t.index("      { label: `re:${lens}:${round}`, phase: 'Refine', agentType: `lens-${lens}` },\n    )\n", rs)
new_re='''  await parallel(roundLenses.map((lens) => async () => {
    // The brief carries this lens's own prior findings and the two-phase reconciliation;
    // a lens new to this round gets none and reviews fresh.
    const report = await agent(
      `${await brief(lens)}\\n\\n## Revised task packet and diff\\n\\n${revised}\\n\\n` + runRule(lens),
      { label: `re:${lens}:${round}`, phase: 'Refine', agentType: profileOf(lens) },
    )
'''
t=t[:rs]+new_re+t[re_block_end+len("      { label: `re:${lens}:${round}`, phase: 'Refine', agentType: `lens-${lens}` },\n    )\n"):]
wr(W,t); print("patched",W)

# ------------------------------------------------------------ engines: external-lens.sh for any CLI; codex-lens.sh a wrapper
E="scripts/aegis/external-lens.sh"
wr(E, '''#!/usr/bin/env bash
# Run a review lens on any AI engine and record it like any other lens.
#
#   scripts/aegis/external-lens.sh <TASK-ID> <lens> <engine-label> [--stdin] -- <command> [args...]
#
#   scripts/aegis/external-lens.sh TASK-042-01 security gemini:2.5-pro -- gemini -p
#   scripts/aegis/external-lens.sh TASK-042-01 security claude:opus -- claude -p --model opus
#   scripts/aegis/external-lens.sh TASK-042-01 security ollama:qwen3 --stdin -- ollama run qwen3
#
# The engine is whatever the project has; nothing in Aegis requires a particular one. The
# command receives one self-contained prompt from `aegis lens prompt --with-contract` — the
# review contract, the lens focus, this lens's own prior findings, the packet and the diff —
# as its last argument, or on stdin with --stdin, and must print a reply containing one JSON
# object. Provenance is attached here, never echoed by the model: --lens, --reviewer, --digest.
set -euo pipefail

task="${1:?usage: external-lens.sh <TASK-ID> <lens> <engine-label> [--stdin] -- <command> [args...]}"
lens="${2:?lens name}"
label="${3:?engine label, for example gemini:2.5-pro}"
shift 3
mode="argument"
if [ "${1:-}" = "--stdin" ]; then mode="stdin"; shift; fi
[ "${1:-}" = "--" ] && shift
[ "$#" -gt 0 ] || { echo "give the engine command after --" >&2; exit 1; }

plugin="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
root="$plugin"
[ -d "$PWD/.aegis" ] && root="$PWD"
aegis="$(command -v aegis || echo "$plugin/scripts/aegis/aegis")"
[ -f "$root/.aegis/runs/$task/manifest.json" ] || { echo "no task $task" >&2; exit 1; }

# The digest is taken before the engine runs: an edit during the review makes the record fail
# rather than bind a verdict to code the reviewer never saw.
digest="$("$aegis" --root "$root" lens plan "$task" | python3 -c 'import json,sys;print(json.load(sys.stdin)["diff_digest"])')"
prompt="$("$aegis" --root "$root" lens prompt "$task" "$lens" --with-contract)"

if [ "$mode" = "stdin" ]; then
  reply="$(printf '%s' "$prompt" | "$@" 2>/dev/null)"
else
  reply="$("$@" "$prompt" 2>/dev/null)"
fi
report="$(printf '%s' "$reply" | python3 -c 'import re,sys; t=sys.stdin.read(); m=re.search(r"\\{[\\s\\S]*\\}", t); print(m.group(0) if m else "")')"
[ -n "$report" ] || { echo "$label returned no JSON report" >&2; exit 1; }
printf '%s' "$report" | "$aegis" --root "$root" lens record "$task" --lens "$lens" --reviewer "$label" --digest "$digest"
''')
os.chmod(f"{ROOT}/{E}", 0o755); print("wrote",E)
C="scripts/aegis/codex-lens.sh"
wr(C, '''#!/usr/bin/env bash
# Codex defaults for external-lens.sh, kept so existing commands still work. Any other engine —
# or none — goes through external-lens.sh directly; nothing in Aegis requires Codex.
#
#   scripts/aegis/codex-lens.sh <TASK-ID> <lens> [model]
set -euo pipefail
task="${1:?usage: codex-lens.sh <TASK-ID> <lens> [model]}"
lens="${2:?lens name}"
model="${3:-gpt-5.6-sol}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$here/external-lens.sh" "$task" "$lens" "codex:$model" -- \\
  codex exec --sandbox read-only -m "$model" -c model_reasoning_effort=xhigh
''')
print("wrote",C)
print("lenses patch applied")
