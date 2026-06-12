# Research Platform Gap Plan

Generated: 2026-06-09

Scope: Reframe UniQuant as an offline A-share quantitative research platform. This plan intentionally excludes live broker integration, automatic order routing, and real-money operations.

## 1. 目标定位

UniQuant 的近期目标调整为：

```text
数据获取与校验
  -> 单票/股票池研究
  -> 多引擎分析
  -> 因子评估
  -> 历史信号序列生成
  -> A 股规则回测
  -> 研究报告和实验归档
```

不纳入本阶段：

- 券商 API
- 自动下单
- 实盘订单状态机
- 实时持仓对账
- 实盘 kill switch
- 盘中监控告警

仍必须保留：

- T+1
- 涨跌停
- 停牌
- 交易成本
- 滑点
- 整手
- 数据时间点约束
- 实验可复现

## 2. 五项建议覆盖关系

| 建议 | 本计划对应阶段 | 目标 |
|---|---|---|
| 1. 补一份研究平台缺口计划 | Phase 0 | 明确研究平台定位、范围、优先级和验收标准。 |
| 2. 定义研究平台 MVP 工作流 | Phase 1 | 建立研究员可执行的一条标准链路。 |
| 3. 整理统一实验入口 | Phase 2 | 把分散脚本和服务串成统一 CLI/API 入口。 |
| 4. 优先修复历史信号时间序列回测问题 | Phase 3 | 让回测基于历史逐日信号，而不是当前一次性信号。 |
| 5. 固化因子准入和报告模板 | Phase 4 | 让因子研究可复现、可比较、可准入。 |

## 3. Phase 0 - 研究平台定位与控制文档

Priority: P0

### 任务

1. 建立本文件作为研究平台整改总计划。
2. 在 `docs/index.md` 增加研究平台分析入口。
3. 明确当前不做实盘自动化交易。
4. 将 Stage 0-7 分析结论归纳为研究平台缺口，而不是实盘缺口。

### 交付物

- `docs/analysis/08_research_platform_gap_plan.md`
- 可选：`docs/research_platform.md`

### 验收标准

- 文档明确研究平台范围。
- 文档明确暂缓实盘自动化内容。
- 文档包含后续 Phase 1-4。
- 文档能直接指导后续开发拆解。

## 4. Phase 1 - MVP 研究工作流

Priority: P0

### 目标工作流

```text
research run
  --universe stock_list
  --start 2020-01-01
  --end 2025-12-31
  --engines regime,lppl,ntf,czsc,wyckoff,alpha
  --factors enabled
  --strategy decision_brain
  --report
```

标准流程：

1. 读取股票池。
2. 获取并校验数据。
3. 运行多引擎分析。
4. 计算或读取因子。
5. 生成历史信号序列。
6. 运行回测。
7. 输出报告和实验归档。

### 重点涉及文件

- `src/uniquant/services/research_pipeline.py`
- `src/uniquant/services/analysis_service_v2.py`
- `src/uniquant/services/data_service.py`
- `src/uniquant/signal/adapters.py`
- `src/uniquant/hands/backtest/unified_engine.py`
- `scripts/`
- `experiments/`

### 交付物

- 研究工作流说明文档。
- 股票池输入规范。
- 实验配置规范。
- 输出目录规范。

### 验收标准

- 能用一个标准配置描述一次研究实验。
- 能区分单票研究和股票池研究。
- 能记录数据区间、股票池、引擎、因子、策略、参数。
- 能输出统一结果目录。

## 5. Phase 2 - 统一实验入口

Priority: P0

### 目标

把当前分散的 `experiments/`、`scripts/`、services 调用整理为一个统一入口。

建议入口：

```bash
python scripts/research_run.py --config config/research/example.yaml
```

或模块入口：

```bash
python -m uniquant.research.run --config config/research/example.yaml
```

### 配置草案

```yaml
experiment:
  name: hs300_single_factor_smoke
  output_dir: outputs/research
  seed: 42

universe:
  source: file
  path: config/universe/hs300_sample.txt

period:
  start: "2020-01-01"
  end: "2025-12-31"

data:
  adjust: qfq
  require_fields:
    - date
    - open
    - high
    - low
    - close
    - volume
    - pre_close

analysis:
  engines:
    - regime
    - lppl
    - ntf
    - czsc
    - wyckoff
    - alpha

signals:
  policy: decision_brain_first
  default_shares: 100

backtest:
  initial_capital: 100000
  execution: next_open
  a_share_rules: true

reports:
  formats:
    - markdown
    - csv
```

### 重点涉及文件

- `scripts/research_run.py` or `src/uniquant/research/run.py`
- `config/research/`
- `src/uniquant/services/research_pipeline.py`
- `src/uniquant/hands/reporter.py`
- `src/uniquant/hands/results_manager.py`

### 交付物

- 一个统一 CLI 入口。
- 一个 example YAML。
- 一个结果输出目录结构。
- 一份运行说明。

### 验收标准

- 单条命令能启动一次研究实验。
- 运行结果包含配置快照。
- 运行结果包含数据质量摘要。
- 运行结果包含信号、交易、权益曲线和指标。
- 实验失败时有明确错误信息和 trace id。

## 6. Phase 3 - 历史信号时间序列回测

Priority: P0

### 背景问题

Stage 5 和 Stage 6 已确认：当前 `UnifiedResearchPipeline` 用 `pd.Timestamp.now()` 给收集到的信号打时间戳。作为历史研究回测，这会导致：

- 历史 K 线日期无法匹配当前时间戳。
- 回测可能没有交易。
- 即使有交易，也不是逐日历史信号序列。

### 目标

实现历史滚动信号生成：

```text
for each trade_date in research_period:
    use data <= trade_date
    run analysis as-of trade_date
    create signal timestamp = trade_date
    backtest executes at next open
```

### 设计原则

- 每个信号只能使用当日及以前可见数据。
- 信号时间戳必须等于研究日。
- 回测成交由 `UnifiedBacktestEngine` 继续执行 T+1 open 逻辑。
- 缺失数据日应记录跳过原因。
- 每日信号需要保存成表。

### 重点涉及文件

- `src/uniquant/services/research_pipeline.py`
- `src/uniquant/services/analysis_service_v2.py`
- `src/uniquant/services/data_service.py`
- `src/uniquant/signal/adapters.py`
- `src/uniquant/hands/backtest/unified_engine.py`

### 交付物

- `HistoricalSignalRunner` 或等价服务。
- 每日信号表：

```text
date, symbol, action, confidence, shares, price, reason, source_policy, trace_id
```

- 历史信号到回测的集成测试。

### 验收标准

- 历史回测不再依赖 `pd.Timestamp.now()`。
- 信号日期全部落在 K 线日期范围内。
- T 日信号在 T+1 open 成交。
- 同一 symbol/date 最终只有一个可执行信号。
- 输出每日信号 CSV。

## 7. Phase 4 - 因子准入和报告模板

Priority: P1

### 目标

把因子研究从“脚本实验”升级为“标准研究流程”。

### 因子准入流程

```text
factor candidate
  -> schema check
  -> no lookahead check
  -> NaN/Inf check
  -> in-sample IC/IR
  -> factor correlation pruning
  -> walk-forward OOS
  -> PBO / overfit check
  -> cost-aware portfolio backtest
  -> admission report
```

### 准入指标建议

| Gate | Suggested criterion |
|---|---|
| 数据完整性 | 必需字段存在，缺失率可解释。 |
| 安全性 | 无 Inf，NaN 只出现在合理 warmup 区间。 |
| 未来函数 | perturbation invariance 通过。 |
| IC | 至少一个周期 Rank IC 稳定非零。 |
| ICIR | 样本内和样本外均需达标。 |
| OOS | walk-forward OOS IC 不塌陷。 |
| PBO | 低于设定阈值。 |
| 相关性 | 与已准入因子不过度冗余。 |
| 成本后表现 | A 股成本后仍有正贡献。 |

### 报告模板

每个因子报告应包含：

- 因子名称
- 研究假设
- 所需字段
- 计算公式
- 方向定义
- 样本范围
- 股票池
- IC/IR 明细
- OOS 结果
- PBO 结果
- 相关性矩阵
- 成本后回测
- 准入结论

### 重点涉及文件

- `src/uniquant/brain/factors/registry.py`
- `src/uniquant/brain/factors/analyzer.py`
- `src/uniquant/brain/factors/composer.py`
- `src/uniquant/brain/factors/walk_forward_pipeline.py`
- `experiments/run_factor_ic_evaluation.py`
- `experiments/run_walk_forward_pipeline.py`
- `experiments/run_real_data_ic.py`

### 交付物

- `docs/research/factor_admission_standard.md`
- `docs/templates/factor_report.md`
- 因子准入 CLI 或脚本。
- 因子报告输出目录。

### 验收标准

- 任一候选因子可通过统一流程生成报告。
- 报告能明确 pass/fail。
- 报告记录数据范围、股票池、参数和版本。
- 准入结果能回写配置或生成候选配置建议。

## 8. 推荐执行顺序

| Order | Phase | Priority | Reason |
|---:|---|---|---|
| 1 | Phase 0 | P0 | 先锁定研究平台范围，避免继续按实盘标准扩散。 |
| 2 | Phase 3 | P0 | 历史信号时间序列是研究回测可信度的核心。 |
| 3 | Phase 1 | P0 | 把研究员工作流定义清楚。 |
| 4 | Phase 2 | P0 | 用统一入口固化工作流。 |
| 5 | Phase 4 | P1 | 因子准入可以在回测链路稳定后系统化。 |

## 9. 最小可交付版本

MVP 不要求覆盖所有模块。最小版本只需：

1. 读取一个股票池。
2. 对每只股票生成历史每日 DecisionBrain 信号。
3. 使用 `UnifiedBacktestEngine` 回测。
4. 输出信号 CSV、交易 CSV、权益曲线 CSV、Markdown 报告。
5. 保存实验配置快照。

MVP 验收命令示例：

```bash
python scripts/research_run.py --config config/research/smoke.yaml
```

MVP 输出示例：

```text
outputs/research/20260609_smoke/
  config_snapshot.yaml
  data_quality.csv
  daily_signals.csv
  trades.csv
  equity_curve.csv
  metrics.json
  report.md
```

## 10. 风险和依赖

| Risk | Impact | Mitigation |
|---|---|---|
| 历史 as-of 分析成本高 | 股票池研究慢 | 先做单票和小股票池 MVP，再缓存中间结果。 |
| data_pack schema 隐式 | 信号生成不稳定 | 固化研究用 data_pack schema。 |
| 多适配器信号冲突 | 回测结果不确定 | Phase 3 引入单一最终信号策略。 |
| 因子准入流程太重 | 阻塞 MVP | 因子准入放 P1，先跑 DecisionBrain 历史信号。 |
| 报告格式发散 | 难比较实验 | 固定输出目录和模板。 |

## 11. 下一步拆解

建议下一轮从 Phase 3 开始，因为它直接影响研究平台可信度。

第一批开发任务：

1. 设计 `HistoricalSignalRunner` 接口。
2. 让 runner 接收 `symbol`, `start`, `end`, `lookback_window`。
3. 每个交易日截断数据到当日。
4. 调用分析服务或轻量 DecisionBrain 路径生成信号。
5. 写出 `daily_signals.csv`。
6. 把 `daily_signals.csv` 转成 `TradingSignal` 列表。
7. 调用 `UnifiedBacktestEngine.run()`。
8. 输出交易、权益、指标和报告。

完成后再补 Phase 1/2 的统一 CLI 和配置文件。
