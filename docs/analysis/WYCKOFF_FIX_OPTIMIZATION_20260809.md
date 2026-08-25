# Wyckoff 修复与优化方案 — 基于方法论多轮对抗判定 (2026-08-09)

> 依据：`WYCKOFF_METHODOLOGY_ADVERSARY_20260809.md` 判定（B-：框架成立 + alpha 轴错位 + 落地冲突）
> 核心结论回顾：真信号 = `RS=leader ∧ phase=DISTRIBUTION`（三窗 +5.85/+4.09/+9.07，MWU p<0.01）；spring 证伪；结构分离弃用；markdown=唯一稳定风控。
> 目标：把判定转化为可落地的 P0/P1/P2 修复，全部 TDD + 双窗(→三窗)重验 + 0 ruff，遵循 A股铁律守卫。

---

## 一、修复总原则

1. **不逆向 A股铁律**：markdown 仍禁多；本轮全部改动**不开空**（A股研究平台无空位机制）。
2. **新信号必须 config 门控**（如 `wyckoff.distribution_leader_enabled`），沿用 `accumulation_downgrade` 的模式，可一键 A/B 回退。
3. **只改 direction 的派生出入口，不改相位判定**（相位仍归 Layer0 叙事，方向由独立 gate 合成）。
4. **验证从严**：新增任何信号均需 三窗 MWU + 中位 + 超额>0 占比 三口径，杜绝 W2 假显著重演。

---

## 二、P0 — alpha 轴修正：`leader∧distribution` 做多落地（最优先级）

### 问题根因（engine.py）
| 位置 | 现状 | 问题 |
|---|---|---|
| `_step5_trading_plan` 签名 (line 1405) | 无 `relative_strength` 入参 | 无法在计划层读取 RS |
| `_step5` DISTRIBUTION 分支 (line 1421-1422) | 硬编码 `direction="空仓观望"` | 唯一真信号被空仓吃掉（W3: 321 只全空仓） |
| `_analyze_single` (line 441 vs 459) | step5 在 RS 计算**之前**执行 | 顺序错位：计划用的信息晚于可用 |

### 修复设计
1. **RS 计算前置**：把 `rs_classify` 块移到 `_step5_trading_plan` 调用之前（line 441 之前），step5 增加可选参数 `relative_strength: Optional[str] = None`（回调前移不改变默认 None 语义）。
2. **新增 config**：`config/config.yaml` → `wyckoff.distribution_leader_enabled: true`；`WyckoffEngine.__init__` 读取存 `self._distribution_leader_enabled`（与 `_accumulation_downgrade` 同模式）。
3. **DISTRIBUTION 分支改造**：
   ```python
   elif step1.phase == WyckoffPhase.DISTRIBUTION:
       if (self._distribution_leader_enabled
           and relative_strength == "leader"):
           # 实证: leader∧distribution 做多方向三窗显著正 (+6.34%)
           # 仅 leader 在派发期强于大盘才放开做多; 其余仍禁开仓
           if confidence.level in ("A", "B", "B+") or rr.rr_ratio >= 1.5:
               direction = "轻仓试探"
           else:
               direction = "观察等待"
       else:
           direction = "空仓观望"
   ```
   - **不做多到满仓**：最高只给"轻仓试探"（分布期 + leader 双重条件，控制尾部风险）
   - **不引入 spring**：判定证明 spring 消解 alpha，distribution 分支不接受 spring 触发
   - 保留 `step35/RR/limit` 等后置 gate 不变
4. **后置 gate 不动**：markdown、涨跌停、假突破、accumulation 降档逻辑保持原样，与新增分支正交。

### 测试（tests/classic_wyckoff/test_distribution_leader.py，预期 ~10 用例）
- 构造 `phase=DISTRIBUTION + relative_strength=leader + conf∈{A,B} + rr>=1.5` → direction="轻仓试探"
- `phase=DISTRIBUTION + leader + conf=D/rr<1.5` → 观察等待
- `phase=DISTRIBUTION + non-leader` → 空仓观望（铁律类回归）
- `phase=DISTRIBUTION + leader` 但 flag=false → 空仓观望（A/B 门控）
- `phase=MARKDOWN + leader` → 空仓观望（markdown 禁多优先级更高）
- step5 无 RS 入参（None）向后兼容 → 原行为不变
- `_analyze_single` 顺序：RS 在 step5 前计算（mock rs_classify 断言被先调用）

### 验证（实证闭环）
- 跑 `wyckoff_full_scan.py --as-of` W3 复扫（flag on）：leader∧dist 池应出现"轻仓试探/观察等待"，不再全空仓
- 三窗超额重验：`validate_ranking.py` 扩展 E4 = distribution×leader 三窗 MWU

---

## 三、P1 — 修补被证伪的组件

### P1-1 spring 语义修正（降级观察，不触发做多）
- **现状**：UNKNOWN 分支 spring+强置信 仍可"轻仓试探"（line 1501-1511）
- **判定**：spring 双窗超额为负，leader×spring 更差（−5.57/−7.50）→ spring 无独立 alpha
- **改法**：config `wyckoff.spring_tentative_enabled: true`（默认 ON 但保留）；在最终 direction=""轻仓试探"" 时若 spring 是唯一触发器 → 降为"观察等待"。或者更保守：仅在 `relative_strength=="leader"` 时才允许 spring 触发轻仓。
- **测试**：spring 触发矩阵（leader/non-leader × conf A/D × rr）回归

### P1-2 结构分定性调整（高分=劣势标记 → 数据化，不再升置信）
- **现状**：`_apply_structural_adjustment` 结构分≥70 升 1 级置信
- **判定**：leader 内高分反差（8.00 vs 5.07），IC 三窗符号翻转 → 结构分离弃用为排序器
- **改法**：新 config `wyckoff.structural_adjust_enabled: false`（默认关闭升/降置信通路），`_apply_structural_adjustment` 保留计算但 default 不再影响 confidence（改由调用方控制）。**不删除** —— 结构分仍写入 report 供存档/复盘。
- **测试**：升级 matrix 断言 flag=false 时置信不变（结构性回退）

### P1-3 置信度与 spring/leader 的"假增强"解耦
- 断裂点：`_calc_confidence` 产出 "B+" 而 enum 仅 A/B/C/D（已知不一致）——修复 enum 对齐或产出归一化，从源头避免 B+ 被从 confidence 判断中误判
- **测试**：置信归一化幂等回归

---

## 四、P2 — 工程健康

| 项 | 目标 | 说明 |
|---|---|---|
| 移除/补活 `_detect_sos` 死桩 | 死桩处理 | line 845-847 恒 None；改为内联调 SOS 检测或删桩 + 引用清理 |
| 硬编码 → config | ~30 处 magic | pnf box/BC-SC 权重/markdown 阈值/RR 2.5/1.5/BASE 5.0/WSS blend 0.3/0.7 逐步入 `config.wyckoff.calibration`，TDD 逐项 |
| 研究管线(ShARPE 2.02) vs 生产对齐 | 最大未兑现价值 | 将 leader×distribution 信号同步到 research run_batch 输出列 |
| 验证工具升级 | validate_ranking.py E4 | 新增 distribution×leader 三窗检验 + MWU/中位数/占比 三口径输出 |

---

## 五、实施顺序与验收

| 阶段 | 任务 | 验收标准 |
|---|---|---|
| P0 (本周) | distribution×leader 做多落地 | 10+ 新测试通过；三窗 fwd 复扫 leader∧dist 不再全空仓；两窗回归无破坏 |
| P1 (下周) | spring 语义修正 + 结构分置信通路关闭 | flag 门控回归；`_apply_structural_adjustment` 前后置信不变断言 |
| P2 (机动) | 死桩/硬编码/工具升级 | ruff 0；validate_ranking E4 输出三窗 |

**全部阶段**：TDD（RED→GREEN）、ruff 0、classic_wyckoff 全套回归（当前 163 passed/1 skipped）、不破坏 accumulation 降档/假突破/涨跌停既有 gate。

---

## 六、风险与边界

1. **leader 高换手（15.9% 重合）**：P0 仅作"轻仓试探"而非满仓，换手风险已内置缓冲；若换手成为问题，可加"leader 需连续 N 期"确认。
2. **distribution 与经典理论冲突**：本方案明确"phase 不作方向"立场，distribution 只因其内含 leader 信号才开仓——不把 distribution 本身当多头信号。
3. **index_df 缺失场景**：RS=None 时不触发新分支（沿用空仓），服务层 index 透传已在上次 W1 完成，daily screen 不受影响。
4. **不引入做空**：全部改动为多头方向，符合 A股铁律与研究平台定位。