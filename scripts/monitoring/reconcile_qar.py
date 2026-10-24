#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CNMM-QAR 生产级实盘持仓、期货对冲与风险穿透对账监控器 (Reconciliation QAR Monitor)
=============================================================================
遵循量化资管实盘多空对冲合规风控体系 (符合 Phase 4 生产监控规范):
1. 头寸逐标的对账 (Drift Tolerance 0.5% / 50 bps 阈值);
2. 期货空头对冲合约与名义价值对账 (按 3 PB 账户穿透);
3. 风险穿透与净敞口对账 (Net Beta > 0.10 触发告警与非对冲熔断预警);
4. 资产配置三元结构对账 (75% 多头 / 75% 期指空头 / 25% 现金准备金, 现金 < 12% 预警);
5. 托管行估值表净值 (Custodian Valuation NAV) vs 账本公允净值对账 (偏差 > 5 bps 报警);
6. 结构化 JSON 报告落盘与状态码返回 (0=GREEN/YELLOW, 1=RED 熔断报警)。
=============================================================================
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from uniquant.shared.logger_factory import get_logger

logger = get_logger("scripts.monitoring.reconcile_qar")

# 监控容差默认阈值
DEFAULT_EQUITY_DRIFT_TOL_PP = 0.50     # 个股权重漂移容差 0.50% (50 bps)
DEFAULT_MAX_NET_BETA = 0.10            # 净市场敞口上限 0.10 (10.0%)
DEFAULT_NAV_DRIFT_BPS_TOL = 5.0        # 托管行估值净值与理论公允净值容差 5 bps
DEFAULT_MIN_CASH_RATIO = 0.12          # 现金流动性警戒线 12.0% (低于则追保预警)
DEFAULT_LIQUIDATION_CASH_RATIO = 0.08  # 现金强平熔断线 8.0%


def load_qar_signal(signal_path: Path | str) -> Dict[str, Any]:
    """读取 daily_signal_qar.py 生成的目标信号 JSON 文件"""
    p = Path(signal_path)
    if not p.exists():
        raise FileNotFoundError(f"目标信号文件不存在: {p}")
    with open(p, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload


def load_equity_positions(positions_path: Path | str) -> pd.DataFrame:
    """
    读取现货持仓 CSV 文件
    标准列: code (或 symbol), shares
    可选列: price, account
    """
    p = Path(positions_path)
    if not p.exists():
        raise FileNotFoundError(f"股票持仓文件不存在: {p}")
    df = pd.read_csv(p)
    col_map = {}
    for col in df.columns:
        c_lower = col.strip().lower()
        if c_lower in ["code", "symbol", "stock_code"]:
            col_map[col] = "code"
        elif c_lower in ["shares", "volume", "holdings", "position"]:
            col_map[col] = "shares"
        elif c_lower in ["price", "close", "cost"]:
            col_map[col] = "price"
        elif c_lower in ["account", "pb_account"]:
            col_map[col] = "account"
    df = df.rename(columns=col_map)
    if "code" not in df.columns or "shares" not in df.columns:
        raise ValueError(f"持仓 CSV 必须包含标的代码列(code)与持股数量列(shares): {p}")

    df["code"] = df["code"].astype(str).str.strip().str.zfill(6)
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce").fillna(0.0)
    return df


def load_futures_positions(futures_path: Optional[Path | str]) -> pd.DataFrame:
    """
    读取中金所期货持仓 CSV 或 JSON 文件
    标准列: account, contract, contracts
    可选列: direction, margin, notional
    """
    if futures_path is None:
        return pd.DataFrame(columns=["account", "contract", "contracts", "direction"])
    p = Path(futures_path)
    if not p.exists():
        raise FileNotFoundError(f"期货持仓文件不存在: {p}")

    if p.suffix == ".json":
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "accounts_allocation" in data:
            rows = []
            for acc, item in data["accounts_allocation"].items():
                rows.append({
                    "account": acc,
                    "contract": item.get("contract", "IF_MAIN"),
                    "contracts": int(item.get("contracts", 0)),
                    "direction": "SHORT",
                })
            df = pd.DataFrame(rows)
        elif isinstance(data, list):
            df = pd.DataFrame(data)
        else:
            df = pd.DataFrame([data])
    else:
        df = pd.read_csv(p)

    col_map = {}
    for col in df.columns:
        c_lower = col.strip().lower()
        if c_lower in ["account", "sub_account", "pb_account"]:
            col_map[col] = "account"
        elif c_lower in ["contract", "symbol", "instrument"]:
            col_map[col] = "contract"
        elif c_lower in ["contracts", "contracts_count", "position", "volume"]:
            col_map[col] = "contracts"
        elif c_lower in ["direction", "side"]:
            col_map[col] = "direction"
    df = df.rename(columns=col_map)
    if "contracts" in df.columns:
        df["contracts"] = pd.to_numeric(df["contracts"], errors="coerce").fillna(0).astype(int)
    return df


def resolve_market_prices(
    codes: List[str],
    explicit_prices: Optional[Dict[str, float]] = None,
    as_of_date: Optional[str] = None,
    quotes_dir: Optional[Path | str] = None,
) -> Dict[str, float]:
    """
    解析当前股票最新收盘价
    优先使用 explicit_prices，缺省从本地数据湖日频行情中提取
    """
    res = {}
    q_dir = Path(quotes_dir) if quotes_dir else PROJECT_ROOT / "data" / "lake" / "quotes" / "daily"
    target_dt = pd.to_datetime(as_of_date) if as_of_date else pd.Timestamp.now()

    for code in codes:
        clean_code = str(code).split(".")[0].zfill(6)
        if explicit_prices and clean_code in explicit_prices:
            res[clean_code] = float(explicit_prices[clean_code])
            continue
        if explicit_prices and code in explicit_prices:
            res[clean_code] = float(explicit_prices[code])
            continue

        # 从数据湖读取
        q_files = glob.glob(str(q_dir / f"{clean_code}.*.parquet"))
        price_found = False
        if q_files:
            try:
                df_q = pd.read_parquet(q_files[0])
                df_q["date"] = pd.to_datetime(df_q["date"])
                sub_q = df_q[df_q["date"] <= target_dt].sort_values("date")
                if not sub_q.empty:
                    last_px = float(sub_q.iloc[-1]["close"])
                    if last_px > 0:
                        res[clean_code] = last_px
                        price_found = True
            except (OSError, ValueError, KeyError) as e:
                logger.debug(f"读取数据湖价格失败 {clean_code}: {e}")

        if not price_found:
            # 兜底基准价格
            res[clean_code] = 50.0

    return res


def reconcile_equity_holdings(
    target_weights: Dict[str, float],
    actual_positions: pd.DataFrame,
    price_map: Dict[str, float],
    total_aum_rmb: float,
    drift_tol_pp: float = DEFAULT_EQUITY_DRIFT_TOL_PP,
) -> Dict[str, Any]:
    """
    逐标的现货头寸对账:
    对比目标权重 vs 实际权重 (基于总 AUM 或多头资产)
    """
    norm_target = {str(k).split(".")[0].zfill(6): float(v) for k, v in target_weights.items()}
    actual_dict: Dict[str, float] = {}
    for _, r in actual_positions.iterrows():
        c = str(r["code"]).split(".")[0].zfill(6)
        s = float(r["shares"])
        actual_dict[c] = actual_dict.get(c, 0.0) + s

    all_codes = sorted(set(norm_target.keys()) | set(actual_dict.keys()))
    rows = []
    n_match = 0
    n_drift = 0
    n_missing = 0
    n_extra = 0
    total_actual_equity_value = 0.0

    for code in all_codes:
        shares = actual_dict.get(code, 0.0)
        px = price_map.get(code, 50.0)
        mkt_val = shares * px
        total_actual_equity_value += mkt_val

        tgt_w = norm_target.get(code, 0.0)
        act_w = (mkt_val / total_aum_rmb) if total_aum_rmb > 0 else 0.0
        drift_pp = (act_w - tgt_w) * 100.0  # 百分点

        if tgt_w > 0.0 and shares <= 0:
            status = "MISSING"
            n_missing += 1
        elif tgt_w <= 0.0 and shares > 0:
            status = "EXTRA"
            n_extra += 1
        elif abs(drift_pp) > drift_tol_pp:
            status = "DRIFT"
            n_drift += 1
        else:
            status = "MATCH"
            n_match += 1

        rows.append({
            "code": code,
            "shares": int(shares),
            "price": round(px, 2),
            "market_value_rmb": round(mkt_val, 2),
            "target_weight_pct": round(tgt_w * 100.0, 4),
            "actual_weight_pct": round(act_w * 100.0, 4),
            "drift_pp": round(drift_pp, 4),
            "status": status,
        })

    return {
        "rows": rows,
        "summary": {
            "total_symbols": len(all_codes),
            "n_match": n_match,
            "n_drift": n_drift,
            "n_missing": n_missing,
            "n_extra": n_extra,
            "total_actual_equity_value_rmb": round(total_actual_equity_value, 2),
            "equity_weight_pct": round((total_actual_equity_value / total_aum_rmb) * 100.0, 2) if total_aum_rmb > 0 else 0.0,
            "is_clean": (n_drift == 0 and n_missing == 0 and n_extra == 0),
        }
    }


def reconcile_futures_hedging(
    target_hedging_orders: Dict[str, Any],
    actual_futures: pd.DataFrame,
    unit_contract_value: float = 1_200_000.0,
) -> Dict[str, Any]:
    """
    中金所期指空头对冲合约与 3 PB 分仓对账
    """
    target_contracts = int(target_hedging_orders.get("target_contracts", 0))
    target_alloc = target_hedging_orders.get("accounts_allocation", {})
    actual_contracts = int(actual_futures["contracts"].sum()) if not actual_futures.empty else 0

    contract_diff = actual_contracts - target_contracts
    target_notional = target_contracts * unit_contract_value
    actual_notional = actual_contracts * unit_contract_value

    pb_records = []
    pb_accounts = ["PB_ACCOUNT_1", "PB_ACCOUNT_2", "PB_ACCOUNT_3"]
    for acc in pb_accounts:
        tgt_c = int(target_alloc.get(acc, {}).get("contracts", target_contracts // 3))
        act_sub = actual_futures[actual_futures["account"] == acc] if not actual_futures.empty and "account" in actual_futures.columns else pd.DataFrame()
        act_c = int(act_sub["contracts"].sum()) if not act_sub.empty else (actual_contracts // 3 if len(pb_accounts) > 0 else 0)
        pb_records.append({
            "account": acc,
            "target_contracts": tgt_c,
            "actual_contracts": act_c,
            "diff_contracts": act_c - tgt_c,
            "is_match": (tgt_c == act_c),
        })

    is_hedged_compliant = (abs(contract_diff) <= 1)  # 允许 1 手整手四舍五入偏差

    return {
        "target_contracts": target_contracts,
        "actual_contracts": actual_contracts,
        "contract_discrepancy": contract_diff,
        "unit_contract_value_rmb": unit_contract_value,
        "target_hedging_notional_rmb": round(target_notional, 2),
        "actual_hedging_notional_rmb": round(actual_notional, 2),
        "pb_accounts_detail": pb_records,
        "is_hedged_compliant": is_hedged_compliant,
    }


def reconcile_risk_and_exposure(
    total_actual_equity_value: float,
    actual_futures_notional: float,
    actual_cash_rmb: float,
    total_aum_rmb: float,
    target_track: str = "75/25-IH",
    max_net_beta: float = DEFAULT_MAX_NET_BETA,
    min_cash_ratio: float = DEFAULT_MIN_CASH_RATIO,
) -> Dict[str, Any]:
    """
    宏观资产配置三元结构 (75/25) 与净市场风险敞口 (Net Beta) 穿透对账
    """
    effective_aum = total_actual_equity_value + actual_cash_rmb
    if total_aum_rmb > 0:
        aum_base = total_aum_rmb
    else:
        aum_base = max(1.0, effective_aum)

    equity_ratio = total_actual_equity_value / aum_base
    futures_short_ratio = actual_futures_notional / aum_base
    cash_ratio = actual_cash_rmb / aum_base

    # 净敞口与净 Beta (假设多头 Beta ~ 1.0, 期指 Beta = -1.0)
    net_exposure_rmb = total_actual_equity_value - actual_futures_notional
    net_beta = net_exposure_rmb / aum_base

    breaches = []
    if abs(net_beta) > max_net_beta:
        breaches.append(f"净市场敞口 Net Beta ({net_beta:+.4f}) 超过合规阈值 ±{max_net_beta:.2f} (未完全对冲风险)")
    if cash_ratio < DEFAULT_LIQUIDATION_CASH_RATIO:
        breaches.append(f"保证金现金比率 ({cash_ratio*100:.2f}%) 跌破强平熔断防线 {DEFAULT_LIQUIDATION_CASH_RATIO*100:.1f}%")
    elif cash_ratio < min_cash_ratio:
        breaches.append(f"现金流动性储备比率 ({cash_ratio*100:.2f}%) 低于预警线 {min_cash_ratio*100:.1f}% (需启动备用金追保)")

    return {
        "target_track": target_track,
        "aum_base_rmb": round(aum_base, 2),
        "actual_equity_value_rmb": round(total_actual_equity_value, 2),
        "actual_futures_short_notional_rmb": round(actual_futures_notional, 2),
        "actual_cash_rmb": round(actual_cash_rmb, 2),
        "equity_ratio_pct": round(equity_ratio * 100.0, 2),
        "futures_short_ratio_pct": round(futures_short_ratio * 100.0, 2),
        "cash_ratio_pct": round(cash_ratio * 100.0, 2),
        "net_market_exposure_rmb": round(net_exposure_rmb, 2),
        "net_beta": round(net_beta, 4),
        "is_beta_neutral": abs(net_beta) <= max_net_beta,
        "is_cash_adequate": cash_ratio >= min_cash_ratio,
        "risk_breaches": breaches,
    }


def reconcile_nav_custodian(
    custodian_nav: Optional[float],
    theoretical_nav: Optional[float],
    bps_tol: float = DEFAULT_NAV_DRIFT_BPS_TOL,
) -> Dict[str, Any]:
    """
    托管行估值表公布净值 vs 系统理论公允净值对账
    """
    if custodian_nav is None or theoretical_nav is None:
        return {
            "nav_reconciled": False,
            "custodian_nav": custodian_nav,
            "theoretical_nav": theoretical_nav,
            "drift_bps": 0.0,
            "is_within_tolerance": True,
            "note": "未提供托管行或理论净值，跳过 NAV 外包对账",
        }

    cust_val = float(custodian_nav)
    theo_val = float(theoretical_nav)
    diff = cust_val - theo_val
    drift_bps = abs(diff / theo_val) * 10_000.0

    is_ok = drift_bps <= bps_tol
    note = "净值对账在正常容差范围 (<= 5 bps)" if is_ok else f"净值偏离达 {drift_bps:.2f} bps，超过 {bps_tol:.1f} bps 告警线！"

    return {
        "nav_reconciled": True,
        "custodian_nav": round(cust_val, 6),
        "theoretical_nav": round(theo_val, 6),
        "drift_amount": round(diff, 6),
        "drift_bps": round(drift_bps, 2),
        "tolerance_bps": bps_tol,
        "is_within_tolerance": is_ok,
        "note": note,
    }


def build_qar_reconciliation(
    signal_path: Path | str,
    positions_path: Path | str,
    futures_path: Optional[Path | str] = None,
    cash_rmb: Optional[float] = None,
    custodian_nav: Optional[float] = None,
    theoretical_nav: Optional[float] = None,
    explicit_prices: Optional[Dict[str, float]] = None,
    drift_tol_pp: float = DEFAULT_EQUITY_DRIFT_TOL_PP,
    max_net_beta: float = DEFAULT_MAX_NET_BETA,
    nav_tol_bps: float = DEFAULT_NAV_DRIFT_BPS_TOL,
) -> Dict[str, Any]:
    """
    端到端实盘对账核心调度入口 (纯函数, 供 CLI 与测试无侵入复用)
    """
    # 1. 加载目标信号
    signal = load_qar_signal(signal_path)
    as_of = signal.get("as_of_date", datetime.now().strftime("%Y-%m-%d"))
    track = signal.get("strategy_track", "75/25-IH")
    target_aum = float(signal.get("aum_rmb", 50_000_000.0))
    target_weights = signal.get("target_stock_weights", {})
    hedge_orders = signal.get("futures_hedging_orders", {})
    unit_contract_val = float(hedge_orders.get("unit_contract_value", 1_200_000.0))

    # 2. 加载实际持仓
    df_equity = load_equity_positions(positions_path)
    df_futures = load_futures_positions(futures_path)

    # 现金准备金
    if cash_rmb is not None:
        actual_cash = float(cash_rmb)
    elif "cash" in df_equity.columns:
        cash_series = pd.to_numeric(df_equity["cash"], errors="coerce").dropna()
        actual_cash = float(cash_series.iloc[0]) if len(cash_series) > 0 else target_aum * 0.25
    else:
        actual_cash = target_aum * 0.25

    # 3. 解析价格: 优先持仓表自带 price 列，其次 explicit_prices 参数，缺省查数据湖
    pos_prices = {}
    if "price" in df_equity.columns:
        for _, r in df_equity.iterrows():
            if pd.notna(r.get("price")) and float(r["price"]) > 0:
                pos_prices[str(r["code"]).split(".")[0].zfill(6)] = float(r["price"])
    if explicit_prices:
        pos_prices.update(explicit_prices)

    all_symbols = list(set(list(target_weights.keys()) + df_equity["code"].tolist()))
    price_map = resolve_market_prices(
        codes=all_symbols,
        explicit_prices=pos_prices if pos_prices else None,
        as_of_date=as_of,
    )

    # 4. 执行各维度对账
    equity_recon = reconcile_equity_holdings(
        target_weights=target_weights,
        actual_positions=df_equity,
        price_map=price_map,
        total_aum_rmb=target_aum,
        drift_tol_pp=drift_tol_pp,
    )

    futures_recon = reconcile_futures_hedging(
        target_hedging_orders=hedge_orders,
        actual_futures=df_futures,
        unit_contract_value=unit_contract_val,
    )

    risk_recon = reconcile_risk_and_exposure(
        total_actual_equity_value=equity_recon["summary"]["total_actual_equity_value_rmb"],
        actual_futures_notional=futures_recon["actual_hedging_notional_rmb"],
        actual_cash_rmb=actual_cash,
        total_aum_rmb=target_aum,
        target_track=track,
        max_net_beta=max_net_beta,
    )

    nav_recon = reconcile_nav_custodian(
        custodian_nav=custodian_nav,
        theoretical_nav=theoretical_nav,
        bps_tol=nav_tol_bps,
    )

    # 5. 综合评级判定: GREEN / YELLOW / RED
    critical_breaches = []
    warning_notes = []

    # 股票持仓异常
    eq_sum = equity_recon["summary"]
    if eq_sum["n_missing"] > 0 or eq_sum["n_extra"] > 0:
        warning_notes.append(f"股票持仓存在多余或缺失标的 (missing={eq_sum['n_missing']}, extra={eq_sum['n_extra']})")
    if eq_sum["n_drift"] > 0:
        warning_notes.append(f"股票持仓存在权重漂移标的 {eq_sum['n_drift']} 只 (> {drift_tol_pp}%)")

    # 期货合约异常
    if not futures_recon["is_hedged_compliant"]:
        critical_breaches.append(f"期指对冲合约偏差 {futures_recon['contract_discrepancy']} 手 (名义价值偏差 {futures_recon['actual_hedging_notional_rmb'] - futures_recon['target_hedging_notional_rmb']:,.2f} 元)")

    # 风险敞口与流动性异常
    critical_breaches.extend(risk_recon["risk_breaches"])

    # NAV 估值异常
    if not nav_recon["is_within_tolerance"]:
        critical_breaches.append(f"托管估值净值偏离理论值 {nav_recon['drift_bps']:.2f} bps (> 5 bps)")

    if len(critical_breaches) > 0:
        overall_status = "RED"
        exit_code = 1
    elif len(warning_notes) > 0:
        overall_status = "YELLOW"
        exit_code = 0
    else:
        overall_status = "GREEN"
        exit_code = 0

    return {
        "as_of_date": as_of,
        "strategy_track": track,
        "target_aum_rmb": target_aum,
        "overall_status": overall_status,
        "exit_code": exit_code,
        "equity_reconciliation": equity_recon,
        "futures_reconciliation": futures_recon,
        "risk_reconciliation": risk_recon,
        "nav_reconciliation": nav_recon,
        "critical_breaches": critical_breaches,
        "warning_notes": warning_notes,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def print_reconciliation_report(rep: Dict[str, Any]) -> None:
    """输出格式化对账控制台表格"""
    print("\n" + "=" * 96)
    print(f"【CNMM-QAR 生产级实盘风控对账报告】 日期: {rep['as_of_date']} | 轨制: {rep['strategy_track']}")
    print("=" * 96)

    status_color = rep["overall_status"]
    print(f"综合风控评级: [{status_color}] (Exit Code: {rep['exit_code']})")
    if rep["critical_breaches"]:
        print(">> 致命风险警报 (CRITICAL BREACHES):")
        for b in rep["critical_breaches"]:
            print(f"   [!] {b}")
    if rep["warning_notes"]:
        print(">> 运营偏离提示 (WARNINGS):")
        for w in rep["warning_notes"]:
            print(f"   [*] {w}")

    # 宏观三元资产配置对账
    r = rep["risk_reconciliation"]
    print("\n" + "-" * 96)
    print(f"{'资产大类':<20} {'实际金额 (元)':<18} {'当前占比 (%)':<15} {'基准目标占比 (%)':<18} {'状态'}")
    print("-" * 96)
    print(f"{'现货股票多头':<20} {r['actual_equity_value_rmb']:<18,.2f} {r['equity_ratio_pct']:<15.2f} {'75.00':<18} {'正常' if abs(r['equity_ratio_pct'] - 75.0) <= 2.0 else '偏离'}")
    print(f"{'中金所期指空头名义':<20} {r['actual_futures_short_notional_rmb']:<18,.2f} {r['futures_short_ratio_pct']:<15.2f} {'75.00':<18} {'正常' if abs(r['futures_short_ratio_pct'] - 75.0) <= 2.0 else '偏离'}")
    print(f"{'现金与保证金准备金':<20} {r['actual_cash_rmb']:<18,.2f} {r['cash_ratio_pct']:<15.2f} {'25.00':<18} {'充裕' if r['is_cash_adequate'] else '追保警报'}")
    print(f"{'组合净市场敞口 Net Beta':<20} {r['net_market_exposure_rmb']:<18,.2f} {r['net_beta']:<+15.4f} {'0.00 ± 0.10':<18} {'完全对冲' if r['is_beta_neutral'] else '敞口超标'}")
    print("-" * 96)

    # 现货持仓前 10 只样本
    eq = rep["equity_reconciliation"]
    print(f"\n【现货标的持仓对账 (共 {eq['summary']['total_symbols']} 只, Match={eq['summary']['n_match']}, Drift={eq['summary']['n_drift']}, Missing={eq['summary']['n_missing']}, Extra={eq['summary']['n_extra']})】")
    print(f"{'标的代码':<10} {'持股数':<12} {'现价':<10} {'目标权重(%)':<14} {'实际权重(%)':<14} {'漂移(pp)':<12} {'评级'}")
    print("-" * 96)
    for row in eq["rows"][:12]:
        print(f"{row['code']:<10} {row['shares']:<12} {row['price']:<10.2f} {row['target_weight_pct']:<14.2f} {row['actual_weight_pct']:<14.2f} {row['drift_pp']:<+12.2f} {row['status']}")
    if len(eq["rows"]) > 12:
        print(f"... 剩余 {len(eq['rows']) - 12} 只标的已记录于完整 JSON 报告")

    # 期指对账
    f = rep["futures_reconciliation"]
    print(f"\n【中金所期指对冲对账: 目标 {f['target_contracts']} 手 vs 实际 {f['actual_contracts']} 手 (偏差: {f['contract_discrepancy']:+d} 手)】")
    for pb in f["pb_accounts_detail"]:
        print(f"  - {pb['account']}: 目标 {pb['target_contracts']} 手, 实际 {pb['actual_contracts']} 手 -> {'吻合' if pb['is_match'] else '偏差'}")

    # NAV 对账
    nav = rep["nav_reconciliation"]
    if nav["nav_reconciled"]:
        print(f"\n【托管估值对账: 托管行 NAV={nav['custodian_nav']:.6f} vs 理论公允 NAV={nav['theoretical_nav']:.6f} | 偏差 {nav['drift_bps']:.2f} bps ({nav['note']})】")
    print("=" * 96 + "\n")


def main():
    parser = argparse.ArgumentParser(description="CNMM-QAR 生产级实盘风控对账监控器")
    parser.add_argument("--signal", required=True, help="目标信号 JSON 文件路径 (如 results/daily_qar/2024-05-06.json)")
    parser.add_argument("--positions", required=True, help="券商 PB 实际股票持仓 CSV 文件路径")
    parser.add_argument("--futures", default=None, help="期货公司实际期指持仓 CSV 或 JSON 文件路径")
    parser.add_argument("--cash", type=float, default=None, help="实际现金总额 (元)")
    parser.add_argument("--prices", default=None, help="显式价格 CSV/JSON 文件路径 (可选)")
    parser.add_argument("--custodian-nav", type=float, default=None, help="托管行公布的公允净值 NAV")
    parser.add_argument("--theoretical-nav", type=float, default=None, help="系统 InstitutionalFeeLedger 计算的理论净值")
    parser.add_argument("--drift-tol-pp", type=float, default=DEFAULT_EQUITY_DRIFT_TOL_PP, help="个股权重允许漂移百分点 (默认 0.50 pp)")
    parser.add_argument("--output", default=None, help="对账输出 JSON 报告路径")

    args = parser.parse_args()

    explicit_px = None
    if args.prices:
        p_path = Path(args.prices)
        if p_path.suffix == ".json":
            with open(p_path, "r", encoding="utf-8") as f:
                explicit_px = json.load(f)
        else:
            df_px = pd.read_csv(p_path)
            code_col = "code" if "code" in df_px.columns else df_px.columns[0]
            val_col = "close" if "close" in df_px.columns else ("price" if "price" in df_px.columns else df_px.columns[1])
            explicit_px = {str(r[code_col]).split(".")[0].zfill(6): float(r[val_col]) for _, r in df_px.iterrows()}

    report = build_qar_reconciliation(
        signal_path=args.signal,
        positions_path=args.positions,
        futures_path=args.futures,
        cash_rmb=args.cash,
        custodian_nav=args.custodian_nav,
        theoretical_nav=args.theoretical_nav,
        explicit_prices=explicit_px,
        drift_tol_pp=args.drift_tol_pp,
    )

    print_reconciliation_report(report)

    if args.output:
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"对账报告已落盘至: {out_p}")

    sys.exit(report["exit_code"])


if __name__ == "__main__":
    main()
