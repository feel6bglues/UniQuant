# 04 信号与执行域 (FULL_AUDIT 20260922)

> 页眉：FULL_AUDIT 专用，非 playbook | SHA `ddd678a` | 批 B1=S3；批 B2=S1,S2（+S4/S5）；批 B4=S6,S7

## 结论（3 句内）

**S3 冲突 C4 成立**（P0-09 假 FIXED）；**S1 七项 P0-1…7 密封链全部在位**（config+源码+测试三源）；**S2 AlphaScore `0<score<0.3` 与 arbitrator 卖优先/`DEFAULT_MAX=0.0` 全在位**。P0-08/P0-01/8 adapters/`factor_gate: block` 与 AGENTS 一致。全库 0 bare `except:`，src 宽 `except Exception:`=34。

## 证据（file:line @ ddd678a）

### S3 主判定（P0）

| 宣称 | 位置 | 实测 |
|------|------|------|
| AGENTS P0-09 FIXED 4 bare narrowed | `AGENTS.md:1047` 点名 engine.py:251,261,1575,1591 | **行号不存在**；当前宽 except 于 255,266,279,289,2153 |
| live_map bug#4 FIXED | `I_live_system_map.md:221` 点名 243,256,1521,1565 | 同样漂移；仍 5×`except Exception:` |
| 实测清单 | `rg except Exception engine.py` | 255,266,279,289（init/config 读取，带 `logger.warning exc_info`）+ 2153（confidence_gate 默认 0.40 回退） |
| image_engine | 159, 247 | `except Exception as e` ×2 |
| 其余 engine 宽 except | 400,456,475,493,633,2221,2237 | 已是窄元组（ValueError/TypeError/KeyError…） |
| research_pipeline P0-08 | AGENTS FIXED @239 | 当前 244=`except (OSError, PermissionError, json.JSONDecodeError)` ✓ **与 FIXED 一致** |
| bare `except:` 全 src | — | **0** |

**裁决（C4）**：P0-08 **维持 FIXED**；P0-09「4 处已窄化」**不成立或曾回退/重写**——5 处宽 `except Exception:` 仍在（多为 fail-open 配置读取，与「窄化为 typed tuple」不同）。风险：配置读取 fail-open 可接受，但文档宣称「FIXED」**误导**；且行号锚点全失效。

### S1 P0-1…7 密封勾选表（B2 收口）

| P0 | 项 | 在位? | 源码 file:line @ ddd678a | config | 测试 |
|:--:|----|:-----:|---------------------------|--------|------|
| 1 | direction 透传 | ✅ | `pack_writer.py:59` dict / `:140` RDP；`adapters.py:655-656` collector | — | `test_extract_from_report_*`, `test_*_pack_writer_writes_direction` |
| 2 | adapter direction gate | ✅ | `adapters.py:187` `_ENTRY_DIRECTIONS={"做多","买入","轻仓试探"}`；`:214-218` gate+置信；非入场→None | `direction_gate_enabled: true` (`config.yaml:508`) | `tests/signal/test_adapters.py`；`test_signal.py` |
| 3 | RDP 仅 wyckoff 键 | ✅ | `pack_writer.py:130-132`（注释 P0-3）；`:133-156` 仅 wyckoff P1 标注键 | — | `test_rd_pack_writer_writes_only_wyckoff_keys` |
| 4 | confidence_gate 0.40 | ✅ | `engine.py:2149-2152` `_scan_buy_confidence_gate` default 0.40；`:2206` `confidence >= gate` 才 BUY；回退 `:2153` wide except | `confidence_gate: 0.40` (`:509`) | `test_scan_signal_never_sells` 等 |
| 5 | structural_adjust 默认关 | ✅ | `engine.py:273-277` 默认 False；`:460-461` 仅 enabled 才调 `_apply_structural_adjustment` | `structural_adjust_enabled: false` (`:510`) | `test_structural_adjust_default_off`, `test_structural_adjust_off_keeps_base_confidence` |
| 6 | normalizer 方向抵销 | ✅ | `normalizer.py:115-125` `_DIRECTION_MAP` **6 项全 0**；`:132` `direction = map.get(...,0)` | — | —（映射字面锁定） |
| 7 | 恒不 SELL-as-entry | ✅ | `adapters.py:184` 文档串；`:218` 非入场/低置信→return None（不产 SELL）；WyckoffAdapter 无 SELL 分支 | — | `test_wyckoff_p0_direction.py::test_scan_signal_never_sells` |

**附属密封（非 7 项但同链）**：

- LIMIT_UP 守卫：`engine.py:1586`（V5 修复，在位）
- accumulation_downgrade：`engine.py:1654-1658` + config `:501 true`
- stoploss_guard 默认关：config `:518 false`
- `test_wyckoff_p0_direction.py` **9 tests 全列**：roundtrip_direction / from_dict_default_empty / extract×2 / dict_pack_writer / rd_pack_writer_only / structural_off×2 / never_sells

**config 实测快照**（`config/config.yaml`）：`direction_gate_enabled: true` / `confidence_gate: 0.40` / `structural_adjust_enabled: false` / `accumulation_downgrade: true` / `wss_enabled: true` / `use_research_data_pack: true` / `factor_gate: "block"` / `signal_arbitration: true`。

### S2 AlphaScore + Arbitrator（B2 收口）

| 项 | 在位? | file:line @ ddd678a | 测试 |
|----|:-----:|---------------------|------|
| P0-01 `0 < score < 0.3` | ✅ | `adapters.py:400` `elif 0 < score < 0.3:` → SELL；`score==0` 落 neither → 无 SELL | Alpha 相关 adapters 测试 |
| AlphaScore 注册 | ✅ | `adapters.py:497` `registry.register("alpha_score", ...)` | — |
| arbitrator 卖优先 | ✅ | 默认 `sell_priority: bool = True` (`arbitrator.py:81`)；规则1 `:197-204` SELL 集非空则选最高置信 SELL；`:337-352` Priority 2 同语义 | `tests/test_signal_arbitrator.py` (20), `tests/signal/test_arbitrator.py` (31) |
| 超时键 | ✅ | `DEFAULT_MAX_SIGNAL_AGE_SECONDS=0.0` (`:40`)；`>0` 才生效 (`:120`) → **默认禁用**（与 Known Gaps 一致） | 同上 |
| FORCE_EXIT SELL | ✅ | `:315-319` final SELL + `TradingSignal(FORCE_EXIT, conf=1.0)` | — |

⚠️ `tests/test_arbitrator.py` **不存在**；真实测试文件为 `tests/test_signal_arbitrator.py` + `tests/signal/test_arbitrator.py`（DoD 的「arbitrator 测试在位」满足，路径需按实测）。

### S4 Arbitrator max_age（P1，B2 顺带）

- `arbitrator.py:40` `DEFAULT_MAX_SIGNAL_AGE_SECONDS=0.0`（禁用）
- 卖优先测试在位（上表 S2）
- **状态：完成（一致）**

### S5 RDP / factor_gate（P1，B2 顺带）

| 项 | 实测 | file:line |
|----|------|-----------|
| `use_research_data_pack` | `true` | `config.yaml:484` |
| `factor_gate` | `"block"` | `config.yaml:472` |
| RDP 仅 wyckoff 键写入 | `pack_writer.py:130-132` | ✅ |
| gate_mode 消费 | `service_container.py:157` | ✅ |
| collector 展平 metadata | `research_pipeline.py:574-585` `collector_pack.update(raw_metadata)` — **metadata 全量进 collector**；P0-3 约束的是 **pack_writer 写入面**（wyckoff 路径只写 wyckoff 键），非 collector 读取面 | ⚠️ 边界：若他引擎写非 wyckoff metadata 仍会展平——与 P0-3 注释「禁全量 metadata 展平」字面有张力，见下 |

**S5 裁决备注（M 级）**：`pack_writer` Wyckoff 分支只注入 wyckoff 键 ✓；但 `research_pipeline:585` 仍将 **整个 metadata dict** update 进 collector_pack。P0-3 防的是「Wyckoff 报告 metadata 全量展平」；其他引擎（regime/risk/ntf）仍写 metadata（`pack_writer.py:106-127`）。是否违反 P0-3 取决于原意是「wyckoff 键白名单」还是「collector 仅 wyckoff」——**按 WBS 字面（pack_writer 展平面）判在位；全库白名单为开放项**。

### S6 适配器注册清单（P1，B4 完成）

`create_default_registry` **8/8**（`adapters.py:491-498`）：

| # | name | 类型 |
|---|------|------|
| 1 | lppl | LppLOutput |
| 2 | czsc | CZSCOutput |
| 3 | wyckoff | WyckoffOutput |
| 4 | fsm | FSM/Decision |
| 5 | regime | RegimeOutput |
| 6 | ntf | NtfOutput |
| 7 | alpha_score | AlphaOutput |
| 8 | ma_status | MA status |

- 与 `I_live_system_map`「8 adapters」**一致**；`signal/__init__.py` 导出全 8 类。
- 已知反转映射残留：normalizer `_DIRECTION_MAP` 6 项全 0（S1-P0-6）✓；无额外反转映射。

### S7 quality.py 死码复证（P2，B4 完成）

| 项 | 实测 |
|----|------|
| LOC | **297**（live_map 曾记 294） |
| ext_refs | ≈5（主要 `tests/test_signal.py`、`tests/test_e2e_integration_qa.py`） |
| 生产路径 SignalQuality 消费 | **0**（src 无调用点） |
| 判定 | **DEPRECATED 半死维持**（C3 叙事：在树、测试仍引用、生产不走） |

## 与历史对账

| 历史 | 状态 |
|------|------|
| P0-09 FIXED 4 处 | **冲突 C4 → 以源码为准：仍有 5 宽 except** |
| P0-08 FIXED | **一致** |
| P0-01 alpha 0.0 | **一致**（`0<score<0.3`） |
| P0-1…7 密封 | **7/7 在位**（B2 勾选表） |
| 8 adapters | **一致** |
| max_age 默认 0 | **一致** |
| sell_priority 默认开 | **一致** |
| factor_gate block / RDP on | **一致**（collector 全量 metadata 边界见 S5 备注） |

## 风险分级

| 级 | 项 |
|----|-----|
| **H** | C4：信号引擎异常处理宣称与现实不符（文档信任受损；宽 except 是否可接受需策略裁决） |
| M | 5 处 fail-open 配置读取缺类型化异常（噪音掩盖真错误） |
| L | 行号锚点全面漂移，历史 bug 表不可导航 |

## 建议动作

1. 修正 AGENTS/live_map P0-09 行：改为「N 处 except Exception（fail-open）+ 0 bare」或重开窄化任务 — DoD：rg 计数=文档（批准后）。
2. 窄化 2153 为 `(KeyError, TypeError, ValueError)` 级 — **需拟修改清单批准**（本审计不改码）。
3. 明确 research_pipeline collector metadata 白名单策略 — DoD：ADR 或 pack_writer 全引擎键审计（**留 B5**，非 B4 阻断）。
4. S1/S2/S4/S5/S6/S7 **已完成**；S 域 P1/P2 清零。

## 本批变更

B1+S3 / B2+S1,S2,S4,S5 / B4+S6,S7；仅 FULL_AUDIT 文档；**无源码变更**。
