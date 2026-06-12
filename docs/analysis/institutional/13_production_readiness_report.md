# WS13 — Production Readiness Report

Generated: 2026-06-10

Scope: Honest assessment of UniQuant's production readiness as a **research platform**. Live trading, broker, HA, and DR are blueprint-only topics.

## 1. Production Readiness Score

| Dimension | Score | Rationale |
|---|---|---|
| Research pipeline | ✅ **READY** | WS1-WS12 audits confirm research pipeline is functional |
| Data ingestion | ✅ **READY** | Multi-source, validated, cached, adjustable (qfq/hfq) |
| Backtest execution | ✅ **READY** | T+1, limit-up/down, costs, slippage, suspension enforced |
| Signal generation | ⚠️ **PARTIAL** | Missing arbitration, timestamp fix needed (WS4/WS6 blueprints exist) |
| Risk controls | ⚠️ **PARTIAL** | DecisionBrain veto works; concentration/drawdown/survivorship gaps (WS10) |
| Live broker layer | ❌ **NOT READY** | Zero evidence of broker integration |
| Order management | ❌ **NOT READY** | No OMS, no order state machine, no fill reconciliation |
| Position management | ⚠️ **PARTIAL** | Only simulation positions (PortfolioService/PortfolioEngine) |
| High availability | ❌ **NOT READY** | No HA evidence |
| Disaster recovery | ❌ **NOT READY** | No DR evidence |
| Crash recovery | ❌ **NOT READY** | DecisionBrain has FSM state persistence; no process-level recovery |
| Observability | ⚠️ **BLUEPRINT** | WS11 design exists but not implemented |

## 2. Broker Layer Evidence

### Finding WS13-001 — No broker, OMS, or order gateway implementation exists (P0 for live trading)

Evidence:
- `rg -n "class.*Broker|class.*Order|class.*OMS|class.*Gateway" src/uniquant` → **zero results**.
- All execution code lives under `hands/backtest/` — simulation only.
- No `broker/`, `gateway/`, `oms/`, `live/` directories exist under `src/uniquant/`.
- `config/config.yaml` has no broker configuration section.
- `pyproject.toml` has no broker/OMS dependency.

Impact:
- The system cannot execute live trades.
- Any attempt to use UniQuant for live trading requires building the broker layer from scratch.

Risk Level: P0 (for live trading); GREEN (research scope correctly maintained)

Recommendation:
- Keep broker as deferred blueprint scope.
- WS14 should define BrokerAdapter and OrderGateway as target interfaces without implementation.

### Finding WS13-002 — HealthService checks research components, not production metrics (P2)

Evidence:
- `HealthService.get_system_health()` checks: config, data service, analysis service, brain, risk, cache, data lake, system (`health_service.py:49-88`).
- No uptime SLA, no connection pool health, no external dependency health.
- No broker connectivity check (correct, since no broker exists).

Impact:
- Health service is adequate for research platform monitoring.
- Not sufficient for production-grade trading system health checks.

Risk Level: P2 (research scope correctly scoped)

### Finding WS13-003 — Data feed failure handling is local to each source (P2)

Evidence:
- Each data source (Sina, Tencent, EastMoney, BaoStock, TDX) has individual error handling with `handle_errors` decorator.
- `data_fetcher.py` has retry logic with jitter (`retry_on_exception`).
- `DataSource` base class uses `pybreaker.CircuitBreaker` (`base.py:11-20`).
- No unified data feed health monitor.
- No data feed fallback chain — if one source fails, the next is tried only if the caller implements fallback.

Impact:
- Individual sources are resilient, but there is no global data feed failover policy.
- A source change requires code modification, not configuration.

Risk Level: P2

Recommendation:
- Define a `DataFeedHealthMonitor` that tracks source availability and triggers fallback.
- Add data-source-level health endpoint to `HealthService`.

### Finding WS13-004 — Cache/storage failure handling uses decorator patterns (P2)

Evidence:
- `DataService.fetch_data()` uses `@handle_errors(DataFetchError, DataValidationError, DataStorageError, CacheError, default_return=None)` (`data_service.py:164-169`).
- Cache degradation returns `None`; callers must handle.
- `DataService._fetch_from_lake()` raises `DataStorageError` on failure.
- `CacheCoordinator` has internal cache but no persistence/recovery.

Impact:
- Cache failures degrade gracefully (return None), but the caller chain may produce empty results without clear diagnostic.
- Storage failures are caught and logged, but there is no automatic recovery.

Risk Level: P2

Recommendation:
- Add cache health monitoring to `HealthService`.
- Document that cache failures produce None results — callers should distinguish "no data" from "cache error".

### Finding WS13-005 — No crash recovery mechanism for long-running processes (P1 for batch)

Evidence:
- `ScanService`, `DataService.batch_process_stocks()`, and `ResearchPipeline.run_batch()` process multiple symbols.
- If a process crashes mid-batch, there is no checkpoint, progress save, or restart mechanism.
- `DecisionBrain._save_state()` persists FSM state to disk, but only for the DecisionBrain state machine — not for pipeline progress.

Impact:
- A 5000-symbol batch scan that crashes at symbol 3000 loses all progress.
- Batch jobs must start from scratch.

Risk Level: P1 (for batch research)

Recommendation:
- Add checkpoint file to `ScanService`: save processed symbol list and partial results.
- On restart, skip already-processed symbols.

### Finding WS13-006 — No position recovery mechanism (P1 for live, Info for research)

Evidence:
- `PortfolioService._current_weights` is in-memory only — no persistent position store.
- `PortfolioService.rebalance()` has rollback but no crash survival.
- No position reconciliation with any external account.

Impact:
- Research positions are ephemeral — lost on process restart.
- This is acceptable for research (positions are recomputed from signals), but would be critical for live trading.

Risk Level: P1 (for live); Info (research)

Recommendation:
- Document that research positions are ephemeral and recomputed from signals.
- Add optional position persistence to `PortfolioService` for multi-session workflows.

### Finding WS13-007 — No order recovery evidence (P0 for live, Info for research)

Evidence:
- No order state machine exists.
- No order/pending/cancelled/filled status tracking.
- `UnifiedBacktestEngine` creates order intents as `pending_order` dict, executed immediately on next bar — no persistence.

Impact:
- Correct for research backtesting (orders are simulated).
- Would require a complete OrderStateMachine for live trading.

Risk Level: Info (research); P0 (live)

### Finding WS13-008 — No HA evidence (Info)

Evidence:
- Single-process architecture: `ServiceContainer` is a singleton.
- No load balancing, no failover, no replication.
- `HealthService` is local-only — no remote health endpoint.

Impact:
- HA is not a research requirement. Documented as deferred.

Risk Level: Info

### Finding WS13-009 — No RPO/RTO evidence (Info)

Evidence:
- No backup strategy for research data.
- No recovery time objective defined.
- Data lake parquet files are the closest thing to persistent state — local disk only.

Impact:
- Research data loss risk depends on data lake backup strategy.
- RPO/RTO not applicable for current research scope.

Risk Level: Info

## 3. Production Readiness Gap Summary

| Component | Research status | Live trading requirement | Gap |
|---|---|---|---|
| Broker integration | Not present | ✅ Required | **FULL GAP** — must be built |
| Order management | Not present | ✅ Required | **FULL GAP** — must be built |
| Position reconciliation | Not present | ✅ Required | **FULL GAP** — must be built |
| Data feed failover | Individual source retry | ✅ Required | Partial — no global policy |
| Cache HA | None | ⚠️ Important | Not needed for research |
| Crash recovery (batch) | None | ⚠️ Important | P1 for research batch |
| Crash recovery (live) | None | ✅ Required | **FULL GAP** |
| HA | None | ✅ Required | Not needed for research |
| DR / RPO / RTO | None | ✅ Required | Not needed for research |
| Observability (OTel) | Blueprint only | ✅ Required | WS11 design ready |
| Secrets management | None | ✅ Required | WS9 WS11 design ready |
| Rate limiting | Network source level | ✅ Required | Per-source, not global |

## 4. Gateway Design — Target Broker Interface

For WS14, define the target broker boundary (no implementation):

```python
@dataclass
class OrderCommand:
    symbol: str
    side: str  # "BUY" | "SELL"
    order_type: str  # "LIMIT" | "MARKET"
    price: float
    quantity: int
    time_in_force: str = "DAY"
    client_order_id: str = ""
    strategy: str = ""


@dataclass
class FillEvent:
    symbol: str
    side: str
    fill_price: float
    fill_quantity: int
    commission: float
    timestamp: datetime
    client_order_id: str
    exchange_order_id: str


class BrokerAdapter(Protocol):
    """Broker adapter interface — research mode and live mode."""

    def submit_order(self, order: OrderCommand) -> str:
        """Submit order, return client_order_id."""
        ...

    def cancel_order(self, client_order_id: str) -> bool:
        """Cancel order."""
        ...

    def get_order_status(self, client_order_id: str) -> Dict[str, Any]:
        """Get order status from broker."""
        ...

    def get_positions(self) -> Dict[str, Any]:
        """Get current positions from broker."""
        ...

    def get_account_balance(self) -> float:
        """Get available cash."""
        ...
```

Research mode implementation:
```python
class SimulatedBrokerAdapter:
    """Research-mode broker simulation using UnifiedMatchingEngine."""
    ...
```

## 5. Verification Checklist

- [x] Verified live broker layer evidence: INSUFFICIENT EVIDENCE (no Broker/OMS/Gateway class).
- [x] Audited data feed failure handling: per-source retry + circuit breaker, no global failover.
- [x] Audited cache/storage failure handling: decorator pattern returns default=None.
- [x] Audited crash recovery evidence: DecisionBrain state save only; no batch checkpoint.
- [x] Audited position recovery evidence: portfolio weights are in-memory only.
- [x] Audited order recovery evidence: no order state machine exists.
- [x] Audited HA evidence: single-process, no replication.
- [x] Audited RPO/RTO evidence: not defined, not applicable.
- [x] Scored production readiness separately from research readiness (§1).
- [x] Defined target BrokerAdapter interface for WS14.