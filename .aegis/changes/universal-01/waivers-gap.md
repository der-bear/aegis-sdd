The gate's hint for a blocking finding set aside is "add an entry to .aegis/waivers.json with
owner, reason and expiry, scoped to <finding id>, and cite its id as the reason". The waiver
schema's `check` enum is registry, env, requirements, docs, budget, testing, events, flags,
integrations, routes, protocols — nothing a review finding belongs to. Following the hint
faithfully is impossible; following it with a borrowed kind is a misuse the next reader cannot
tell from a mistake. Found while preparing the TASK-UNBLOCK-01 escalation, 2026-09-17.
