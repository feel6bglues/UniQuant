# WS9 - Configuration Governance

Generated: 2026-06-10

Scope: configuration topology, hardcoded paths, hardcoded symbols, environment separation, secrets boundary, runtime feature flags, and validation controls for the research-platform-first UniQuant scope.

## 1. Evidence Base

Inspected:

- `config/config.yaml`
- `config/factors.yaml`
- `src/uniquant/shared/config_loader.py`
- `src/uniquant/shared/logger_factory.py`
- `src/uniquant/shared/env_config.py`
- `src/uniquant/shared/perf.py`
- `src/uniquant/services/data_service.py`
- `src/uniquant/data/parsers/tdx_parser.py`
- `src/uniquant/data/managers/adjust_factor_manager.py`
- `src/uniquant/brain/factors/registry.py`

Commands used:

```text
nl -ba config/config.yaml
nl -ba config/factors.yaml
nl -ba src/uniquant/shared/config_loader.py
rg -n "pd.Timestamp.now\(|datetime.now\(|/home/|sh000300|000001|default_shares|initial_capital|batch_size|parallel|workers|UNIQUANT|os.environ|getenv|api_key|token|secret|password|broker|tdx" config src/uniquant
rg -n "get_config\(\)\.get\(|get_config\(|config\.get\(|cfg\.get\(" src/uniquant
python importlib check for config data_sources class paths
```

## 2. Current Configuration Map

```text
config/config.yaml
 ├── base
 │    ├── data_lake
 │    ├── logging
 │    └── tdx
 ├── cache
 │    ├── global
 │    ├── ttl
 │    ├── limits
 │    ├── performance
 │    └── cleanup
 ├── network
 │    ├── timeout
 │    ├── retry
 │    ├── rate_limit
 │    ├── headers
 │    ├── sources
 │    ├── connection_pool
 │    └── ssl
 ├── data_sources
 ├── indicators
 ├── czsc
 ├── lppl
 ├── markets
 ├── risk
 └── brain

config/factors.yaml
 └── factors

src/uniquant/shared/config_loader.py
 └── GlobalConfig singleton
      ├── loads config.yaml if present
      ├── always loads factors.yaml
      ├── provides get(dot.path, default)
      ├── provides set(dot.path, value)
      └── performs shallow validation
```

## 3. Current Governance Status

| Area | Current status | Assessment |
|---|---|---|
| Central YAML | Present | Useful baseline |
| Factor YAML | Present | Needs registry reconciliation |
| Dot-path read API | Present | Broadly used |
| Runtime mutation API | Present | Needs audit trail / containment |
| Required section validation | Present | Shallow only |
| Environment overlays | Not found | Gap |
| Secrets layer | Not found | Gap |
| Typed schema | Not found | Gap |
| Feature flags for new architecture | Not found | Gap |
| Class-path validation | Not found | Gap |
| Hardcoded path control | Partial | Gap |
| Hardcoded benchmark control | Partial | Gap |

## 4. Findings

### Finding WS9-001 - Local TDX paths are embedded in repo config and code (P1)

Evidence:
- `config/config.yaml:15-18` sets `base.tdx.path` to `/home/james/.local/share/tdxcfv/drive_c/tc`.
- `src/uniquant/data/parsers/tdx_parser.py:423-428` embeds the same user-specific Wine TDX path as a non-Windows default in a test/main path.
- `src/uniquant/data/managers/adjust_factor_manager.py:94-100` and `src/uniquant/data/managers/adjust_factor_manager.py:144-150` include local absolute GBBQ fallback paths.

Impact:
- Research runs are machine-dependent.
- CI, collaborator environments, and production-like replay can silently fail or use different corporate-action inputs.
- Corporate-action handling is part of backtest integrity; path drift can affect adjusted prices.

Risk Level: P1

Recommendation:
- Move TDX root and GBBQ paths to `environment.local.yaml` or environment variables read through one typed config layer.
- Keep repo defaults relative or empty.
- Fail with an actionable validation error when local data paths are required but absent.

Migration Cost: Low

Priority: Sprint 3

Verification:
- Unit test: config validation rejects absolute user-home paths in committed default config.
- Integration smoke: TDX import path can be supplied through environment override.
- Static check: `rg "/home/james|tdxcfv|T0002/hq_cache/gbbq" config src/uniquant`.

### Finding WS9-002 - `data_sources.sources.*.class` entries are stale/non-importable (P1)

Evidence:
- `config/config.yaml:125-190` uses class paths like `data.sources.stock_sources.StockDataSource`, `data.sources.index_sources.IndexDataSource`, `data.sources.etf_sources.EtfDataSource`, and `data.sources.baostock.BaostockSource`.
- Importlib check from repo venv returned `ModuleNotFoundError: No module named 'data.sources'` for those config paths.
- Current source classes exist under `uniquant.data.sources.*`, e.g. `src/uniquant/data/sources/baostock.py`, `sina.py`, `tencent.py`, `eastmoney.py`, and `tdx.py`.
- `rg` found no current `StockDataSource`, `IndexDataSource`, or `EtfDataSource` classes under `src/uniquant/data`.

Impact:
- The data-source configuration is not a reliable runtime contract.
- Any future dynamic loader using these paths would fail at startup or silently bypass configured priorities.
- This undermines data lineage because configured source order may not match executed source order.

Risk Level: P1

Recommendation:
- Replace stale class paths with canonical `uniquant.data.sources.*` paths or remove unused dynamic class config.
- Add startup validation that imports every enabled source class.
- Add a source registry test that compares config source names to actual importable classes.

Migration Cost: Low

Priority: Sprint 3

Verification:
- Unit test: all `data_sources.sources.*.class` values for `enabled: true` are importable and expose the expected interface.
- Config smoke: startup fails fast on missing source class.

### Finding WS9-003 - No environment overlay model exists (P1)

Evidence:
- `src/uniquant/shared/config_loader.py:55-91` loads `config/config.yaml` or a fixed list of individual YAML files, then always loads `factors.yaml`.
- No inspected code path loads `config.{env}.yaml`, `environment.local.yaml`, profile-specific overrides, or a declared `UNIQUANT_ENV`.
- `config_loader.py:21` only declares required sections, not environment profiles.

Impact:
- Research, test, batch scan, and future paper/live modes cannot be separated cleanly.
- Local paths and performance knobs must live in shared files or ad hoc environment variables.
- Rollback is harder because behavior-changing switches are not isolated by environment.

Risk Level: P1

Recommendation:
- Introduce a deterministic overlay order:

```text
config/default.yaml
config/config.yaml
config/environments/{research,test,batch,paper}.yaml
config/local.yaml          # gitignored
environment variables      # explicit allowlist only
runtime overrides           # test-only or CLI-only
```

- Add `runtime.environment` and `runtime.profile` to the typed config.

Migration Cost: Medium

Priority: Sprint 3

Verification:
- Unit test: overlay precedence is deterministic.
- Unit test: `research` and `test` profiles produce different data/cache paths without editing committed config.
- Static check: `config/local.yaml` is ignored and not required.

### Finding WS9-004 - Config validation is shallow and untyped (P1)

Evidence:
- `src/uniquant/shared/config_loader.py:165-192` calls validation helpers.
- Validation checks required high-level sections and a small set of keys, e.g. `base.data_lake.path`, `cache.global.enabled`, `network.timeout.default`, and `risk.default_risk_pct`.
- It does not validate many behavior-changing sections in `config/config.yaml`, including `data_sources.sources.*.class`, `markets.benchmarks`, `indicators`, `czsc`, most `lppl` bounds, and feature flags that do not yet exist.
- `GlobalConfig.get()` returns `Any` and silently returns defaults on `KeyError` or `TypeError` at `config_loader.py:132-144`.

Impact:
- Invalid or misspelled config keys can silently fall back to defaults.
- Institutional audit closure cannot prove that runtime config matches intended contracts.
- Parameter drift can change research results without a failing test.

Risk Level: P1

Recommendation:
- Add typed config models for core sections: `RuntimeConfig`, `DataConfig`, `ResearchConfig`, `RiskConfig`, `BacktestConfig`, `PerformanceConfig`, `ObservabilityConfig`, and `FactorAdmissionConfig`.
- Keep `get(dot.path)` only as a compatibility API; typed access should be the default for new code.
- Add strict validation mode for CI and research replay.

Migration Cost: Medium

Priority: Sprint 3

Verification:
- Schema test: invalid LPPL bounds, missing benchmark symbol, non-importable data source, and out-of-range risk values fail validation.
- Snapshot test: effective config can be serialized with redacted secrets.

### Finding WS9-005 - Secrets boundary is absent (P2)

Evidence:
- `config/config.yaml:113-118` has SSL fields for `ca_bundle`, `client_cert`, and `client_key`, but no secrets provider or secret reference syntax.
- Search found masking references in `src/uniquant/shared/error_handling.py`, but no inspected config loader support for secrets.
- Search for `api_key`, `token`, `secret`, `password`, and `broker` found no active broker credential config in current research scope.

Impact:
- Current research scope is not blocked because no live broker credential path was found.
- Future data vendor, broker, or notification integration would likely add secrets ad hoc.
- Without a secrets boundary, production-readiness claims would be invalid.

Risk Level: P2

Recommendation:
- Define secret references in config but keep values outside repo:

```text
secrets:
  provider: env
  required:
    - DATA_VENDOR_TOKEN
```

- Redact secrets in effective-config dumps and logs.
- Keep broker secrets out of current implementation scope until WS13 production readiness.

Migration Cost: Low

Priority: Sprint 3 / WS13 bridge

Verification:
- Unit test: secret values are never serialized in config dumps.
- Static check: no committed files contain known secret key patterns.

### Finding WS9-006 - New architecture switches are not represented as feature flags (P1)

Evidence:
- WS4 requires `approximate_research` vs `strict_point_in_time` historical signal modes.
- WS6 and WS10 require `SignalArbitrator` and risk veto gates.
- WS8 recommends production use of `perf_section()` and per-symbol engine result caching.
- `config/config.yaml` contains no dedicated `runtime`, `pipeline`, `features`, `observability`, or `performance.instrumentation` section for these switches.
- `src/uniquant/shared/perf.py` is gated by `UNIQUANT_PERF`, while `config/config.yaml:357-360` only covers LPPL cache settings.

Impact:
- Migration cannot be staged cleanly.
- Behavior-changing refactors cannot be enabled per profile, measured, and rolled back.
- Research runs cannot record which architectural mode produced a result.

Risk Level: P1

Recommendation:
- Add default-off feature flags:

```text
runtime:
  environment: research
  profile: local

pipeline:
  analysis_mode: approximate_research
  use_historical_signal_runner: false
  signal_arbitration_enabled: false
  strict_point_in_time: false

risk:
  enforce_position_sizer: false
  max_position_pct: 0.1
  max_drawdown_pct: 0.2

performance:
  instrumentation_enabled: false
  engine_cache_enabled: false
  scan_parallel_workers: 1

observability:
  structured_logs: false
  trace_signal_lineage: false
  emit_effective_config_hash: true
```

Migration Cost: Low

Priority: Sprint 3

Verification:
- Contract test: default config preserves existing behavior.
- Migration test: enabling `signal_arbitration_enabled` changes only the adapter/arbitration path.
- Replay metadata test: pipeline output includes effective config hash and feature-flag snapshot.

### Finding WS9-007 - Mutable singleton config has no audit trail (P2)

Evidence:
- `src/uniquant/shared/config_loader.py:10-29` implements a singleton `GlobalConfig`.
- `src/uniquant/shared/config_loader.py:146-157` exposes `.set(dot.path, value)` and mutates the in-memory dict.
- No audit log, provenance marker, or freeze/read-only mode was found around runtime config mutation.

Impact:
- Long-running research or batch scans can be affected by in-process config mutation.
- Reproducibility is weaker because result artifacts may not know whether config was modified after load.
- Test pollution risk increases if singleton state leaks across tests.

Risk Level: P2

Recommendation:
- Add `freeze()` or immutable effective config for pipeline runs.
- Restrict `.set()` to tests/CLI overrides or require explicit `RuntimeOverride` provenance.
- Include effective config hash in `PipelineResult.metadata`.

Migration Cost: Medium

Priority: Sprint 3

Verification:
- Unit test: pipeline receives immutable config snapshot.
- Unit test: runtime `.set()` after snapshot does not change an in-flight run.

### Finding WS9-008 - Logging path semantics are inconsistent (P2)

Evidence:
- `src/uniquant/shared/config_loader.py:43-47` defines `LOG_DIR` from `cache.global.path`, defaulting to `"logs"`.
- `src/uniquant/shared/logger_factory.py:60` reads `base.logging.directory`, defaulting to `"logs"`.
- `config/config.yaml:11-13` defines logging level and format but no `base.logging.directory`.

Impact:
- Different logging helpers can write to different paths.
- Observability rollout in WS11 would inherit inconsistent log location behavior.
- Operational diagnostics are harder to standardize.

Risk Level: P2

Recommendation:
- Define one canonical `base.logging.directory`.
- Make `GlobalConfig.LOG_DIR` read `base.logging.directory`, not `cache.global.path`.
- Keep cache and log paths separate in config schema.

Migration Cost: Low

Priority: Sprint 3 / WS11

Verification:
- Unit test: `get_config().LOG_DIR` equals logger factory directory.
- Static check: no logging path reads from `cache.global.path`.

### Finding WS9-009 - Benchmark and default symbol selection is partially hardcoded (P1)

Evidence:
- `config/config.yaml:383-392` defines benchmark symbols under `markets.benchmarks`.
- `src/uniquant/services/data_service.py:397-407` hardcodes `sh000300` as benchmark data in `fetch_for_brain()`.
- `src/uniquant/services/data_service.py:528-537` hardcodes an ETF list in `download_etf_sector_data()`.
- `src/uniquant/services/research_pipeline.py:80` uses `pipeline.run("000001.SZ")` in example/demo code; `src/uniquant/ui/dashboard.py` also uses `000001.SZ` as UI default.

Impact:
- Research lineage does not prove which benchmark config drove a run.
- A benchmark change requires code edits in at least one data-service path.
- Hardcoded ETFs can drift from `markets.etfs.default_list`.

Risk Level: P1

Recommendation:
- Route benchmark selection through typed `markets.benchmarks.default` or `research.benchmark_symbol`.
- Route ETF sector downloads through `markets.etfs.default_list`.
- Attach benchmark symbol and source to `ResearchDataPack.metadata`.

Migration Cost: Low

Priority: Sprint 3

Verification:
- Unit test: changing `research.benchmark_symbol` changes `fetch_for_brain()` benchmark without source edits.
- Data lineage test: `ResearchDataPack.metadata.benchmark_symbol` is populated.

### Finding WS9-010 - Environment variable governance is split from config governance (P2)

Evidence:
- `src/uniquant/shared/env_config.py:32-38` sets thread-related environment variables and `LPPL_DISABLE_PARALLEL`.
- `src/uniquant/shared/perf.py` gates instrumentation with `UNIQUANT_PERF`.
- `src/uniquant/shared/cost_model.py` reads environment variables for execution-cost overrides.
- `config/config.yaml:303-311` separately configures LPPL optimizer workers.

Impact:
- Effective runtime behavior is not fully represented by `config/config.yaml`.
- Performance and numerical behavior can differ between shells even when YAML is unchanged.
- WS8 benchmarking and WS11 observability need one effective runtime snapshot.

Risk Level: P2

Recommendation:
- Add an explicit environment-variable allowlist in the config layer.
- Normalize environment-derived settings into the effective config snapshot.
- Record selected thread limits, LPPL parallel mode, and performance instrumentation state in run metadata.

Migration Cost: Medium

Priority: Sprint 3

Verification:
- Unit test: effective config includes redacted/normalized environment-derived values.
- Benchmark metadata check: run artifact records thread and perf settings.

### Finding WS9-011 - Factor config can drift from factor registry (P1)

Evidence:
- `config/factors.yaml:1-15` enables `momentum_20d`, `turnover_momentum_20d`, and `pe_ttm`.
- `src/uniquant/brain/factors/registry.py:63-82` reads `factors.{name}` overrides when a factor registers.
- WS7 already identified `pe_ttm` as enabled in config but not registered in the current factor registry path.
- No startup validation was found that fails when a factor is configured but missing from registry.

Impact:
- Factor admission and factor weighting can appear configured while not actually participating.
- Research reports can overstate factor coverage.
- Admission governance cannot prove that config and executable factor universe match.

Risk Level: P1

Recommendation:
- Add factor config reconciliation:

```text
configured_factors - registered_factors = error or explicit quarantine
registered_factors - configured_factors = default policy
```

- Connect reconciliation output to WS7 `FactorAdmissionReport`.

Migration Cost: Low

Priority: Sprint 3

Verification:
- Unit test: `pe_ttm` configured-but-unregistered fails strict validation.
- Admission report includes configured, registered, admitted, rejected, and quarantined factors.

## 5. Target Configuration Architecture

```text
Environment Layer
 ├── UNIQUANT_ENV
 ├── UNIQUANT_PROFILE
 ├── explicit allowlisted env overrides
 └── local paths / secrets references

Config Layer
 ├── default config
 ├── profile overlay
 ├── local overlay
 ├── typed schema validation
 ├── class-path validation
 ├── factor registry reconciliation
 └── immutable effective config snapshot

Secrets Layer
 ├── env provider for current scope
 ├── external provider placeholder for future WS13
 └── redaction in logs/reports

Runtime Feature Layer
 ├── historical signal mode
 ├── signal arbitration
 ├── risk gates
 ├── factor admission gates
 ├── performance instrumentation
 ├── engine result cache
 └── observability/tracing
```

## 6. Proposed Config Sections

```yaml
runtime:
  environment: research
  profile: local
  strict_validation: true

paths:
  data_lake: data/lake
  cache: data/cache
  logs: logs
  tdx_root: null
  gbbq_path: null

research:
  benchmark_symbol: sh000300
  universe_config: null
  analysis_mode: approximate_research
  strict_point_in_time: false

pipeline:
  use_historical_signal_runner: false
  signal_arbitration_enabled: false
  attach_effective_config: true

risk:
  enforce_position_sizer: false
  max_position_pct: 0.1
  max_drawdown_pct: 0.2

factor_admission:
  enabled: false
  strict_registry_reconciliation: true
  min_ic: 0.02
  min_ir: 0.3
  require_oos: true
  require_pbo: true
  cost_aware: true

performance:
  instrumentation_enabled: false
  engine_cache_enabled: false
  scan_parallel_workers: 1
  dataframe_copy_policy: defensive

observability:
  structured_logs: false
  metrics_enabled: false
  tracing_enabled: false
  emit_effective_config_hash: true

secrets:
  provider: env
  required: []
```

## 7. Migration Plan

### Step 1 - Validation without behavior change

- Add schema and validation tests.
- Keep current `GlobalConfig.get()` behavior.
- Emit warnings for stale class paths, hardcoded local paths, missing logging directory, and factor registry drift.

### Step 2 - Effective config snapshot

- Build immutable `EffectiveConfig`.
- Attach `config_hash`, `profile`, and feature flags to research outputs.
- Keep `.set()` for tests but exclude it from production pipeline flows.

### Step 3 - Feature flags

- Add default-off flags for WS4, WS6, WS7, WS8, WS10, and WS11 changes.
- Gate behavior-changing migrations behind these flags.
- Record flag state in every `PipelineResult`.

### Step 4 - Environment and local overlays

- Introduce `config/environments/research.yaml`, `config/environments/test.yaml`, and gitignored `config/local.yaml`.
- Move machine-specific TDX and GBBQ paths out of committed defaults.

### Step 5 - Strict mode

- Enable strict validation in CI and institutional replay.
- Fail fast on non-importable data source class paths, configured-but-unregistered factors, and invalid risk/performance settings.

## 8. Test Matrix

| Test | Purpose | Priority |
|---|---|---|
| Config schema validation | Reject invalid type/range/path/class config | P1 |
| Environment overlay precedence | Prove deterministic config layering | P1 |
| Source class import validation | Catch stale `data_sources` paths | P1 |
| Factor registry reconciliation | Catch configured but missing factors | P1 |
| Benchmark config routing | Remove hardcoded `sh000300` from lineage-critical path | P1 |
| Local path leak scan | Prevent `/home/...` paths in committed config | P1 |
| Effective config hash | Make research outputs reproducible | P1 |
| Feature flag defaults | Preserve existing behavior by default | P1 |
| Secrets redaction | Prevent secret leakage in logs/reports | P2 |
| Log/cache path separation | Standardize observability output paths | P2 |
| Env var allowlist | Capture performance/thread env effects | P2 |

## 9. Sprint 3 Handoff

WS9 should feed:

- WS11 Observability: structured logs, metrics, traces, effective config hash, and log directory standardization.
- WS12 Event Architecture: runtime profile, command/event schema versioning, and feature flags for event migration.
- WS14 TDD Refactoring Design: config schema tests, feature-flag rollout tests, and rollback plan.

Current WS9 status:

```text
Configuration map: complete
Hardcoded path audit: complete
Hardcoded symbol audit: complete
Class-path audit: complete
Environment/config/secrets target: complete
Feature flag blueprint: complete
Test matrix: complete
```
