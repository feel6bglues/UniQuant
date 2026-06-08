# GLOBAL_SYSTEM_AUDIT_V3  — 全球全景审计终审报告

**审计周期**: 2026-06-06 | **项目**: UniQuant v0.3 (A 股量化交易平台)
**审计范围**: 全量 4 个队列 | **总文件数**: ~350 源文件 | **总代码行**: ~86,000 LOC

---

## 审计方法

- Phase 0: 全局动态建图，划分 4 个队列
- Phase 1: 逐个队列地毯式审计，每队列输出单独报告
- Phase 2: 跨队列碰撞检测，生成冲突矩阵
- Phase 3: 综合评分与修复路线图

---

## 系统健康评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 5 层 DAG 完整性 | 7/10 | 方向正确；`shared` 层全局状态多为函数内，非模块级 |
| 导入链可靠性 | 5/10 | 7 个幽灵依赖 + 1 个断裂导入 + 根目录 34 文件散落 |
| 并发安全性 | 4/10 | 8 个 `global` 状态点，多数无锁 |
| 测试有效性 | 5/10 | 77 测试文件，但 10 文件含 skip，`conftest.py` 仅 27 行 |
| 废弃代码管理 | 3/10 | 4 个 deprecated 函数 + `di_container.py` 滞留 |
| 配置一致性 | 6/10 | YAML 配置完备，但部分硬编码未迁移 |
| 函数/文件粒度 | 5/10 | 40+ 超大函数 + 2 个 1500+ 行单体 + 7 个大测试 |

**综合评分**: 5.0 / 10

---

## 🔴 致命问题 (Critical — 必须立即修复)

| # | 问题 | 影响 | 修复成本 | 引用 |
|---|------|------|----------|------|
| 1 | `price_collar.py` 断裂导入 `from ..shared.market_rules` | 任何 import 崩溃 | 1 行修复 | Q1-P0 |
| 2 | 7 个幽灵依赖未在 `pyproject.toml` 声明 | 环境搭建失败 | 7 行添加 | Q1-P1, Q2-P0, Q3-P1 |
| 3 | 8 个模块级 `global` 状态点 | 多线程竞态风险 | 中等 (加锁/重构) | Q1/Q2/Q3 |
| 4 | 34 根目录散落脚本 20,110 LOC | 项目入口混乱 + 逻辑重复 | 归档操作 | Q4-P0 |

---

## 🟠 重要问题 (Major — 本迭代修复)

| # | 问题 | 影响 | 修复成本 |
|---|------|------|----------|
| 5 | 2 个测试文件因引用失效完全跳过 | 测试覆盖率缺失 | 低 (删除或修复引用) |
| 6 | 4 个 deprecated 函数未清理 | 认知负担 + Warning 噪音 | 低 (移除调用方) |
| 7 | `analysis_service.py` (1650L) + `dashboard.py` (1524L) | 可维护性差 | 高 (需要拆分为多文件) |
| 8 | `ui/__init__.py` 空 + `data/utils/__init__.py` 无导出 | 包导出不完整 | 低 (补全导出) |
| 9 | 测试 `conftest.py` 仅 27 行 | 测试基础设施不足 | 中等 |

---

## 🟡 改进项 (Minor — 后续迭代)

| # | 问题 | 影响 |
|---|------|------|
| 10 | 7 个 CLI main() 未注册为 `console_scripts` | 无法命令行调用 |
| 11 | 40+ 函数 >100 行 | 可维护性 |
| 12 | 7 个测试文件 >400 行 | 可维护性 |
| 13 | 3 个存根脚本 | 无功能代码 |
| 14 | `hands/tuning/` 空目录 | 残留空壳 |
| 15 | `scripts/run_market_scan.py` 硬编码 30+ 行指数排除 | 可维护性 |

---

## 修复路线图 (即插即用)

### Sprint 1 (30 分钟)
```bash
# 1. 修复断裂导入
fix: price_collar.py from ..shared → from .  # 1 行

# 2. 补充 pyproject.toml 依赖
add: urllib3, pybreaker, backtrader, exchange_calendars,
     streamlit-aggrid, streamlit-autorefresh, streamlit-echarts  # 7 行

# 3. 清理完全跳过的测试（删除或提供引用脚本）
rm: tests/test_build_financial_v2.py   # 引用脚本不存在
rm: tests/test_stock_list_cli.py       # 引用脚本不存在

# 4. 清理存根脚本
rm: scripts/offline_full_test.py       # 4 行空壳
rm: scripts/verify_200.py              # 9 行包装
rm: scripts/verify_import.py           # 9 行包装
```

### Sprint 2 (2 小时)
```bash
# 5. 归档 34 个根目录脚本
mkdir -p scripts/archive
mv *.py scripts/archive/  # 选择性迁移，保留项目入口
# 恢复关键入口后运行验证

# 6. 清理 4 个 deprecated 函数
# 检查调用方，替换为新函数，删除旧函数

# 7. 补充 `ui/__init__.py` 导出；确认 `data/utils/__init__.py` 是否需补充

# 8. 扩展 conftest.py
```

### Sprint 3 (1 天)
```bash
# 9. 修复 8 个全局状态点
# - 为 error_stats 加锁
# - 为 health_service 加锁
# - 为 industry_provider._CACHE 加锁
# - 模块级单例改为懒初始化

# 10. 替换 run_market_scan.py 硬编码为 BoardType

# 11. 注册 7 个 CLI 入口
```

### Sprint 4 (2 天)
```bash
# 12. 拆分 analysis_service.py (1650L)
# 13. 拆分 dashboard.py (1524L)
# 14. 拆分 40+ 超大函数
# 15. 拆分 7 个超大测试文件
```

---

## 结算数据

| 指标 | Phase 1 审计 | 全局 |
|------|-------------|------|
| 审计队列 | 4 | 4 |
| 审计总文件 (源码) | ~200 | ~350 (含 test/doc) |
| 审计总 LOC | ~72,000 | ~86,000 |
| 致命问题 (P0) | 4 | 4 |
| 重要问题 (P1) | ~10 | ~8 |
| 改进项 (P2) | ~15 | ~8 |
| 发现总文件需修改 | - | ~80+ |

---

## 结论

UniQuant 处于**重构中期阵痛期**。架构方向正确（5 层 DAG、Protocol 接口、DI 容器、引擎工厂），但存在 V1→V2 过渡期的历史遗留问题大量堆积。核心问题不是架构设计，而是**清理执行不足**（根目录散落、废弃代码存活、`pyproject.toml` 未同步）。

**Sprint 1 可在 30 分钟内处理 4 个致命问题**，清除后系统即可达到基本可用状态。
