# UniQuant 早期探索性实验脚本归档档案 (2026年6月)

## 1. 归档背景
本项目根目录下历史遗留的 9 个单体探索性实验脚本由早期原型验证阶段创建（时间戳 2026-06-21）。
随着 UniQuant 全面重构成型为现代化分层投研与风控中枢（`src/uniquant/` 分布为 `brain/`, `data/`, `hands/`, `risk/`, `services/`, `research/`），根目录下的单体脚本已被系统化模块完全替代。

在 2026-09-24 进行的针对全库 607 个 Python 源代码与测试文件的 AST（抽象语法树）静态扫描确认：
**全库对该 9 个脚本的导入引用计数为严格的 0 处。物理归档对主工程投研链路无任何隐式破坏风险。**

## 2. 归档清单
| 原根目录文件名 | 文件大小 | 对应现代工程化替代模块/路径 |
| :--- | :--- | :--- |
| `deep_analysis_experiment.py` | 36.5 KB | `src/uniquant/services/analysis/` |
| `deep_analysis_v2.py` | 27.7 KB | `src/uniquant/services/analysis/` |
| `factor_analysis_only.py` | 15.9 KB | `scripts/factor_mining/run_conditional_validation.py` |
| `full_analysis_experiment.py` | 31.4 KB | `scripts/backtest/run_cnmm_purged_long_horizon.py` |
| `full_analysis_final.py` | 18.0 KB | `src/uniquant/services/portfolio_service.py` |
| `full_a_stock_analysis_optimized.py` | 21.9 KB | `src/uniquant/data/lake/storage_manager.py` |
| `full_a_stock_analysis.py` | 26.4 KB | `scripts/maintenance/sync_local_tdx_day.py` |
| `full_multi_model_analysis.py` | 31.3 KB | `src/uniquant/brain/` 多模型中台 |
| `research_experiment.py` | 46.0 KB | `src/uniquant/research/gates/alpha_tier_engine.py` |

## 3. 访问与恢复说明
本目录下的脚本仅供历史思路追踪与代码法医对比查阅。请勿在新的生产或投研代码中直接依赖此目录。
