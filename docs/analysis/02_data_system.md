# Stage 2 - Data System

Generated: 2026-06-09

Scope: Data-layer source routing, data lake, cache/fallback, cleaning, validation, adjustment, and `fetch_for_brain()` behavior. No source code was modified and no tests were run in this stage.

## 1. 本阶段计划

1. Read Stage 0 and Stage 1 artifacts.
2. Trace the services data entry: `DataService.fetch_for_brain()`.
3. Trace `DataAccessService` lake/source fallback behavior.
4. Inspect `DataFetcher`, `DataIngestionService`, `SourceRouter`, and current concrete data sources.
5. Inspect `StorageManager` lake layout and read/write behavior.
6. Inspect cleaning, validation, adjustment, normalization, and cache invalidation.
7. Compare `config/config.yaml` source declarations to current source files.

## 2. 已阅读文件

| File | Purpose |
|---|---|
| `docs/analysis/00_architecture_map.md` | Architecture baseline. |
| `docs/analysis/01_services_orchestration.md` | Services boundary and Stage 2 input. |
| `config/config.yaml` | Data source, cache, network, and data lake declarations. |
| `src/uniquant/services/data_service.py` | Service-level data facade and `fetch_for_brain()`. |
| `src/uniquant/services/data_access_service.py` | Lake/source fallback and persistence logic. |
| `src/uniquant/data/data_fetcher.py` | Main concrete data fetcher and source setup. |
| `src/uniquant/data/data_ingestion_service.py` | Lazy data source initialization and router call. |
| `src/uniquant/data/data_pipeline_service.py` | Clean, validate, adjust pipeline. |
| `src/uniquant/data/lake/storage_manager.py` | Data lake paths, parquet read/write, symbol normalization. |
| `src/uniquant/data/pipeline/data_cleaner.py` | OHLC cleaning and amount creation. |
| `src/uniquant/data/pipeline/data_validator.py` | Required columns and OHLC consistency validation. |
| `src/uniquant/data/pipeline/data_adjuster.py` | QFQ/HFQ adjustment and lookahead mitigation. |
| `src/uniquant/data/managers/source_router.py` | Multi-source fallback, health, timeout/race behavior. |
| `src/uniquant/data/managers/market_data_coordinator.py` | Index, ETF, industry/sector paths. |
| `src/uniquant/data/sources/base.py` | Data source interface. |
| `src/uniquant/data/sources/tdx.py` | Local TDX source implementation. |
| `src/uniquant/data/utils/normalizer.py` | Field alias normalization. |
| `src/uniquant/shared/config_loader.py` | Config loading and validation. |
| `tests/test_data_access_service.py` | Fallback and persistence tests. |
| `tests/test_data_and_stock_query_regressions.py` | DataService fallback regression tests. |
| `tests/test_data_fetcher_init_fault_tolerance.py` | Data source init fault tolerance. |
| `tests/test_field_mapping.py` | Field alias normalization tests. |
| `tests/test_p1_cache_invalidation.py` | Cache invalidation regression tests. |
| `tests/test_p1_data_entry_injection.py` | Shared storage graph and injected data entry tests. |
| `tests/test_lookahead_bias.py` | Factor analyzer lookahead tests; not the main data path. |

## 3. 数据源矩阵

### Runtime Sources Actually Instantiated

`DataFetcher.__init__()` hard-codes this source list and wraps successful instances in `StandardAdapter` and `SourceRouter` (`src/uniquant/data/data_fetcher.py:77-89`):

| Source class | File | Primary use | Failure behavior |
|---|---|---|---|
| `TdxSource` | `src/uniquant/data/sources/tdx.py` | Local TDX `.day` files from configured/default TDX path. | Init/fetch failures are logged and return empty frames. |
| `BaostockSource` | `src/uniquant/data/sources/baostock.py` | Legacy online/source fallback. | Init failure skipped by `DataFetcher`. |
| `SinaSource` | `src/uniquant/data/sources/sina.py` | Legacy online/source fallback. | Init failure skipped by `DataFetcher`. |
| `ThsSource` | `src/uniquant/data/sources/ths.py` | Legacy online/source fallback. | Init failure skipped by `DataFetcher`. |
| `TencentSource` | `src/uniquant/data/sources/tencent.py` | Legacy online/source fallback. | Init failure skipped by `DataFetcher`. |

`DataIngestionService._init_sources()` independently initializes the same five sources lazily (`src/uniquant/data/data_ingestion_service.py:22-37`). This means there are two related but separate source-initialization paths:

- `DataFetcher.data_sources` and `DataFetcher.source_router`.
- `DataFetcher.ingestion`, whose `fetch_price()` initializes another `SourceRouter`.

Tests confirm source init is fault-tolerant:

- One or more source init failures do not crash `DataFetcher` (`tests/test_data_fetcher_init_fault_tolerance.py:21-35`).
- All source failures still allow `DataFetcher` creation with a list object (`tests/test_data_fetcher_init_fault_tolerance.py:40-56`).
- Empty `SourceRouter` returns an empty `DataFrame` instead of crashing (`tests/test_data_fetcher_init_fault_tolerance.py:73-83`).

### Config-Declared Sources

`config/config.yaml` declares `StockDataSource`, `IndexDataSource`, and `EtfDataSource` as enabled new merged sources, with legacy sources disabled (`config/config.yaml:121-205`). However, current `src/uniquant/data/sources/` contains files like `tdx.py`, `baostock.py`, `sina.py`, `tencent.py`, `ths.py`, `eastmoney.py`, `mootdx_local.py`, and `mootdx_online.py`; it does not contain `stock_sources.py`, `index_sources.py`, or `etf_sources.py` in the scanned top-level source directory.

`GlobalConfig._validate_data_sources_config()` only checks that `data_sources.sources` exists (`src/uniquant/shared/config_loader.py:276-286`). It does not validate that configured class paths are importable. Current main runtime source routing therefore appears to be code-driven by `DataFetcher` rather than config-driven by `data_sources.sources`.

Risk: `config/config.yaml` source declarations are likely stale or aspirational relative to the active source code path.

### Data Type Routing

| Data type | Current service path | Source/lake behavior |
|---|---|---|
| Stock daily | `DataService.fetch_for_brain()` -> `_load_data_with_fallback(symbol, "stock", ...)` -> `StorageManager.read_data(..., data_type="stock")` | Lake first, then `fetcher.get_price(symbol, adjust="qfq")`, then clean/write lake. |
| Benchmark index | `DataService.fetch_for_brain()` -> `_load_data_with_fallback("sh000300", "index", ...)` | Lake first for `sh000300`, then aliases `000300.SH`, `000300.SZ`, `000300`, then `fetcher.get_price("sh000300", adjust="")`. |
| ETF | `DataService.fetch_for_brain()` -> `_load_etf_data()` | Lake first for `510300` and `510300.SH` as `data_type="stock"`, then `fetcher.get_price("510300")`. |
| Index daily direct | `DataFetcher.fetch_index_daily()` -> `MarketDataCoordinator.fetch_index_daily()` | Uses `akshare_wrapper.fetch_index_daily(symbol)` and date filters/renames selected Chinese fields. |
| ETF daily direct | `DataFetcher.fetch_etf_daily_robust()` -> `MarketDataCoordinator.fetch_etf_daily_robust()` | Reuses `fetch_stock_daily(..., adjust="")`. |
| Industry/concept | `DataFetcher.fetch_industry_concept_data()` -> `MarketDataCoordinator.fetch_industry_concept_data()` | Currently returns two empty `DataFrame`s. |
| Sector daily | `DataFetcher.fetch_sector_daily()` -> `MarketDataCoordinator.fetch_sector_daily()` | Maps sector names to index symbols and fetches index daily. |
| Realtime | `DataFetcher.fetch_stock_real_time()` | Currently returns empty `DataFrame`. |

## 4. 数据流入流程

### Main Service Path

```text
ServiceContainer
  -> DataService(storage_manager=StorageManager)
  -> DataFetcher(data_dir=storage_manager.data_dir, storage_manager=StorageManager)
  -> DataService.fetch_for_brain(symbol)
       -> stock = _load_data_with_fallback(symbol, "stock")
       -> bench = _load_data_with_fallback("sh000300", "index")
       -> etf = _load_etf_data()
```

`DataService.__init__()` creates or receives a shared `StorageManager`, constructs `DataFetcher` with that same storage, and exposes `self.lake = self.storage_manager` (`src/uniquant/services/data_service.py:50-87`). `tests/test_p1_data_entry_injection.py:47-55` verifies a default `DataService` reuses the injected storage manager through its fetcher and pipeline adjuster. `tests/test_p1_data_entry_injection.py:57-70` verifies `ServiceContainer` uses one storage graph.

### Lake/Source Fallback

`DataAccessService.load_data_with_fallback()` is the main fallback helper for `fetch_for_brain()`:

1. Try `service.lake.read_data(symbol, data_type=data_type, market="cn")`.
2. If `data_type == "index"`, try aliases from a clean code: `.SH`, `.SZ`, and no suffix.
3. If lake is empty, call `service.fetcher.get_price(symbol, adjust)` where `adjust=""` for index and `"qfq"` otherwise.
4. Clean with `service.cleaner.clean_stock_daily()`.
5. Write cleaned data back to lake with `overwrite=True`.
6. Return a clone of cleaned data.
7. On exception, return empty `DataFrame`.

Evidence: `src/uniquant/services/data_access_service.py:130-177`.

Tests:

- Index aliases are checked for `"sh000300"` (`tests/test_data_access_service.py:22-39`).
- Fetch-and-save writes cleaned stock data (`tests/test_data_access_service.py:41-62`).
- Lake errors return empty frames and avoid writes (`tests/test_data_and_stock_query_regressions.py:31-47`).

### Source Fetch Path

`DataFetcher.get_price(symbol, adjust="")`:

1. Checks an in-memory LRU-style `_price_cache`.
2. Calls `DataIngestionService.fetch_price(symbol)`.
3. Processes the frame through `DataPipelineService.process(df, symbol, adjust=adjust)`.
4. Saves the processed result to `_price_cache`.

Evidence: `src/uniquant/data/data_fetcher.py:113-127`.

`DataIngestionService.fetch_price()` lazily initializes concrete source instances and calls `SourceRouter.fetch_with_fallback()` (`src/uniquant/data/data_ingestion_service.py:17-45`).

`SourceRouter.fetch_with_fallback()` tries adapters in order, catches circuit breaker errors and generic exceptions, and raises the last error only if all failed with an error; otherwise returns `None` (`src/uniquant/data/managers/source_router.py:232-246`).

## 5. 数据清洗校验流程

### Cleaning

`DataCleaner.clean()`:

- Returns empty input unchanged.
- Lowercases columns.
- Converts `open`, `high`, `low`, `close`, `volume` to numeric where present.
- Fills non-price numeric NaN such as `volume` with 0.
- Repairs OHLC consistency: `high = max(open, close, high)`, `low = min(open, close, low)`.
- Drops rows missing `date` or `close`.
- Converts `date` to datetime.
- Forward/back fills `open`, `high`, and `low`.
- Drops duplicate dates, keeping the last.
- Creates `amount = close * volume` when missing.
- Sorts by date and resets index.

Evidence: `src/uniquant/data/pipeline/data_cleaner.py:11-65`.

### Validation

`DataValidator.validate()` requires:

- `date`
- `code`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `amount`

Evidence: `src/uniquant/data/pipeline/data_validator.py:19-25`.

It also:

- Swaps `high`/`low` when `high < low`.
- Repairs high/open/close and low/open/close violations.
- Warns on non-positive `amount`.
- Warns on close pct change over 99%.
- Warns on date gaps over 14 days.
- Warns when `adjustflag` is missing or indicates unadjusted data.

Evidence: `src/uniquant/data/pipeline/data_validator.py:26-81`.

Important boundary: `DataService._load_data_with_fallback()` uses `DataAccessService.load_data_with_fallback()`, which cleans but does not call `DataValidator.validate()` before writing to lake (`src/uniquant/services/data_access_service.py:161-174`). `DataPipelineService.process()` does call cleaner, validator, and adjuster (`src/uniquant/data/data_pipeline_service.py:26-32`), but this only runs inside `DataFetcher.get_price()`. Therefore lake-read data consumed by `fetch_for_brain()` may be normalized by `StorageManager.read_parquet()` but is not revalidated at service boundary.

### Adjustment

`DataAdjuster.apply_adjustment()`:

- Accepts only `qfq` or `hfq`, otherwise returns raw input.
- Reads local factor data.
- Uses `pd.merge_asof(..., direction="backward")` to align factors by date.
- Supports a `cutoff_date` and filters data to `date <= cutoff` to reduce future corporate-action leakage.
- For QFQ, uses the last factor in the filtered raw data as the latest factor, not the absolute latest factor, explicitly to avoid leaking future dividend events.
- Clips extreme prices and volumes.

Evidence: `src/uniquant/data/pipeline/data_adjuster.py:159-279`.

`DataAdjuster.get_adjusted_data()` passes `cutoff_date=end_date` for both QFQ and HFQ (`src/uniquant/data/pipeline/data_adjuster.py:281-308`).

Risk: `DataPipelineService.process(df, symbol, adjust)` calls `apply_adjustment(symbol, df, method=adjust)` without a `cutoff_date` (`src/uniquant/data/data_pipeline_service.py:26-32`). In that case the cutoff becomes `df_merged["date"].max()` (`src/uniquant/data/pipeline/data_adjuster.py:213-219`), which is point-in-time for the supplied frame if the frame was already date-filtered. `DataFetcher.get_price()` fetches all available price data and then processes it before date filtering in `fetch_stock_daily()` (`src/uniquant/data/data_fetcher.py:170-178`), so callers using `fetch_stock_daily(start, end, adjust="qfq")` may receive prices adjusted relative to the full fetched range, not necessarily the requested `end_date`. Stage 6/Factor stages should inspect this for backtest lookahead risk.

## 6. 数据湖读写机制

`StorageManager` initializes the lake structure under `data_dir` (`src/uniquant/data/lake/storage_manager.py:24-56`):

```text
data/
  lake/
    quotes/
      daily/
      weekly/
      monthly/
      1mins/
      5mins/
    index/
  factors/
```

Path mapping:

| `data_type` | Path | Evidence |
|---|---|---|
| `daily` or `stock` | `data/lake/quotes/daily/{symbol}.parquet` | `src/uniquant/data/lake/storage_manager.py:531-534` |
| `weekly` | `data/lake/quotes/weekly/{symbol}.parquet` | `src/uniquant/data/lake/storage_manager.py:535-536` |
| `monthly` | `data/lake/quotes/monthly/{symbol}.parquet` | `src/uniquant/data/lake/storage_manager.py:537-538` |
| `factor` | `data/factors/{symbol}.parquet` | `src/uniquant/data/lake/storage_manager.py:539-540` |
| `index` | `data/lake/index/{symbol}.parquet` | `src/uniquant/data/lake/storage_manager.py:541-544` |
| `1mins`/`min1` | `data/lake/quotes/1mins/{symbol}.parquet` | `src/uniquant/data/lake/storage_manager.py:545-546` |
| `5mins`/`min5` | `data/lake/quotes/5mins/{symbol}.parquet` | `src/uniquant/data/lake/storage_manager.py:547-548` |
| other | `data/{data_type}/{symbol}.parquet` | `src/uniquant/data/lake/storage_manager.py:549-550` |

Read/write behavior:

- `read_data()` returns empty `DataFrame` if file missing, otherwise `read_parquet()` (`src/uniquant/data/lake/storage_manager.py:552-560`).
- `read_parquet()` optionally normalizes DataFrame columns using `normalize_dataframe_columns()` (`src/uniquant/data/lake/storage_manager.py:112-128`).
- `write_parquet()` rejects empty frames and rejects paths outside `data_dir` after resolving paths (`src/uniquant/data/lake/storage_manager.py:67-103`).
- `write_data()` writes to a temporary file then replaces the target (`src/uniquant/data/lake/storage_manager.py:562-584`).
- `save_data()` and `save_factor()` also implement temporary-file replacement for daily/factor data (`src/uniquant/data/lake/storage_manager.py:330-370`).

Security note: `write_parquet()` includes a path traversal guard requiring the resolved target path to start with the resolved `data_dir` path (`src/uniquant/data/lake/storage_manager.py:77-86`).

## 7. A 股字段要求表

| Field | Where required | Role | Notes |
|---|---|---|---|
| `date` | Cleaner, validator, backtest | Chronological index and signal matching. | Cleaner converts to datetime and sorts. |
| `code` | `DataValidator` | Source identity. | TDX adds `code` in `TdxSource.fetch_daily()`; cleaner does not create it. |
| `open` | Cleaner, validator, backtest | Execution price and OHLC consistency. | Backtest requires it. |
| `high` | Cleaner, validator, backtest required schema | OHLC consistency and indicators. | Backtest `_prepare_dataframe()` requires it but does not use high in main loop. |
| `low` | Cleaner, validator, backtest required schema | OHLC consistency and indicators. | Backtest `_prepare_dataframe()` requires it. |
| `close` | Cleaner, validator, analysis, backtest | Latest price, returns, equity curve. | `AnalysisService._calculate_derived()` reads latest `close`. |
| `volume` | Cleaner, validator, backtest | Suspension/liquidity checks. | Backtest rejects execution when volume <= 0. |
| `amount` | Cleaner, validator | Turnover/quality. | Cleaner creates it if missing. |
| `pre_close` | Backtest derived if missing | Limit checks and execution constraints. | `UnifiedBacktestEngine._prepare_dataframe()` creates from `close.shift(1).fillna(open)`. |
| `avg_daily_volume` | Backtest derived if missing | Slippage/liquidity impact. | Backtest creates rolling 20-day average if missing. |
| `adjustflag` | Validator warning only | Adjustment status. | Missing `adjustflag` is warning, not failure. |

Backtest minimum required columns are `date`, `open`, `high`, `low`, `close`, `volume` (`src/uniquant/hands/backtest/unified_engine.py:272-286`). Validator requires a stricter set including `code` and `amount` (`src/uniquant/data/pipeline/data_validator.py:19-25`).

## 8. `fetch_for_brain` 输出结构

There are two methods named `fetch_for_brain`; they are not equivalent.

### Active Services Path

`AnalysisService._prepare_data()` calls `self.data_service.fetch_for_brain(ticker)` (`src/uniquant/services/analysis_service_v2.py:291-301`). In the container, `data_service` is `src/uniquant/services/data_service.py`.

`DataService.fetch_for_brain(symbol)` returns:

| Key | Source | Description |
|---|---|---|
| `stock` | `_load_data_with_fallback(symbol, "stock", ...)` | Target stock daily frame. |
| `bench` | `_load_data_with_fallback("sh000300", "index", ...)` | HS300 benchmark frame. |
| `etf` | `_load_etf_data()` | 510300 ETF frame, or empty frame. |

Evidence: `src/uniquant/services/data_service.py:397-407`.

`AnalysisService` later appends `trace_id`, engine fields, `symbol`, `market`, `price`, `atr_stop`, and `returns` (`src/uniquant/services/analysis_service_v2.py:236-238`, `308-320`, `482-512`).

### Lower-Level DataFetcher Method

`DataFetcher.fetch_for_brain(symbol)` returns only `stock`, `symbol`, and `timestamp` (`src/uniquant/data/data_fetcher.py:246-253`). This method is not the one used by `AnalysisService` in the current service chain. It is a potential naming confusion and should not be used as evidence for the service-level `data_pack` shape.

## 9. 数据质量风险清单

| Priority | Risk | Evidence | Impact |
|---|---|---|---|
| High | Config source declarations do not match current source files. | `config/config.yaml:125-145` references `stock_sources`, `index_sources`, `etf_sources`; scanned `src/uniquant/data/sources/` lacks those files. | Operators may believe config controls routing when runtime uses hard-coded `DataFetcher` sources. |
| High | Service-level lake fallback cleans but does not validate before writing. | `DataAccessService.load_data_with_fallback()` cleans/writes at `src/uniquant/services/data_access_service.py:161-174`; no validator call. | Bad OHLC/schema can persist to lake if cleaner does not catch it. |
| High | QFQ adjustment may use full fetched range before requested-date filtering in `fetch_stock_daily()`. | `DataFetcher.get_price()` processes before `fetch_stock_daily()` date filters (`src/uniquant/data/data_fetcher.py:113-127`, `170-178`). | Potential lookahead bias for backtests using source-fetched adjusted data. |
| Medium | `DataValidator` requires `code`, but cleaner does not create it. | `DataValidator` required columns include `code`; `DataCleaner` creates `amount` but not `code`. | Non-TDX or already-clean data may fail validation in `DataPipelineService`. |
| Medium | `DataService.fetch_for_brain()` only checks stock data non-empty downstream; benchmark/ETF may be empty. | `AnalysisService._prepare_data()` checks only `data_pack["stock"]` (`src/uniquant/services/analysis_service_v2.py:294-300`). | Alpha/regime/decision may silently degrade. |
| Medium | Industry/concept data currently returns empty frames. | `MarketDataCoordinator.fetch_industry_concept_data()` returns two empty frames (`src/uniquant/data/managers/market_data_coordinator.py:55-60`). | Sector/industry-aware research is not live through this path. |
| Medium | Realtime stock data currently returns empty frame. | `DataFetcher.fetch_stock_real_time()` returns empty (`src/uniquant/data/data_fetcher.py:223-225`). | Live-readiness is limited. |
| Medium | Two source initialization paths can diverge. | `DataFetcher.__init__()` and `DataIngestionService._init_sources()` both initialize the five source classes. | Source health and source order may not be single-source-of-truth. |
| Low | Data lake freshness scan uses `_data_sources`, which is not visibly populated in read/write path. | `StorageManager.validate_freshness()` iterates `self._data_sources` (`src/uniquant/data/lake/storage_manager.py:510-527`). | Freshness report may miss real files. |
| Low | Config validation does not import or verify source class paths. | `GlobalConfig._validate_data_sources_config()` only checks `sources` exists (`src/uniquant/shared/config_loader.py:276-286`). | Configuration drift can pass validation. |

## 10. 哪些数据可用于回测、研究、展示

| Data | Current suitability | Reason |
|---|---|---|
| Lake `stock/daily` with OHLCV | Suitable for backtest if fields are present and dates are historical. | Backtest can derive `pre_close` and `avg_daily_volume`, but requires OHLCV. |
| Source-fetched adjusted stock data | Suitable only after lookahead review for date-bounded QFQ. | Adjustment may be computed before requested date filtering. |
| Lake `index` data | Suitable for regime/benchmark/alpha if populated. | Alias fallback exists for HS300; empty benchmark degrades alpha. |
| ETF 510300 data | Suitable for NTF/market context if populated. | Falls back to source but is stored as `data_type="stock"`. |
| Industry/concept data | Not currently suitable as real input from inspected path. | Coordinator returns empty frames. |
| Realtime data | Not currently suitable. | `fetch_stock_real_time()` returns empty. |
| Factor forward-return data | Research/backtest only, not live. | `tests/test_lookahead_bias.py` shows live mode should reject future-return computation, but this is factor analyzer behavior, not general data fetch behavior. |

## 11. 改进建议

1. Align `config/config.yaml` source declarations with actual source classes, or implement/import the declared `StockDataSource`, `IndexDataSource`, and `EtfDataSource` classes.
2. Extend `GlobalConfig._validate_data_sources_config()` to validate enabled source class paths are importable.
3. Add validation to `DataAccessService.load_data_with_fallback()` before writing fetched data to lake, or document why cleaner-only is sufficient there.
4. Add a date-bounded adjustment path for `fetch_stock_daily(start_date, end_date, adjust="qfq")` so the adjustment cutoff is the requested `end_date`.
5. Rename or deprecate `DataFetcher.fetch_for_brain()` to avoid confusion with `DataService.fetch_for_brain()`.
6. Add tests for `DataService.fetch_for_brain()` output keys and empty benchmark/ETF behavior.
7. Decide whether benchmark/ETF emptiness should mark engine status or pipeline warnings before brain analysis.
8. Consolidate source initialization so source health, order, and config are controlled in one place.
9. Implement or explicitly mark realtime and industry/concept paths as unavailable in health/readiness output.

## 12. 校验清单

- [x] Explained stock, index, ETF, sector/industry, and realtime data paths.
- [x] Explained empty data and source failure behavior.
- [x] Checked `date/open/high/low/close/volume/pre_close` handling and where fields are required or derived.
- [x] Explained data lake path mapping and read/write behavior.
- [x] Explained `fetch_for_brain()` active output structure.
- [x] Distinguished service-level `DataService.fetch_for_brain()` from lower-level `DataFetcher.fetch_for_brain()`.
- [x] Identified data quality, cache, source routing, and lookahead risks.
- [x] Bound findings to concrete files, functions, config lines, and tests.
- [x] Did not modify source code.
- [x] Did not claim tests passed; no test command was run.

## 13. 下一阶段输入

Stage 3 should analyze brain engines with this data context:

- `src/uniquant/services/analysis_service_v2.py`
- `src/uniquant/services/analysis/*_analysis_engine.py`
- `src/uniquant/brain/fsm/`
- `src/uniquant/brain/czsc/`
- `src/uniquant/brain/lppl/`
- `src/uniquant/brain/ntf/`
- `src/uniquant/brain/regime/`
- `src/uniquant/brain/wyckoff/`
- `src/uniquant/brain/alpha_decoupler/`
- `src/uniquant/brain/indicators/`
- `tests/test_analysis_engines.py`
- `tests/test_fsm.py`
- `tests/test_czsc_engine.py`
- `tests/test_lppl_engine_scan_windows.py`
- `tests/test_ntf_engine.py`
- `tests/test_regime_detector.py`
- `tests/test_wyckoff.py`
- `tests/test_alpha_decoupler.py`

Stage 3 should specifically verify how each engine behaves when `bench` or `etf` is empty, whether `data_pack` fields are documented, and which engine failures become tradeable signals through Stage 5.

## 14. 阶段结论

The data system has a functional lake-first/source-fallback service path, shared storage injection through the service container, and explicit cleaning/adjustment components. The highest-risk issues are configuration drift versus active source routing, service-level writes without validator enforcement, possible QFQ cutoff/lookahead ambiguity, and incomplete live/industry/realtime paths. For current research/backtest work, lake-backed OHLCV stock data is the most reliable input; benchmark and ETF data must be treated as optional unless Stage 3 proves engines handle missing frames safely.
