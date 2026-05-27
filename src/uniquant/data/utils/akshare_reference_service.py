from typing import Any, Callable, Optional

import pandas as pd

from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class AkshareReferenceService:
    """Reference/news/board oriented AkShare method wrappers."""

    def __init__(self, call: Callable[..., Optional[Any]]):
        self._call = call

    def fetch_industry_list(self) -> Optional[pd.DataFrame]:
        return self._call("stock_board_industry_name_em")

    def fetch_concept_list(self) -> Optional[pd.DataFrame]:
        return self._call("stock_board_concept_name_em")

    def fetch_concept_relation(self, symbol: str) -> Optional[pd.DataFrame]:
        return self._call("stock_board_concept_cons_em", symbol=symbol)

    def fetch_financial_breakfast(self) -> Optional[pd.DataFrame]:
        return self._call("stock_info_cjzc_em")

    def fetch_stock_zt_pool_dtgc(self, date: str) -> Optional[pd.DataFrame]:
        return self._call("stock_zt_pool_dtgc_em", date=date)

    def fetch_stock_zt_pool_previous(self, date: str) -> Optional[pd.DataFrame]:
        return self._call("stock_zt_pool_previous_em", date=date)

    def fetch_stock_lhb_jgmmtj(
        self, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        return self._call(
            "stock_lhb_jgmmtj_em", start_date=start_date, end_date=end_date
        )

    def fetch_fund_hold_detail(self, symbol: str, date: str) -> Optional[pd.DataFrame]:
        return self._call("stock_report_fund_hold_detail", symbol=symbol, date=date)

    def fetch_hsgt_board_rank(
        self, symbol: str, indicator: str = "今日"
    ) -> Optional[pd.DataFrame]:
        return self._call("stock_hsgt_board_rank_em", symbol=symbol, indicator=indicator)

    def fetch_ipo_tutor(self) -> Optional[pd.DataFrame]:
        return self._call("stock_ipo_tutor_em")

    def fetch_dzjy_hyyybtj(self, symbol: str = "近3日") -> Optional[pd.DataFrame]:
        return self._call("stock_dzjy_hyyybtj", symbol=symbol)

    def fetch_global_news(self, source: str = "em") -> Optional[pd.DataFrame]:
        method_map = {
            "em": "stock_info_global_em",
            "sina": "stock_info_global_sina",
            "futu": "stock_info_global_futu",
            "ths": "stock_info_global_ths",
            "cls": "stock_info_global_cls",
        }
        return self._call(method_map.get(source, "stock_info_global_em"))

    def fetch_stock_news(self, symbol: str) -> Optional[pd.DataFrame]:
        return self._call("stock_news_em", symbol=symbol)

    def fetch_stock_yjyg(self) -> Optional[pd.DataFrame]:
        return self._call("stock_yjyg_em")

    def fetch_stock_yysj(self) -> Optional[pd.DataFrame]:
        return self._call("stock_yysj_em")

    def fetch_concept_list_ths(self) -> Optional[pd.DataFrame]:
        logger.info("开始获取同花顺概念板块列表")
        result = self._call("stock_board_concept_name_ths")
        if result is not None and not result.empty:
            logger.info("成功获取概念板块列表: %d 个板块", len(result))
        else:
            logger.warning("获取概念板块列表为空")
        return result
