# UniQuant 项目状态仪表盘

> 最后更新: 2026-06-21 | 代码版本: 263 文件 (58,231 LOC) | 重构进度: Phase 0-4 已完成 (v0.6.x) | 文档: 124 文件 (122 .md + 2 其他)

---

## 总览

```
完成度: ████████████████████ 100% 源码就绪 (263/263 .py 文件, 58.2K LOC)
测试数: ████████████████████ 76 测试文件 (951 通过, 12 失败, 7 跳过, 2 收集错误)
重构:   ████████████████████ Phase 0-4 已完成 (v0.6.x)
文档:   █████░░░░░░░░░░░░░░░ 124 文件 (大部分需更新以同步代码)
```

---

## 模块状态

### ✅ 完整（全部 8 个声明层均已就位）

| 包 | 文件数 | LOC | 说明 |
|----|:------:|:---:|------|
| `brain/` | 73 | 15,743 | 11 子包: CZSC、FSM、LPPL、NTF、Regime、Wyckoff、Factors(含 27 auto_mined)、Indicators、Screener、Alpha Decoupler |
| `data/` | 65 | 15,426 | 11 数据源(baostock/eastmoney/mootdx/sina/tdx/tencent/ths)、管道(pipeline)、湖(lake)、管理器(managers) |
| `services/` | 31 | 8,485 | DAG 容器、13 分析引擎、14 懒加载服务 |
| `shared/` | 37 | 5,716 | 5 Protocol 接口、常量子包(7 模块)、缓存、异常、配置、成本/滑点/限价笼 |
| `hands/` | 34 | 6,087 | 回测(统一引擎/撮合引擎/投资组合引擎)、策略框架(6 策略)、参数调优 |
| `signal/` | 7 | 2,075 | 信号模型、归一化、聚合、质量评估、adapters |
| `risk/` | 7 | 1,450 | 回撤分析、EVT、历史风险、组合优化、仓位管理、结构风险 |
| `ui/` | 8 | 3,248 | Streamlit dashboard、health_check、LPPL 可视化、4 个 manager_* |

> 配置: `config/` 含 4 个 YAML (config.yaml, trading.yaml, factors.yaml, optimal_params.yaml)

---

## 测试状态

| 指标 | 数值 |
|------|:----:|
| 测试文件数 | 76 |
| 测试用例数 | 966 |
| ✅ 通过 | 951 |
| ❌ 失败 | 12 |
| ⏭️ 跳过 | 7 |
| ⚠️ 收集错误 | 2 |

> 剩余阻塞: 详见 AGENTS.md 阻塞问题清单。P0 收集错误来自 `test_drawdown_analyzer.py` 和 `test_portfolio_engine_v2.py` 的 `from src.uniquant...` 导入风格。

---

## 文档状态

| 类别 | 状态 | 说明 |
|------|:----:|------|
| 总文件数 | 124 | 122 .md + 1 pyproject.toml + 1 .gitignore |
| 子目录 | 17 | audit_logs(27), packages(8), guides(6), reference(4), whitepaper(3), development(2), research(2) |
| 与代码同步 | 🔴 大部分过时 | 入口文档 index.md 已修复，STATUS.md 已更新，其余需跟进 |
| AGENTS.md 同步 | 🔴 需更新 | 声称 67 文件（实际 124），测试数需更新 |

### P0 已修复项

| 项 | 状态 |
|---|:----:|
| index.md 模块状态表（data/hands/signal 标注为"待迁移"） | ✅ 已修正 |
| STATUS.md 全量数据（44→263 文件, 10→951 测试） | ✅ 已修正 |
| docs/pyproject.toml 误导性副本 | ⏳ 待删除 |
| constants.py 过时引用 | ⏳ 待全局替换 |