# -*- coding: utf-8 -*-
"""
单元测试: StorageManager 数据新鲜度与两级 SLA 检测 (R10 闭环)

测试覆盖:
1. validate_freshness 正常检测逻辑（有湖数据时提取真实最大交易日）
2. 空湖或滞后超阈值时的告警与返回值结构
3. 本地 TDX .day 路径比对逻辑（两级滞后 L1 与 L2 计算）
4. 上游 TDX 停更告警与 require_l1_fresh 联合判断
5. 损坏 parquet 文件的健壮容错与 read_errors 记录
6. 真实生产环境数据冒烟测试
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import Tuple

import pandas as pd
import pytest

from uniquant.data.lake.storage_manager import StorageManager


def _create_mock_day_file(path: Path, date_int: int = 20261012) -> Path:
    """创建紧凑格式的通达信 .day 二进制测试文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    # 格式: <IIIIIfII (date, open, high, low, close, amount, volume, reserved)
    # 每条 32 字节
    with open(path, "wb") as f:
        prev_date = date_int - 1
        record1 = struct.pack("<IIIIIfII", prev_date, 1000, 1050, 990, 1020, 1000000.0, 10000, 0)
        record2 = struct.pack("<IIIIIfII", date_int, 1020, 1080, 1010, 1060, 1500000.0, 15000, 0)
        f.write(record1)
        f.write(record2)
    return path


def _create_mock_parquet_file(path: Path, dates: list[str]) -> Path:
    """创建包含指定 date 序列的日线 parquet 测试文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({
        "date": pd.to_datetime(dates),
        "open": [10.0] * len(dates),
        "high": [11.0] * len(dates),
        "low": [9.5] * len(dates),
        "close": [10.5] * len(dates),
        "amount": [100000.0] * len(dates),
        "volume": [1000] * len(dates),
        "reserved": [0] * len(dates),
        "code": [path.stem] * len(dates),
    })
    df.to_parquet(path, index=False)
    return path


@pytest.fixture
def mock_storage_env(tmp_path: Path):
    """创建带有最小主数据表的隔离 StorageManager 环境"""
    # D5 R-5 硬失败防护: 必须提供 all_stock_codes.csv
    stock_codes_file = tmp_path / "all_stock_codes.csv"
    stock_codes_file.write_text("code,tradeStatus,code_name\nsh.600519,1,贵州茅台\nsz.000001,1,平安银行\n")

    logger = logging.getLogger("StorageManager")
    orig_propagate = logger.propagate
    logger.propagate = True

    sm = StorageManager(data_dir=str(tmp_path))
    try:
        yield sm, tmp_path
    finally:
        logger.propagate = orig_propagate


class TestStorageFreshnessSLA:
    """数据新鲜度两级 SLA 检测测试套件"""

    def test_freshness_normal_lake_detection(self, mock_storage_env: Tuple[StorageManager, Path]):
        """测试正常数据湖检测: 准确提取湖内真实最大交易日"""
        sm, _ = mock_storage_env
        daily_dir = sm.daily_dir

        # 写入两个标的数据，最大日期分别为 2026-10-08 与 2026-10-10
        _create_mock_parquet_file(
            daily_dir / "600519.SH.parquet",
            ["2026-10-01", "2026-10-02", "2026-10-08"],
        )
        _create_mock_parquet_file(
            daily_dir / "000001.SZ.parquet",
            ["2026-10-08", "2026-10-10"],
        )

        res = sm.validate_freshness(
            max_lag_days=7,
            as_of_date="2026-10-12",
            check_tdx=False,
        )

        assert res["is_fresh"] is True
        assert res["lake_max_date"] == "2026-10-10"
        assert res["tdx_max_date"] is None
        assert res["l2_lag_days"] == 2  # 2026-10-12 - 2026-10-10 = 2 天 <= 7 天
        assert res["details"]["lake_empty"] is False
        assert res["details"]["scanned_files_count"] >= 2
        assert res["details"]["read_errors"] == []

    def test_freshness_empty_lake_warning(
        self,
        mock_storage_env: Tuple[StorageManager, Path],
        caplog: pytest.LogCaptureFixture,
    ):
        """测试空湖检测: 告警并返回非新鲜与标准空字典"""
        sm, _ = mock_storage_env

        with caplog.at_level(logging.WARNING):
            res = sm.validate_freshness(check_tdx=False)

        assert res["is_fresh"] is False
        assert res["lake_max_date"] == ""
        assert res["tdx_max_date"] is None
        assert res["l2_lag_days"] == -1
        assert res["details"]["lake_empty"] is True
        assert "L2_LAKE_EMPTY" in res["details"]["stale_reasons"]
        assert any("数据湖日线数据为空" in record.message for record in caplog.records)

    def test_freshness_lag_exceeded_threshold(
        self,
        mock_storage_env: Tuple[StorageManager, Path],
        caplog: pytest.LogCaptureFixture,
    ):
        """测试滞后超过 max_lag_days 时的告警行为"""
        sm, _ = mock_storage_env
        daily_dir = sm.daily_dir

        _create_mock_parquet_file(
            daily_dir / "600519.SH.parquet",
            ["2026-09-01", "2026-09-10"],
        )

        # 基准日 2026-09-25, 滞后 15 天
        with caplog.at_level(logging.WARNING):
            res_strict = sm.validate_freshness(
                max_lag_days=7,
                as_of_date="2026-09-25",
                check_tdx=False,
            )

        assert res_strict["is_fresh"] is False
        assert res_strict["l2_lag_days"] == 15
        assert res_strict["details"]["l2_is_fresh"] is False
        assert any("数据湖滞后超阈值" in record.message for record in caplog.records)

        # 调宽阈值至 20 天，预期恢复 fresh
        res_relaxed = sm.validate_freshness(
            max_lag_days=20,
            as_of_date="2026-09-25",
            check_tdx=False,
        )
        assert res_relaxed["is_fresh"] is True
        assert res_relaxed["details"]["l2_is_fresh"] is True

    def test_freshness_with_tdx_comparison_logic(
        self,
        mock_storage_env: Tuple[StorageManager, Path],
        tmp_path: Path,
    ):
        """测试与本地 TDX 路径比对两级滞后 (L1 与 L2)"""
        sm, _ = mock_storage_env
        daily_dir = sm.daily_dir

        # 构造 TDX 目录: 上游通达信数据末日为 2026-10-10
        mock_tdx_vipdoc = tmp_path / "mock_tdx" / "vipdoc"
        _create_mock_day_file(mock_tdx_vipdoc / "sh" / "lday" / "sh600519.day", date_int=20261010)

        # 构造湖内数据: 湖数据末日为 2026-10-06
        _create_mock_parquet_file(
            daily_dir / "600519.SH.parquet",
            ["2026-10-05", "2026-10-06"],
        )

        # 基准日为 2026-10-11
        # L1 (TDX 相对基准日): 2026-10-11 - 2026-10-10 = 1 天 (正常)
        # L2 (湖相对 TDX): 2026-10-10 - 2026-10-06 = 4 天
        res = sm.validate_freshness(
            max_lag_days=5,
            tdx_dir=mock_tdx_vipdoc,
            as_of_date="2026-10-11",
            check_tdx=True,
        )

        assert res["is_fresh"] is True
        assert res["lake_max_date"] == "2026-10-06"
        assert res["tdx_max_date"] == "2026-10-10"
        assert res["l2_lag_days"] == 4
        assert res["details"]["l1_lag_days"] == 1
        assert res["details"]["l1_is_fresh"] is True
        assert res["details"]["l2_is_fresh"] is True

        # 若 max_lag_days 缩紧到 3 天，则 L2 超标
        res_tight = sm.validate_freshness(
            max_lag_days=3,
            tdx_dir=mock_tdx_vipdoc,
            as_of_date="2026-10-11",
            check_tdx=True,
        )
        assert res_tight["is_fresh"] is False
        assert res_tight["details"]["l2_is_fresh"] is False

    def test_freshness_tdx_upstream_stale_warning(
        self,
        mock_storage_env: Tuple[StorageManager, Path],
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        """测试 TDX 上游停更 (L1 > 1 天) 时的告警与 require_l1_fresh 控制"""
        sm, _ = mock_storage_env
        daily_dir = sm.daily_dir

        mock_tdx_vipdoc = tmp_path / "mock_tdx" / "vipdoc"
        # 上游停更在 2026-09-30
        _create_mock_day_file(mock_tdx_vipdoc / "sh" / "lday" / "sh600519.day", date_int=20260930)

        # 湖同步完全跟上上游 TDX (也是 2026-09-30, L2 = 0)
        _create_mock_parquet_file(
            daily_dir / "600519.SH.parquet",
            ["2026-09-29", "2026-09-30"],
        )

        # 当前基准日 2026-10-10 (L1 滞后 10 天)
        with caplog.at_level(logging.WARNING):
            res = sm.validate_freshness(
                max_lag_days=7,
                tdx_dir=mock_tdx_vipdoc,
                as_of_date="2026-10-10",
                require_l1_fresh=False,
            )

        # 默认 require_l1_fresh=False，湖与 TDX 对齐即视为 L2 满足
        assert res["is_fresh"] is True
        assert res["l2_lag_days"] == 0
        assert res["details"]["l1_lag_days"] == 10
        assert res["details"]["l1_is_fresh"] is False
        assert any("TDX 上游数据停更/滞后" in record.message for record in caplog.records)

        # 若开启 require_l1_fresh=True，则由于上游停更整体判定不新鲜
        res_strict = sm.validate_freshness(
            max_lag_days=7,
            tdx_dir=mock_tdx_vipdoc,
            as_of_date="2026-10-10",
            require_l1_fresh=True,
        )
        assert res_strict["is_fresh"] is False

    def test_freshness_corrupted_parquet_graceful_handling(
        self,
        mock_storage_env: Tuple[StorageManager, Path],
    ):
        """测试存在损坏 parquet 文件时，不崩溃并记录在 read_errors 中"""
        sm, _ = mock_storage_env
        daily_dir = sm.daily_dir

        # 写入一个有效文件
        _create_mock_parquet_file(
            daily_dir / "600519.SH.parquet",
            ["2026-10-01", "2026-10-05"],
        )
        # 写入一个损坏文件
        corrupted = daily_dir / "000001.SZ.parquet"
        corrupted.write_bytes(b"NOT_A_PARQUET_FILE_GARBAGE")

        res = sm.validate_freshness(
            sample_size=0,  # 全量扫描
            as_of_date="2026-10-06",
            check_tdx=False,
        )

        assert res["is_fresh"] is True
        assert res["lake_max_date"] == "2026-10-05"
        assert len(res["details"]["read_errors"]) >= 1
        assert any("000001.SZ.parquet" in err for err in res["details"]["read_errors"])

    def test_freshness_real_environment_smoke(self):
        """冒烟测试: 在项目真实数据湖上运行 validate_freshness"""
        sm = StorageManager()
        res = sm.validate_freshness()

        assert isinstance(res["is_fresh"], bool)
        assert isinstance(res["lake_max_date"], str)
        assert res["lake_max_date"] == "2026-09-23"  # 真实湖基线冻结日期
        assert isinstance(res["l2_lag_days"], int)
        assert res["l2_lag_days"] >= 0
        assert res["details"]["lake_empty"] is False
        assert res["details"]["lake_dir"].endswith("quotes/daily")
        if res["tdx_max_date"] is not None:
            assert res["tdx_max_date"] >= "2026-09-30"
