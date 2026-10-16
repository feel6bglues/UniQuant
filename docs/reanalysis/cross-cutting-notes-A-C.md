# Cross-Cutting Notes: Phase A ↔ Phase C

> ⚠️ **历史快照（point-in-time audit）** — 本文档记录的是**撰写时点**的工作树状态。其中的文件数 / LOC / 测试数 / 覆盖率 / 死代码清单 / "已修复" 声明**均可能已失效**，且已知与当前实测口径不符。
> **请勿**将其作为当前状态的依据。当前真相源见 [`docs/index.md`](../index.md)、[`AGENTS.md`](../../AGENTS.md) 与 [`docs/analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md`](../analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md)。

> 2026-07-06 | 关键发现交换，供 Wave 2 输入

---

## A 发现影响 C 解释的项

| # | A 发现 | 对 C 的影响 |
|---|---|---|
| 1 | `data_fetcher.py` 中异常处理有 49% 是 `except Exception` 过度捕获 | 如果数据获取失败被静默吞掉，C 报告的"数据可用率"可能被高估。C 应验证：当 parquet 文件损坏时，data_fetcher 是否返回空 DataFrame 还是抛出异常 |
| 2 | `data/lake/` 存储管理器无明显数据完整性校验 | C 的 parquet 数据本身可能通过校验和验证，但上层的数据获取链路缺乏校验。C 应特别关注该路径 |
| 3 | 无 | — |

## C 发现影响 A 解释的项

| # | C 发现 | 对 A 的影响 |
|---|---|---|
| 1 | 数据湖 5934/5934 文件 100% 可读，数据范围 1992-2026 | 数据层的基础设施健康，A 的"data 层代码质量"评估时应考虑数据层实际运行数据良好这一事实 |
| 2 | 数据延迟 28 天（最新 2026-06-08） | 这在 A 的代码审计中不体现，但影响代码运行时的"可用性"评估 |
| 3 | `.tmp.lock` 文件残留占条目近半 | 这可能是代码中缺少清理逻辑的体现，与 A 的异常处理审计相关 |

## 联合建议

1. 在 Wave 2-D 中，应特别验证 data_fetcher 在 parquet 损坏时的行为
2. `.tmp.lock` 残留问题应在最终修复清单中列为 P1 项