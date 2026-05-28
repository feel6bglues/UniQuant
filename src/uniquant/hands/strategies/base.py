# Make backtrader an optional dependency
try:
    import backtrader as bt

    HAS_BACKTRADER = True
except ImportError:
    HAS_BACKTRADER = False
    bt = None

# Import internal modules
try:
    from risk.sizer import PositionSizer
except ImportError:
    # Fallback/Mock for standalone testing
    PositionSizer = None

from uniquant.shared.logger_factory import get_logger

logger = get_logger("Strategy")

# Export HAS_BACKTRADER for use in other modules
__all__ = ["BaseStrategy", "HAS_BACKTRADER", "bt"]

if HAS_BACKTRADER:

    class BaseStrategy(bt.Strategy):
        """
        Base Strategy Class for Alpha-Tactician Pro.
        Implements common functionality for logging, order management, and risk integration.
        """

        params = (
            ("verbose", True),
            ("risk_pct", 0.05),  # Risk per trade
            ("stop_atr_n", 2.0),  # ATR multiplier for stop loss
        )

        def __init__(self):
            self.sizer_engine = PositionSizer() if PositionSizer else None
            self.orders = {}  # Keep track of orders by ref
            self.dataclose = self.datas[0].close
            self.datahigh = self.datas[0].high
            self.datalow = self.datas[0].low

        def log(self, txt: str, dt=None):
            """Logging helper"""
            if self.params.verbose:
                dt = dt or self.datas[0].datetime.date(0)
                logger.info(f"[{dt.isoformat()}] {txt}")

        def notify_order(self, order):
            if order.status in [order.Submitted, order.Accepted]:
                # Buy/Sell order submitted/accepted to/by broker - Nothing to do
                return

            # Check if an order has been completed
            # Attention: broker could reject order if not enough cash
            if order.status in [order.Completed]:
                if order.isbuy():
                    self.log(
                        f"BUY EXECUTED, Price: {order.executed.price:.2f}, Cost: {order.executed.value:.2f}, Comm: {order.executed.comm:.2f}"
                    )
                elif order.issell():
                    self.log(
                        f"SELL EXECUTED, Price: {order.executed.price:.2f}, Cost: {order.executed.value:.2f}, Comm: {order.executed.comm:.2f}"
                    )

                self.bar_executed = len(self)

            elif order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.log(f"Order Canceled/Margin/Rejected: {order.status}")

            # Write down: no pending order
            if hasattr(order, "ref") and order.ref in self.orders:
                del self.orders[order.ref]

        def notify_trade(self, trade):
            if not trade.isclosed:
                return

            self.log(
                f"OPERATION PROFIT, GROSS {trade.pnl:.2f}, NET {trade.pnlcomm:.2f}"
            )

        def calculate_position_size(self, stop_price: float) -> int:
            """
            Calculate position size using Risk Engine.
            """
            if not self.sizer_engine:
                return 100  # Default fallback

            current_price = self.dataclose[0]

            # Calculate
            res = self.sizer_engine.calculate_shares(
                price=current_price,
                stop_loss=stop_price,
                market="CN",  # Assuming CN for now
                atr_stop=None,  # or pass ATR
            )

            return res.get("shares", 0)

        def start(self):
            self.log("Strategy Started")

        def stop(self):
            self.log("Strategy Stopped")

else:

    class BaseStrategy:
        """
        Mock BaseStrategy class when backtrader is not available.
        """

        def __init__(self):
            logger.warning(
                "Backtrader is not installed. Strategy functionality will be limited."
            )
            self.orders = {}

        def log(self, txt: str, dt=None):
            logger.info(f"[Mock] {txt}")

        def notify_order(self, order):
            """Mock method for backtrader compatibility"""
            # This method is intentionally empty
            # It's only implemented for backtrader API compatibility
            logger.debug(f"Mock notify_order called: {order}")

        def notify_trade(self, trade):
            """Mock method for backtrader compatibility"""
            # This method is intentionally empty
            # It's only implemented for backtrader API compatibility
            logger.debug(f"Mock notify_trade called: {trade}")

        def calculate_position_size(self, stop_price: float) -> int:
            return 100

        def start(self):
            self.log("Strategy Started (Mock)")

        def stop(self):
            self.log("Strategy Stopped (Mock)")
