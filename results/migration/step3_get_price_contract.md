# Step 3 对账报告 — get_price 湖优先重构（2026-10-12）

预注册依据：`docs/analysis/DATA_SOURCE_MIGRATION_PLAN.md` §6 Step3 + §8 C1-C5 + B-1 表（调用点迁移 25 行）。

## 1. GET_PRICE_RETURN_CONTRACT（冻结契约）

| 项 | 值 |
|---|---|
| 签名 | `get_price(symbol, adjust="", start_date=None, end_date=None)` |
| 源 | 湖优先（`StorageManager.read_data`）→ mootdx 本地兜底 → 双 miss 返回合同列空表（warning 不 raise） |
| 列 | 9 列 `date/open/high/low/close/amount/volume/reserved/code`；qfq/hfq 时 10 列（+`adj_factor`） |
| date dtype | `datetime64[ns]` |
| 排序/去重 | date 升序；date 去重（keep last） |
| volume/amount | 股 / 元（湖量纲，禁止改） |
| 复权 | qfq/hfq → `CorporateActionAdjuster`（只调 OHLC、volume 不动、+adj_factor 列、缺 gbbq 硬失败） |
| 锚点 | qfq 以湖最新日为锚（先复权后切片） |
| 回写 | **永不**（写湖归 data_access_service 管） |

## 2. 真数据冒烟（600519.SH，只读）

| 断言 | 结果 |
|---|---|
| raw 返回行数 / 末日 | 6,011 行 / 2026-09-23 ✓ |
| qfq 含 adj_factor 列 | ✓（10 列） |
| qfq volume == raw volume | ✓（np.array_equal） |
| 末日 qfq close == raw close | ✓（锚点性质） |
| cleaner 过真湖数据 | 行数不变、attrs 全 0（零修复零异常）✓ |
| config sources 收缩 | `['mootdx_local', 'mootdx_online']` ✓ |

## 3. C1-C5 关单状态

| 项 | 状态 | 证据 |
|---|---|---|
| C1 date 列 KeyError | ✅ 关 | 缺列 → `ValueError`（含 cleaner 输入列契约消息），`tests/test_data_cleaner_contract.py` ① |
| C2 amount 兜底造列 | ✅ 关 | 删 `close*volume` 兜底 → `ValueError`；amount NaN 只 warning 不 fill；混沌测试同批改语义（`test_missing_amount_column` 断言必须 raise） |
| C3 bfill 前视 | ✅ 关 | 删 bfill；首段 NaN 保持（前视回归用例锁死：填充值 ≠ 后续日值） |
| C4 OHLC 修复不可审计 | ✅ 关 | 修复条数进 `df.attrs["cleaner_repaired"]`（不加新列），真湖数据全 0 |
| C5 回写耦合 | ✅ 关（Step2a 已关） | 本次复验：全部 write_data 点过 `_assert_unadjusted_for_lake`；`rebuild_cache` 新接线护栏；`fetch_and_save_dataset` guard→write 顺序由测试锁定 |

## 4. 调用点迁移（B-1 表 #6-#18）

13 个生产文件行 / 18 个调用点全处置，修复点带 `# Step3: adjust 显式化（预注册§8 #N）` 审计注释。处置明细见迁移计划文档 §8 "B-1a WS-D 实施登记"。关键项：

- qfq 分支一律不写湖（护栏拦截 + 显式 log）；
- `_fetch_and_filter_price`/`fetch_from_source`/`fetch_and_save_dataset` 显式 `adjust=""`（消灭隐式 qfq 污染面）；
- LPPL `data_manager.py` 保留显式 qfq（研究侧唯一 qfq 消费者，断链期首次真正拿到数据）；
- `check_cache_consistency` 改湖 vs 缓存对比（不再依赖源取数）。

## 5. 测试总账

| 项 | 数量 |
|---|---|
| 新增用例（get_price 契约 8 + cleaner 契约 7 + 调用点语义 15 + config 收缩 4） | 34+ |
| 同批改写既有用例（fetcher 9 / chaos cleaner / e2e fixture 补 amount 3 / 缓存失效 2 / 回归 1） | 15+ |
| 数据域广域回归（`-k "data or fetcher or cleaner or config or lake or tdx or mootdx or adjuster or corporate or service"`） | **659 passed / 4 skipped / 0 failed** |
| ruff（全部改动文件） | 0 |

## 6. 边界与遗留

- mootdx_online 网络兜底**未接线**（配置体保留 enabled=false，待裁决）；
- `stock_data_updater` 与 `sync_local_tdx_day` 的双增量实现合并留 Step 5 排程项（本次只做显式化 + 空数据防御）；
- 源文件剪除（sina/tencent/ths/eastmoney/baostock 适配器本体 + `sources/__init__.py` 注册）= Step 4 剪枝范围；
- e2e fixture `_make_dirty_kline_df` 补真实 amount 列（cleaner 禁兜底后的"上游必须带真实 amount"契约体现）。
