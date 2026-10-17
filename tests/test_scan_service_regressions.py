import pandas as pd

from uniquant.services.scan_service import ScanConfig, ScanPipeline


def test_scan_pipeline_load_data_skips_invalid_financial_parquet(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    financial_dir = data_dir / "lake" / "financial"
    financial_dir.mkdir(parents=True, exist_ok=True)
    # Step4 (D5 R-5): 主数据硬失败 → fixture 提供最小主数据表
    pd.DataFrame({
        "code": ["sz.000001"], "name": ["测试2"], "代码": ["000001"],
        "ipoDate": ["2000-01-01"], "outDate": [""], "type": ["1"], "status": ["1"],
    }).to_csv(data_dir / "all_stock_codes.csv", index=False, encoding="utf-8-sig")
    (financial_dir / "000001.SZ.parquet").write_text("invalid parquet", encoding="utf-8")

    pipeline = ScanPipeline(data_dir=str(data_dir), config=ScanConfig())
    pipeline.storage.batch_read_data = lambda symbols, data_type="daily": {
        "000001.SZ": pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01"]),
                "close": [10.0],
            }
        )
    }

    def raise_value_error(path):
        raise ValueError(f"cannot read {path}")

    monkeypatch.setattr("pandas.read_parquet", raise_value_error)

    pipeline.load_data(symbols=["000001.SZ"])

    assert "000001.SZ" in pipeline.daily_data
    assert pipeline.financial_data == {}
