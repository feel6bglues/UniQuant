# src/uniquant/ 综合分析计划

> 基准: 254 Python 文件, 62,804 LOC, 27 个子包
> 方法: 8 阶段分布读取 + 并行子代理分析

---

## 分析范围

- **8 层架构**: shared → data → brain/risk/signal → hands → services → ui
- **4 大维度**: 结构、依赖、数据流、风险
- **验证对标**: 26 项 DSL (文档标准列表) 指标

## 阶段计划

### Phase 1: shared/ 层 (33 文件, 4,734 LOC + cache/ + constants/)
**关键文件**:
- `interfaces.py` (641) — 协议/接口/TradingSignal
- `config_loader.py` (419) — YAML 配置加载
- `analysis_result.py` (318) — 分析结果容器
- `error_handling.py` (498) — 错误/重试框架
- `limit_checker.py` (308) — A 股涨跌停规则
- `cost_model.py` (154) + `slippage_model.py` (44) + `price_collar.py` (32) — 交易成本模型
- `time_provider.py` (97) — G-1 时间抽象
- `event_bus.py` (89) + `event_types.py` (143) — 事件系统
- `exceptions.py` (123) — 异常层次
- `factor_governance.py` (156) — G-2 因子治理
- `config_models.py` (71) — Phase 4 特征开关
- `market_rules.py` (63) — 板块规则
- `cache/` 子包 — 缓存层
- `constants/` 子包 — 常量聚合

### Phase 2: data/ 层 (65 文件, ~15,000 LOC)
**关键文件**:
- `sources/` — 多数据源适配器 (Eastmoney 1094, Sina 609, THS 620, Tencent 368, Baostock 463, TDX 177)
- `managers/` — SDK 管理器 (13 文件, ~2,873 LOC)
- `pipeline/` — 清洗/验证/对齐/调整管线
- `lake/` — 数据湖存储
- `services/` — 数据导入器
- `scripts/` — 同步脚本

### Phase 3: brain/ 层 (74 文件, ~16,000 LOC)
**关键子包**:
- `wyckoff/` — 20 文件, 7,975 LOC (最大)
- `lppl/` — 11 文件, 3,576 LOC
- `factors/` — 9 文件, 2,169 LOC
- `fsm/` — 2 文件, 779 LOC
- `czsc/` — 2 文件, 649 LOC
- `indicators/` — 2 文件, 407 LOC
- `screener/` — 2 文件, 454 LOC
- `regime/` — 2 文件, 292 LOC
- `ntf/` — 2 文件, 192 LOC
- `alpha_decoupler/` — 2 文件, 352 LOC

### Phase 4: signal/ + risk/ 层 (14 文件, 4,325 LOC)
**signal/**: adapters (604), arbitrator (386), aggregator (367), models (280), normalizer (315), quality (289), db (315)
**risk/**: sizer (479), portfolio_optimizer (428), evt_risk (389), drawdown_analyzer (196), structural (106)

### Phase 5: hands/ 层 (20 文件, ~6,000 LOC)
**backtest/**: unified_engine (604), unified_matching (263), engine (747), portfolio_engine (373), 12 文件
**strategies/**: 10 文件, 1,629 LOC

### Phase 6: services/ + ui/ 层 (39 文件, ~13,000 LOC)
**services/**: analysis_service_v2 (648), analysis_service_legacy (1649), service_container (187), data_service (599), research_pipeline (547), 13 文件
**services/analysis/**: 13 文件 (各引擎包装器)
**ui/**: dashboard (1553), 8 文件

### Phase 7: 交叉层审计
- 8 层依赖方向违反
- `datetime.now` / `pd.Timestamp.now` 调用审计
- 跨层数据耦合
- God Object 检测

### Phase 8: 风险分析
- 前视偏差
- 隐式 NaN 传播
- 死代码 / 未使用导出
- 安全审计

---

## 实施策略

1. **Phase 1-3**: 并行启动 3 个子代理
2. **Phase 4-6**: 并行启动 3 个子代理
3. **Phase 7-8**: 基于前 6 阶段结果自动分析
4. 每个子代理返回: 结构摘要 + 依赖分析 + 关键风险 + 文档-代码偏差
