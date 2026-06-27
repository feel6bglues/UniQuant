from __future__ import annotations

import pandas as pd

from uniquant.shared.interfaces import ResearchDataPack


def test_create_empty():
    pack = ResearchDataPack(symbol="000001.SZ")
    assert pack.symbol == "000001.SZ"
    assert pack.stock_df is None
    assert pack.regime is None


def test_create_with_data():
    df = pd.DataFrame({"date": ["2025-01-01"], "close": [10.0]})
    pack = ResearchDataPack(
        symbol="000001.SZ",
        stock_df=df,
        lppl={"risk_level": "Safe", "confidence": 0.8},
    )
    assert pack.symbol == "000001.SZ"
    assert pack.stock_df is not None
    assert len(pack.stock_df) == 1
    assert pack.lppl["risk_level"] == "Safe"


def test_from_dict():
    data = {
        "symbol": "000001.SZ",
        "stock": pd.DataFrame({"date": ["2025-01-01"], "close": [10.0]}),
        "regime": "NORMAL",
        "lppl": {"risk_level": "Danger"},
    }
    pack = ResearchDataPack.from_dict(data, symbol="000001.SZ")
    assert pack.symbol == "000001.SZ"
    assert pack.regime == "NORMAL"
    assert pack.lppl["risk_level"] == "Danger"


def test_backward_compat_dict_access():
    pack = ResearchDataPack(symbol="000001.SZ", metadata={"source": "test"})
    assert pack.metadata["source"] == "test"


def test_default_fields():
    pack = ResearchDataPack(symbol="600000.SH")
    assert pack.index_df is None
    assert pack.ntf is None
    assert pack.czsc is None
    assert pack.wyckoff is None
    assert pack.alpha is None
    assert pack.factors is None
    assert pack.metadata == {}


def test_to_dict():
    df = pd.DataFrame({"date": ["2025-01-01"], "close": [10.0]})
    pack = ResearchDataPack(
        symbol="000001.SZ",
        stock_df=df,
        regime="NORMAL",
        lppl={"risk_level": "Safe"},
        metadata={"source": "test"},
    )
    d = pack.to_dict()
    assert d["symbol"] == "000001.SZ"
    assert d["regime"] == "NORMAL"
    assert d["lppl"]["risk_level"] == "Safe"
    assert d["metadata"]["source"] == "test"
    assert d["stock"] is df


def test_round_trip():
    data = {
        "symbol": "000001.SZ",
        "stock": pd.DataFrame({"date": ["2025-01-01"], "close": [10.0]}),
        "regime": "NORMAL",
        "lppl": {"risk_level": "Danger"},
        "metadata": {"source": "test"},
    }
    pack = ResearchDataPack.from_dict(data)
    d = pack.to_dict()
    assert d["symbol"] == data["symbol"]
    assert d["regime"] == data["regime"]
    assert d["lppl"]["risk_level"] == data["lppl"]["risk_level"]
    assert d["metadata"]["source"] == data["metadata"]["source"]


def test_to_dict_all_none():
    pack = ResearchDataPack(symbol="600000.SH")
    d = pack.to_dict()
    assert d["symbol"] == "600000.SH"
    assert d["stock"] is None
    assert d["index"] is None
    assert d["regime"] is None
    assert d["metadata"] == {}


def test_feature_flag_exists():
    from uniquant.shared.config_models import FeatureFlags
    flags = FeatureFlags()
    assert hasattr(flags, "use_research_data_pack")
    assert flags.use_research_data_pack is False


def test_config_yaml_has_flag():
    from uniquant.shared.config_loader import get_config
    cfg = get_config()
    ff = cfg.get("refactoring", {}).get("feature_flags", {})
    assert "use_research_data_pack" in ff
    assert ff["use_research_data_pack"] is False


def test_fetch_research_pack_returns_typed():
    import pandas as pd
    from uniquant.services.data_service import DataService

    service = DataService()
    mock_stock = pd.DataFrame({"date": ["2025-01-01"], "close": [10.0]})
    mock_bench = pd.DataFrame({"date": ["2025-01-01"], "close": [4000.0]})
    mock_etf = pd.DataFrame({"date": ["2025-01-01"], "close": [3.5]})

    service.fetch_for_brain = lambda sym: {
        "stock": mock_stock,
        "bench": mock_bench,
        "etf": mock_etf,
    }
    pack = service.fetch_research_pack("000001.SZ")
    assert isinstance(pack, ResearchDataPack)
    assert pack.symbol == "000001.SZ"
    assert pack.stock_df is mock_stock
    assert pack.index_df is mock_bench  # "bench" key now mapped by from_dict


def test_fetch_research_pack_returns_from_dict():
    from uniquant.services.data_service import DataService

    service = DataService()
    service.fetch_for_brain = lambda sym: {"stock": None, "bench": None, "etf": None}
    pack = service.fetch_research_pack("600000.SH")
    assert pack.symbol == "600000.SH"
    assert pack.stock_df is None


def test_prepare_data_default_path_uses_dict():
    from unittest.mock import Mock
    from uniquant.services.analysis_service_v2 import AnalysisService

    mock_data = Mock()
    analysis = AnalysisService(data_service=mock_data)
    stock_df = pd.DataFrame({"date": ["2025-01-01"], "close": [10.0]})
    mock_data.fetch_for_brain = Mock(return_value={"stock": stock_df})
    mock_data.fetch_research_pack = Mock()

    result = analysis._prepare_data("000001.SZ")
    assert result is not None
    assert result["stock"] is stock_df
    mock_data.fetch_for_brain.assert_called_once_with("000001.SZ")
    mock_data.fetch_research_pack.assert_not_called()


def test_prepare_data_typed_path_uses_research_pack():
    from unittest.mock import Mock, patch
    from uniquant.services.analysis_service_v2 import AnalysisService

    mock_data = Mock()
    analysis = AnalysisService(data_service=mock_data)
    stock_df = pd.DataFrame({"date": ["2025-01-01"], "close": [10.0]})

    typed_pack = ResearchDataPack(
        symbol="000001.SZ",
        stock_df=stock_df,
        lppl={"risk_level": "Safe"},
        metadata={"source": "typed"},
    )
    mock_data.fetch_research_pack = Mock(return_value=typed_pack)

    with patch(
        "uniquant.services.analysis_service_v2.load_refactoring_config"
    ) as mock_cfg:
        from uniquant.shared.config_models import FeatureFlags, RefactoringConfig
        mock_cfg.return_value = RefactoringConfig(
            feature_flags=FeatureFlags(use_research_data_pack=True),
        )
        result = analysis._prepare_data("000001.SZ")

    assert result is not None
    assert isinstance(result, ResearchDataPack)
    assert result.stock_df is stock_df
    assert result.symbol == "000001.SZ"
    assert result.lppl["risk_level"] == "Safe"
    assert result.metadata["source"] == "typed"
    mock_data.fetch_research_pack.assert_called_once_with("000001.SZ")


def test_prepare_data_typed_path_fallback_on_error():
    from unittest.mock import Mock, patch
    from uniquant.services.analysis_service_v2 import AnalysisService

    mock_data = Mock()
    analysis = AnalysisService(data_service=mock_data)
    stock_df = pd.DataFrame({"date": ["2025-01-01"], "close": [10.0]})
    mock_data.fetch_for_brain = Mock(return_value={"stock": stock_df})

    with patch(
        "uniquant.services.analysis_service_v2.load_refactoring_config"
    ) as mock_cfg:
        mock_cfg.side_effect = ImportError("config broken")
        result = analysis._prepare_data("000001.SZ")

    assert result is not None
    assert result["stock"] is stock_df
    mock_data.fetch_for_brain.assert_called_once_with("000001.SZ")
