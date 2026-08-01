"""
UniQuant 端到端研报流水线示例
===============================

演示完整链路: ServiceContainer 初始化 → 数据获取 → 引擎分析
→ 信号收集 → 信号仲裁 → 回测 → 结果分析

运行:
    python docs/examples/end_to_end_pipeline.py

依赖:
    pip install -e ".[all]"
"""

import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("pipeline_demo")


def run_pipeline(symbol: str = "000001.SZ", name: str = "平安银行"):
    from uniquant.services.service_container import ServiceContainer

    log.info("Step 0: 初始化 ServiceContainer...")
    t0 = time.time()
    container = ServiceContainer()
    container.initialize()
    log.info(f"  ServiceContainer 就绪 ({time.time()-t0:.2f}s)")

    analysis_svc = container.get("analysis_service")
    data_svc = container.get("data_service")

    # ------------------------------------------------------------------
    # Step 1: 获取数据
    # ------------------------------------------------------------------
    log.info(f"Step 1: 获取 {symbol} ({name}) 数据...")
    t1 = time.time()
    data_pack = data_svc.fetch_for_brain(symbol)
    stock_df = data_pack.get("stock")
    if stock_df is not None:
        log.info(f"  K 线行数: {len(stock_df):,} | 列: {list(stock_df.columns)}")
        log.info(f"  日期范围: {stock_df.index[0]} ~ {stock_df.index[-1]}")
    else:
        log.warning("  ⚠ 无股票数据（可能需先运行数据下载脚本）")
    log.info(f"  Data fetch: {time.time()-t1:.2f}s")

    # ------------------------------------------------------------------
    # Step 2: 运行分析引擎
    # ------------------------------------------------------------------
    log.info(f"Step 2: 运行 {symbol} 全引擎分析...")
    t2 = time.time()
    result = analysis_svc.run_ticker_analysis(symbol, trace_id="demo_001")
    log.info(f"  Analysis: {time.time()-t2:.2f}s")

    if not result.success:
        log.error(f"  分析失败: {result.error}")
        return

    decision = result.decision
    data_pack = result.data_pack

    log.info(f"  决策: {decision.get('action', 'N/A')} | "
             f"置信度: {decision.get('confidence', 'N/A')}")

    for engine, status_key in [
        ("regime", "regime"), ("lppl", "lppl_phase"),
        ("czsc", "czsc_signal"), ("wyckoff", "wyckoff_phase"),
        ("ntf", "ntf_signal"),
    ]:
        val = (getattr(data_pack, engine, "N/A") if hasattr(data_pack, engine)
               else data_pack.get(status_key, "N/A"))
        log.info(f"  {engine:8s}: {val}")

    # ------------------------------------------------------------------
    # Step 3: 信号收集与仲裁
    # ------------------------------------------------------------------
    log.info("Step 3: 收集并仲裁 TradingSignal...")
    from uniquant.signal.adapters import TradingSignalCollector, create_default_registry

    collector = TradingSignalCollector(create_default_registry())
    data_pack_dict = data_pack.to_dict() if hasattr(data_pack, 'to_dict') else data_pack
    signals = collector.collect(data_pack_dict)
    log.info(f"  原始信号: {len(signals)} 条")

    from uniquant.signal.arbitrator import SignalArbitrator

    arbitrator = SignalArbitrator()
    arbitrated = arbitrator.arbitrate(signals)

    for s in arbitrated:
        log.info(f"  → {s.action:5s} {s.symbol} @ {s.price:.2f} "
                 f"(conf={s.confidence:.2f}, reason={s.reason})")

    # ------------------------------------------------------------------
    # Step 4: 回测
    # ------------------------------------------------------------------
    log.info("Step 4: 运行 UnifiedBacktestEngine 回测...")
    t4 = time.time()
    from uniquant.hands.backtest.unified_engine import UnifiedBacktestEngine

    backtest_engine = UnifiedBacktestEngine(initial_capital=100_000.0)
    bt_result = backtest_engine.run(
        df=stock_df, signals=arbitrated, symbol=symbol, name=name,
    )
    log.info(f"  Backtest: {time.time()-t4:.2f}s")

    log.info(f"  总收益率:      {bt_result.total_return:>+8.2%}")
    log.info(f"  夏普比率:      {bt_result.sharpe:>8.2f}")
    log.info(f"  最大回撤:      {bt_result.max_drawdown:>8.2%}")
    log.info(f"  交易次数:      {bt_result.total_trades:>8}")
    log.info(f"  胜率:          {bt_result.win_rate:>8.2%}" if hasattr(bt_result, "win_rate") else "")
    log.info(f"  最终资金:      ¥{bt_result.final_cash:>10,.2f}")

    # ------------------------------------------------------------------
    # Step 5: ResearchPipeline 一键运行
    # ------------------------------------------------------------------
    log.info("Step 5: ResearchPipeline 全链路一键运行...")
    t5 = time.time()
    from uniquant.services.research_pipeline import UnifiedResearchPipeline as ResearchPipeline
    from uniquant.signal.arbitrator import SignalArbitrator

    pipeline = ResearchPipeline(
        analysis_service=analysis_svc,
        backtest_engine=backtest_engine,
        signal_collector=collector,
        arbitrator=SignalArbitrator(),
    )
    pipeline_result = pipeline.run(symbol=symbol, name=name)
    log.info(f"  Pipeline: {time.time()-t5:.2f}s")
    log.info(f"  成功: {pipeline_result.success}")
    if pipeline_result.backtest:
        log.info(f"  回测交易: {len(pipeline_result.backtest.trades)} 笔")

    log.info("=" * 50)
    log.info("端到端流水线完成 ✅")


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "000001.SZ"
    name = sys.argv[2] if len(sys.argv) > 2 else "平安银行"
    run_pipeline(symbol, name)
