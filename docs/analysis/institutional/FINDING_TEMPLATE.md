# Institutional Finding Template

Generated: 2026-06-09

Use this template for every institutional audit finding under `docs/analysis/institutional/`.

## Required Finding Format

```text
Finding ID:
Title:
Scope:

Evidence:
- File/class/function/config/test/command reference.
- If evidence is not available, write: INSUFFICIENT EVIDENCE.

Impact:
- Concrete effect on research validity, backtest integrity, data lineage, risk control, performance, observability, maintainability, or production readiness.

Risk Level:
- P0: Blocks trustworthy research or can produce materially false backtest/research conclusions.
- P1: High architectural, data, risk, performance, or maintainability risk; should be handled before broad platform scaling.
- P2: Important for institutional maturity but not blocking current research-platform use.
- Info: Context, documentation, or low-risk cleanup.

Recommendation:
- Specific action that can be implemented, tested, observed, and rolled back.

Migration Cost:
- Low: One module or narrow test/document change.
- Medium: Several modules or new contract/test surface.
- High: Cross-layer redesign, migration tooling, or staged rollout.

Priority:
- Sprint or execution order.

Verification:
- Test, static check, review artifact, data replay, benchmark, or manual audit step required to close the finding.
```

## Evidence Rules

1. Every claim must be tied to current source code, configuration, tests, or command output.
2. Historical docs can be background only; they are not sufficient evidence unless current source confirms them.
3. When a source file is absent or a behavior has not been tested in this audit pass, mark it explicitly as:

```text
INSUFFICIENT EVIDENCE
```

4. Do not infer production readiness from research/backtest code.
5. For live-trading topics, classify them as deferred blueprint scope unless a current broker/order/live execution implementation is found.

## Risk Closure Criteria

A finding is not closed until it has:

- A code/config/doc change or explicit no-change decision.
- A verification method.
- An owner or target workstream.
- A rollback or containment path for behavior-changing work.

