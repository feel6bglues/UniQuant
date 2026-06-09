"""
测试财务导入链路关键行为
"""

import os

import pandas as pd

os.environ["HOME"] = "/tmp"

from uniquant.data.services.import_financial import TDXFinancialImporter


class TestTDXFinancialImporter:
    """TDXFinancialImporter 测试"""

    def test_normalize_stock_code(self, tmp_path):
        importer = TDXFinancialImporter(
            tdx_dir=tmp_path / "tdx",
            output_dir=tmp_path / "lake" / "financial",
        )

        assert importer._normalize_stock_code(1) == "000001.SZ"
        assert importer._normalize_stock_code("000001") == "000001.SZ"
        assert importer._normalize_stock_code("600000") == "600000.SH"
        assert importer._normalize_stock_code("830001") == "830001.BJ"

    def test_write_single_stock_preserves_existing_history(self, tmp_path):
        output_dir = tmp_path / "lake" / "financial"
        output_dir.mkdir(parents=True, exist_ok=True)
        importer = TDXFinancialImporter(
            tdx_dir=tmp_path / "tdx",
            output_dir=output_dir,
        )

        existing = pd.DataFrame({
            "code": ["000001.SZ"],
            "report_date": pd.to_datetime(["2023-12-31"]),
            "基本每股收益": [1.0],
        })
        existing.to_parquet(output_dir / "000001.SZ.parquet", index=False)

        new_data = pd.DataFrame({
            "code": ["000001.SZ"],
            "report_date": [20240331],
            "基本每股收益": [1.2],
        })

        assert importer._write_single_stock("000001", [new_data]) is True

        result = pd.read_parquet(output_dir / "000001.SZ.parquet")

        assert len(result) == 2
        assert result["report_date"].tolist() == [
            pd.Timestamp("2023-12-31"),
            pd.Timestamp("2024-03-31"),
        ]
        assert result["code"].tolist() == ["000001.SZ", "000001.SZ"]

    def test_allowed_security_filters_to_stock_codes_only(self, tmp_path):
        stock_codes_file = tmp_path / "all_stock_codes.csv"
        pd.DataFrame([
            {"code": "sz.000001", "name": "平安银行", "type": 1, "status": 1},
            {"code": "sh.000001", "name": "上证指数", "type": 2, "status": 1},
            {"code": "sh.510050", "name": "ETF", "type": 5, "status": 1},
            {"code": "sz.123001", "name": "转债", "type": 4, "status": 1},
            {"code": "sz.000002", "name": "已退市股票", "type": 1, "status": 0},
        ]).to_csv(stock_codes_file, index=False, encoding="utf-8-sig")

        importer = TDXFinancialImporter(
            tdx_dir=tmp_path / "tdx",
            output_dir=tmp_path / "lake" / "financial",
            stock_codes_file=stock_codes_file,
        )

        assert importer.is_allowed_security("000001.SZ") is True
        assert importer.is_allowed_security("000001.SH") is False
        assert importer.is_allowed_security("510050.SH") is False
        assert importer.is_allowed_security("123001.SZ") is False
        assert importer.is_allowed_security("000002.SZ") is False

    def test_write_single_stock_skips_non_stock_security(self, tmp_path):
        stock_codes_file = tmp_path / "all_stock_codes.csv"
        pd.DataFrame([
            {"code": "sh.510050", "name": "ETF", "type": 5, "status": 1},
        ]).to_csv(stock_codes_file, index=False, encoding="utf-8-sig")

        importer = TDXFinancialImporter(
            tdx_dir=tmp_path / "tdx",
            output_dir=tmp_path / "lake" / "financial",
            stock_codes_file=stock_codes_file,
        )

        df = pd.DataFrame({
            "code": ["510050.SH"],
            "report_date": [20240331],
            "基本每股收益": [1.2],
        })

        assert importer._write_single_stock("510050", [df]) is False
        assert not (tmp_path / "lake" / "financial" / "510050.SH.parquet").exists()
