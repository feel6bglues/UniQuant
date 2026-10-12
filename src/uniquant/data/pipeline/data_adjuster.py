"""数据复权器 — 已废弃为兼容薄壳 (唯一算法 = CorporateActionAdjuster, 2026-10-12)。

迁移计划 D4/R13: 旧轨废弃先于或等于 Bug3 修复落地。本模块原实现为"双重坏死"旧轨:
``update_factors`` 喂 parquet 英文列 → ``smart_factor_calculator`` 期望
``.cash/.split/.r_price`` → AttributeError 被吞 → ``data/factors/`` 恒 0 文件 →
``apply_adjustment`` 恒"未找到复权因子，返回原始数据" (qfq 名义复权实为不复权)。

单轨化后的契约 (与新轨语义冻结一致):
- ``apply_adjustment`` 内部构造 ``CorporateActionAdjuster`` 并委托 ``adjust()``
  (qfq/hfq → adjust_type), 输出必含 ``adj_factor`` 列;
- **volume 恒不调整** (旧轨的 volume 缩放已删除);
- **qfq 锚点 = 数据最新日** (旧轨 ``iloc[-1]`` + 因子文件 merge_asof 路径已删除);
- gbbq 基线缺失 → 硬失败 (``GbbqBaselineMissingError``), 禁止静默单位矩阵;
- ``update_factors`` 保留为 deprecated 直通, 不再读写 ``data/factors/``。

原函数签名与返回类型不变, 旧 import 方 (``data_fetcher.py`` / ``data_pipeline_service.py``
/ ``data_importer.py`` / ``stock_data_updater.py``) 零改动可用。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..corporate_action import CorporateActionAdjuster
from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class DataAdjuster:
    """数据复权器 — 兼容薄壳, 唯一算法 = CorporateActionAdjuster (已废弃)。"""

    def __init__(self, storage_manager, gbbq_path: str | Path | None = None):
        """
        Args:
            storage_manager: 旧轨存储管理器 (仅用于推导 gbbq 基线路径与直读原始数据)。
            gbbq_path: 显式 gbbq 基线路径。None 时按 storage_manager.data_dir/fq/gbbq.parquet
                推导; storage 无有效 data_dir 时回退新轨默认路径 (项目 data/fq/gbbq.parquet)。
        """
        self.storage_manager = storage_manager
        # 旧轨因子文件管理器已废弃: 保留属性以兼容旧读取方, 恒为 None。
        self.factor_manager = None
        self._gbbq_path = self._resolve_gbbq_path(storage_manager, gbbq_path)
        self._action_adjuster: CorporateActionAdjuster | None = None

    @staticmethod
    def _resolve_gbbq_path(storage_manager, gbbq_path: str | Path | None) -> Path | None:
        """解析 gbbq 基线路径: 显式参数 > storage data_dir 推导 > 新轨默认 (None)。"""
        if gbbq_path is not None:
            return Path(gbbq_path)
        data_dir = getattr(storage_manager, "data_dir", None)
        if isinstance(data_dir, (str, Path)):
            return Path(data_dir) / "fq" / "gbbq.parquet"
        # 无有效 data_dir (如测试替身) → 交由 CorporateActionAdjuster 使用默认项目基线
        return None

    def _get_action_adjuster(self) -> CorporateActionAdjuster:
        """懒加载新轨调整器; gbbq 基线缺失在此处硬失败 (D2, 不做静默回退)。"""
        if self._action_adjuster is None:
            adjuster = CorporateActionAdjuster(gbbq_path=self._gbbq_path)
            adjuster.load_events()
            self._action_adjuster = adjuster
        return self._action_adjuster

    def is_valid_stock_code(self, code: str, market: str) -> bool:
        """验证股票代码是否在指定范围内

        Args:
            code: 股票代码
            market: 市场代码 (SH/SZ)

        Returns:
            bool: 是否为有效股票代码
        """
        # 沪市主板: 60xxxx
        if market == 'SH' and code.startswith('60') and len(code) == 6:
            return True
        # 科创板: 68xxxx
        elif market == 'SH' and code.startswith('68') and len(code) == 6:
            return True
        # 深市主板/中小板: 00xxxx
        elif market == 'SZ' and code.startswith('00') and len(code) == 6:
            return True
        # 创业板: 30xxxx
        elif market == 'SZ' and code.startswith('30') and len(code) == 6:
            return True
        return False

    def update_factors(self, symbol: str) -> bool:
        """[已废弃] 旧轨因子文件生成已下线, 因子改为复权时按需计算。

        不再读取日线/gbbq, 也不再写 ``data/factors/``; 保留签名与返回类型供
        ``stock_data_updater`` 等旧调用方零改动使用, 恒返回 True (直通)。
        """
        logger.warning(
            f"DataAdjuster.update_factors 已废弃为直通 (2026-10-12): {symbol} "
            f"不再读写 data/factors/, 复权因子由 CorporateActionAdjuster 按需计算"
        )
        return True

    def apply_adjustment(
        self, symbol: str, df_raw: pd.DataFrame, method: str,
        cutoff_date: str | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        """应用复权 — 已委托 CorporateActionAdjuster (薄壳)。

        Args:
            symbol: 股票代码, 如 '600000.SH'。
            df_raw: 原始日线 (含 date 与价格列)。
            method: 'qfq' / 'hfq'; 其它值按旧契约原样返回 (不触发 gbbq 加载)。
            cutoff_date: 截止日期, 过滤后再复权 (qfq 锚点随之落在截止日)。

        Returns:
            复权后的 DataFrame (新增 ``adj_factor`` 列, volume 不调整)。
        """
        if df_raw.empty or "date" not in df_raw.columns or method not in ("qfq", "hfq"):
            logger.warning(f"无效的复权参数: method={method}, 数据行数={len(df_raw)}")
            return df_raw

        logger.info(f"应用 {method} 复权，数据共 {len(df_raw)} 条记录")

        df = df_raw.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        n_bad = int(df["date"].isna().sum())
        if n_bad:
            logger.warning(f"{symbol} 有 {n_bad} 行日期无效，已剔除")
            df = df.dropna(subset=["date"])
        if cutoff_date is not None:
            df = df[df["date"] <= pd.Timestamp(cutoff_date)]
        if df.empty:
            logger.warning(f"{symbol} 过滤后无可用数据，返回空表")
            return df
        # 新轨按行位置对齐因子 → 必须按日期升序 (旧轨亦返回按日期排序结果)
        df = df.sort_values("date").reset_index(drop=True)

        result = self._get_action_adjuster().adjust(df, symbol, adjust_type=method)
        logger.info(
            f"复权完成 ({method})，共 {len(result)} 条记录 "
            f"(新增 adj_factor 列, volume 不调整)"
        )
        return result

    def get_adjusted_data(
        self, symbol: str, start_date: str, end_date: str, adjust: str = ""
    ) -> pd.DataFrame:
        """获取复权后的数据"""
        if not self.storage_manager:
            logger.error("StorageManager 未初始化")
            return pd.DataFrame()

        # 读取原始数据
        df_raw = self.storage_manager.read_local_raw(symbol)

        if df_raw.empty:
            return df_raw

        # 按日期范围过滤
        df_raw["date"] = pd.to_datetime(df_raw["date"])
        df_raw = df_raw[
            (df_raw["date"] >= pd.Timestamp(start_date))
            & (df_raw["date"] <= pd.Timestamp(end_date))
        ].copy()

        # 应用复权 (qfq/hfq 之外的 adjust 值按旧契约原样返回)
        return self.apply_adjustment(symbol, df_raw, method=adjust, cutoff_date=end_date)
