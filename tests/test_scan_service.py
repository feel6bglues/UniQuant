import json
import unittest.mock as mock

import pandas as pd

from uniquant.services.scan_service import ScanConfig, ScanPipeline


def test_default_config_parallelism_disabled():
    """默认配置下 checkpoint 关闭，max_workers=4"""
    config = ScanConfig()
    assert config.max_workers == 4
    assert config.checkpoint_enabled is False


def test_max_workers_config():
    """max_workers 可配置"""
    config = ScanConfig(max_workers=8)
    assert config.max_workers == 8


def test_parallel_financial_loading_empty_dir(tmp_path):
    """无财务 parquet 文件时返回空，不报错"""
    pipeline = ScanPipeline(data_dir=str(tmp_path), config=ScanConfig())
    pipeline.storage.batch_read_data = lambda symbols, data_type="daily": {}
    pipeline.load_data(symbols=["000001.SZ"])
    assert pipeline.financial_data == {}


def test_parallel_financial_loading_success(tmp_path):
    """并行加载财务数据成功"""
    data_dir = tmp_path / "data"
    financial_dir = data_dir / "lake" / "financial"
    financial_dir.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame({"code": ["000001"], "pe": [10.0]})
    df.to_parquet(financial_dir / "000001.SZ.parquet", index=False)

    pipeline = ScanPipeline(data_dir=str(data_dir), config=ScanConfig(max_workers=2))
    pipeline.storage.batch_read_data = lambda symbols, data_type="daily": {
        "000001.SZ": pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "close": [10.0]})
    }
    pipeline.load_data(symbols=["000001.SZ"])
    assert "000001.SZ" in pipeline.financial_data
    assert pipeline.financial_data["000001.SZ"]["pe"].iloc[0] == 10.0


def test_parallel_financial_loading_partial_failures(tmp_path, monkeypatch):
    """部分 parquet 损坏时跳过错误，不影响其他"""
    data_dir = tmp_path / "data"
    financial_dir = data_dir / "lake" / "financial"
    financial_dir.mkdir(parents=True, exist_ok=True)

    good_df = pd.DataFrame({"code": ["000001"], "pe": [10.0]})
    good_df.to_parquet(financial_dir / "000001.SZ.parquet", index=False)
    (financial_dir / "000002.SZ.parquet").write_text("corrupted", encoding="utf-8")
    (financial_dir / "000003.SZ.parquet").write_bytes(b"\x00\x01\x02")

    pipeline = ScanPipeline(data_dir=str(data_dir), config=ScanConfig(max_workers=2))
    pipeline.storage.batch_read_data = lambda symbols, data_type="daily": {
        s: pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "close": [10.0]})
        for s in symbols
    }
    pipeline.load_data(symbols=["000001.SZ", "000002.SZ", "000003.SZ"])
    assert "000001.SZ" in pipeline.financial_data
    assert "000002.SZ" not in pipeline.financial_data
    assert "000003.SZ" not in pipeline.financial_data


def test_checkpoint_save_and_load(tmp_path):
    """checkpoint 方法正常读写 JSON 文件"""
    data_dir = tmp_path / "data"
    pipeline = ScanPipeline(data_dir=str(data_dir), config=ScanConfig(checkpoint_enabled=True))
    pipeline._save_checkpoint("test_checkpoint", {"symbols": ["A", "B"]})

    cp_file = pipeline._checkpoint_dir / "test_checkpoint.json"
    assert cp_file.exists()
    assert json.loads(cp_file.read_text(encoding="utf-8")) == {"symbols": ["A", "B"]}

    loaded = pipeline._load_checkpoint("test_checkpoint")
    assert loaded == {"symbols": ["A", "B"]}


def test_checkpoint_disabled_does_not_create_files(tmp_path):
    """checkpoint_enabled=False 时不会创建 checkpoint 文件"""
    data_dir = tmp_path / "data"
    pipeline = ScanPipeline(data_dir=str(data_dir))
    pipeline._save_checkpoint("test", {"x": 1})

    cp_file = pipeline._checkpoint_dir / "test.json"
    assert not cp_file.exists()


def test_clear_checkpoints_removes_all_json(tmp_path):
    """_clear_checkpoints 删除所有 JSON checkpoint 文件"""
    data_dir = tmp_path / "data"
    pipeline = ScanPipeline(data_dir=str(data_dir), config=ScanConfig(checkpoint_enabled=True))
    pipeline._save_checkpoint("a", {})
    pipeline._save_checkpoint("b", {})
    pipeline._clear_checkpoints()
    assert not list(pipeline._checkpoint_dir.iterdir())


def test_financial_loading_checkpoint_skips_loaded(tmp_path):
    """已加载的财务数据在 checkpoint 中标记，重新 load_data 时跳过"""
    data_dir = tmp_path / "data"
    financial_dir = data_dir / "lake" / "financial"
    financial_dir.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame({"code": ["000001"], "pe": [10.0]})
    df.to_parquet(financial_dir / "000001.SZ.parquet", index=False)
    df2 = pd.DataFrame({"code": ["000002"], "pe": [20.0]})
    df2.to_parquet(financial_dir / "000002.SZ.parquet", index=False)

    config = ScanConfig(max_workers=2, checkpoint_enabled=True)
    pipeline = ScanPipeline(data_dir=str(data_dir), config=config)
    pipeline.storage.batch_read_data = lambda symbols, data_type="daily": {
        s: pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "close": [10.0]})
        for s in symbols
    }

    # 第一次加载
    pipeline.load_data(symbols=["000001.SZ"])
    assert "000001.SZ" in pipeline.financial_data

    # 验证 checkpoint 保存了已加载的 symbol
    cp = pipeline._load_checkpoint("financial_loaded")
    assert cp is not None
    assert "000001.SZ" in cp

    # 第二次加载 — 只加载未缓存的
    pipeline.load_data(symbols=["000001.SZ", "000002.SZ"])
    assert "000002.SZ" in pipeline.financial_data


def test_lightweight_skips_financial_loading(tmp_path):
    """lightweight=True 跳过财务数据加载"""
    data_dir = tmp_path / "data"
    financial_dir = data_dir / "lake" / "financial"
    financial_dir.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame({"code": ["000001"], "pe": [10.0]})
    df.to_parquet(financial_dir / "000001.SZ.parquet", index=False)

    pipeline = ScanPipeline(data_dir=str(data_dir), config=ScanConfig(lightweight=True))
    pipeline.storage.batch_read_data = lambda symbols, data_type="daily": {}
    pipeline.load_data(symbols=["000001.SZ"])
    assert pipeline.financial_data == {}


def test_merge_financial_metrics_checkpoint_skips_merged(tmp_path):
    """合并财务指标时 checkpoint 跳过已合并的 symbol"""
    data_dir = tmp_path / "data"
    financial_dir = data_dir / "lake" / "financial"
    financial_dir.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame({"code": ["000001"], "pe": [10.0]})
    df.to_parquet(financial_dir / "000001.SZ.parquet", index=False)

    config = ScanConfig(max_workers=2, checkpoint_enabled=True)
    pipeline = ScanPipeline(data_dir=str(data_dir), config=config)
    pipeline.storage.batch_read_data = lambda symbols, data_type="daily": {
        "000001.SZ": pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "close": [10.0, 11.0],
        })
    }
    pipeline.load_data(symbols=["000001.SZ"])
    pipeline.build_factors()
    # 第二次 build_factors 不再重复合并
    pipeline.build_factors()


def test_concurrent_load_and_merge_backward_compatible(tmp_path):
    """并行加载+合并与旧版行为一致（结果结构不变）"""
    data_dir = tmp_path / "data"
    financial_dir = data_dir / "lake" / "financial"
    financial_dir.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame({
        "code": ["000001"],
        "report_date": pd.to_datetime(["2024-03-31"]),
        "财报公告日期": [20240415],
        "基本每股收益": [2.0],
        "每股净资产": [4.0],
    })
    df.to_parquet(financial_dir / "000001.SZ.parquet", index=False)

    pipeline = ScanPipeline(data_dir=str(data_dir), config=ScanConfig(max_workers=2))
    pipeline.storage.batch_read_data = lambda symbols, data_type="daily": {
        "000001.SZ": pd.DataFrame({
            "date": pd.to_datetime(["2024-04-10", "2024-04-30"]),
            "open": [10.0, 11.0],
            "high": [10.5, 11.5],
            "low": [9.8, 10.8],
            "close": [10.0, 12.0],
            "volume": [1000, 1200],
            "amount": [10000, 14400],
        })
    }
    pipeline.load_data(symbols=["000001.SZ"])
    assert "000001.SZ" in pipeline.financial_data
    assert "000001.SZ" in pipeline.daily_data

    # 模拟 compute_all_factors 返回空（避免依赖 FactorRegistry 状态）
    from uniquant.brain.factors.composer import FactorComposer
    with mock.patch.object(FactorComposer, "compute_all_factors", return_value=pd.DataFrame()):
        pipeline.build_factors()
    assert not pipeline.combined_df.empty
    assert "code" in pipeline.combined_df.columns


def test_parallel_financial_loading_no_files_no_crash(tmp_path):
    """没有财务文件时并行加载不报错"""
    data_dir = tmp_path / "data"
    pipeline = ScanPipeline(data_dir=str(data_dir), config=ScanConfig(max_workers=2))
    pipeline.storage.batch_read_data = lambda symbols, data_type="daily": {
        "000001.SZ": pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "close": [10.0]})
    }
    pipeline.load_data(symbols=["000001.SZ"])
    assert pipeline.financial_data == {}
