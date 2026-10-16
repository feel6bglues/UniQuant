# CLAUDE.md — Repository Coding Rules

> **Status of this file (read first):** the project control doc (`AGENTS.md`) and several
> prompts reference a root `CLAUDE.md` containing "the 10 coding rules". That file was
> **never committed to this repository** (`git log --all -- CLAUDE.md` is empty; a
> whole-repo search finds only *references* to it, never the rules themselves).
>
> Rather than fabricate the missing original, this file is an **honest consolidation** of
> the binding rules that *do* exist, each cited to its authoritative source. Where a rule
> is enforced by tooling, the enforcement command is given. If a rule here ever conflicts
> with `AGENTS.md`, `AGENTS.md` wins — it is the canonical control document.

Non-negotiable. Every edit, test, and commit in this repository must follow these rules.

---

## The 10 rules

### 1. Test-driven development
Write the failing test first (RED) → minimal implementation (GREEN) → refactor.
Minimum coverage **80%**. Every change ships with unit + integration (and, where a user
flow exists, E2E) tests.
*Source: `AGENTS.md` → "Testing Requirements"; harness `AGENTS.md` → "Core Principles".*

### 2. `ruff` must be clean
Zero lint findings across `src/uniquant/`, `tests/`, `scripts/` (CI lint covers all three).
```bash
ruff check src/uniquant/ tests/ scripts/     # must print "All checks passed!"
```
*Source: `AGENTS.md` → "Common Commands" / CI `test.yml`.*

### 3. Never claim unverified results
Do **not** report that tests pass unless the command was run **in the current working
tree**. Report the real count. If a number is unknown, say so — an honest "unknown" beats
a plausible invention.
*Source: `AGENTS.md` → "Do not claim test results are current unless the command was run in
the current working tree."*

### 4. No fabrication of inputs to satisfy a gate
Gate / verdict code must consume **real measured inputs**. If a required input
(e.g. a residual-IC series, a PBO value, an economic plausibility dict) is missing,
**fail closed** (e.g. `TIER_UNRATED`) with an explicit reason — never substitute a
constant, a self-comparison, or a hard-coded pass so a candidate can advance.
*Source: `AGENTS.md` → "P0-1 四阶门禁诚实化" (2026-10-16); `research/gates/alpha_tier_engine.py`.*

### 5. Immutability
Never mutate an object in place. Return a new copy with the change applied.
*Source: harness `AGENTS.md` → "Core Principles #4" / "Coding Style → Immutability (CRITICAL)".*

### 6. Preserve the A-share trading rules
T+1, board-specific price limits, ST limits, stamp duty, transfer fee, slippage and lot
size live in dedicated modules and are load-bearing. **Any change touching them requires
focused tests and explicit review.**
*Source: `AGENTS.md` → "A-Share Rules To Preserve" and "High-Risk Files".*

### 7. Security first
No hardcoded secrets (env vars / secret manager only, validated at startup); validate all
input at system boundaries; parameterized queries only; never leak sensitive data in error
messages. If a security issue is found: stop, fix, rotate, then re-scan for the same class.
*Source: harness `AGENTS.md` → "Security Guidelines".*

### 8. Surgical changes
Minimal, focused diffs. Do not revert user or prior-agent work. Treat the working tree as
possibly dirty — inspect `git status --short` before editing. Prefer narrow analysis and
narrow edits over broad rewrites.
*Source: `AGENTS.md` → "Working Rules For Agents"; cited as "Surgical Changes" in
`docs/analysis/WYCKOFF_IMPLEMENTATION_AUDIT_20260802.md`.*

### 9. Keep code small and shallow
Many small files over few large ones; functions **< 50 lines**; files **< 800 lines**;
nesting **≤ 4 levels**; no hardcoded magic values. Organise by feature/domain.
*Source: harness `AGENTS.md` → "Coding Style" / "Code quality checklist".*

### 10. Documentation drift is a blocker
After **any** code change, update `AGENTS.md` and all affected docs under `docs/` (at
minimum: file counts, LOC, test counts, phase status). Treat stale docs as a blocker, not
a backlog item. When a doc claim cannot be reconciled with the code, correct the doc or
mark it superseded — do not leave it silently wrong.
*Source: `AGENTS.md` → "Working Rules For Agents → Sync docs with every change".*

---

## Verification checklist (run before every commit)

```bash
ruff check src/uniquant/ tests/ scripts/          # rule 2
pytest tests/ -q                                   # rule 1 & 3
git status --short                                 # rule 8 (surgical changes)
git diff --stat                                    # rule 10 (docs synced?)
```

Rules 4, 5, 6, 7 and 9 are design constraints reviewed by reading the diff; they are not
fully machine-checked, so they are covered by the focused tests required in rule 6 and by
review.
