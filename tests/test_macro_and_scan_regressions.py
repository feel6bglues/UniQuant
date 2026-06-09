
import pandas as pd

from uniquant.services.analysis.macro_service import MacroAnalysisService
from uniquant.services.scan_service import ScanConfig, ScanPipeline


class DummyLake:
    def __init__(self, df: pd.DataFrame):
        self._df = df

    def read_data(self, symbol: str, data_type: str = "stock", market: str = "cn") -> pd.DataFrame:
        return self._df.copy()


class DummyDataService:
    def __init__(self, df: pd.DataFrame):
        self.lake = DummyLake(df)


def test_run_lppl_analysis_falls_back_on_runtime_error(monkeypatch):
    sample_df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=120, freq="D"),
            "close": [100 + i for i in range(120)],
        }
    )
    service = MacroAnalysisService(data_service=DummyDataService(sample_df))

    def raise_runtime_error(self, df):
        raise RuntimeError("lppl failed")

    monkeypatch.setattr(
        "uniquant.brain.lppl.engine.LPPLEngine.detect_bubble",
        raise_runtime_error,
    )

    result = service.run_lppl_analysis("000001.SZ")

    assert result["status"] == "success"
    assert result["summary"] == "使用基本统计方法进行泡沫风险分析"
    assert "bubble_detected" in result


def test_run_regime_detection_returns_failed_result_on_attribute_error(monkeypatch):
    service = MacroAnalysisService()

    def raise_attribute_error(self, symbol):
        raise AttributeError("bad regime dependency")

    monkeypatch.setattr(
        "uniquant.brain.regime.regime_detector.RegimeDetector.detect",
        raise_attribute_error,
    )

    result = service.run_regime_detection("000001.SZ")

    assert result["status"] == "failed"
    assert result["regime"] == "NORMAL"
    assert "bad regime dependency" in result["error"]


def test_run_ntf_detection_returns_failed_result_on_attribute_error(monkeypatch):
    service = MacroAnalysisService()

    def raise_attribute_error(self, symbol):
        raise AttributeError("bad ntf dependency")

    monkeypatch.setattr(
        "uniquant.brain.ntf.ntf_engine.NTFEngine.detect_intervention",
        raise_attribute_error,
    )

    result = service.run_ntf_detection("510300.SH")

    assert result["status"] == "failed"
    assert result["ntf_side"] == "NONE"
    assert result["ntf_intensity"] == 0.0
    assert "bad ntf dependency" in result["error"]


def test_scan_pipeline_load_data_skips_invalid_financial_parquet(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    financial_dir = data_dir / "lake" / "financial"
    financial_dir.mkdir(parents=True, exist_ok=True)
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
