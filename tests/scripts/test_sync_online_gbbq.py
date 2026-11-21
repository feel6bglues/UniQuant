"""sync_online_gbbq 单元测试 (通达信官方 gbbq 在线写通道, 第二十三轮)。

背景 (第二十一/二十二轮实测): tdxdata.download_gbbq → decrypt_records 为官方
HTTP 分发, cat=1 为本地 Wine gbbq 严格超集 (64,125 条零缺失, f32 精度差);
corporate_action.py 严格只消费 category=1。

全部用例注入假拉取器 + tmp 路径, 不触网、不写真实 data/fq (CI 安全)。
"""

import pandas as pd
import pytest

import scripts.maintenance.sync_online_gbbq as sync


def _rec(code="600519", date=20260626, cat=1, fenhong=280.24, song=0.0, peigu=0.0, price=0.0, market=1):
    return {
        "market": market,
        "code": code,
        "date": date,
        "category": cat,
        "fenhong": fenhong,
        "peigujia": price,
        "songzhuangu": song,
        "peigu": peigu,
        "raw": None,
    }


def _local_frame() -> pd.DataFrame:
    """模拟本地 Wine gbbq: cat1 旧值 + cat5 元数据 (dtypes 与真实文件一致)。"""
    df = pd.DataFrame(
        {
            "code": ["600519", "000001", "600519", "000001"],
            "market": [1, 0, 1, 0],
            "date": [20250626, 19900301, 20241220, 19910301],
            "category": [1, 1, 5, 5],
            "cash_div": [276.730011, 0.0, 31856.009766, 0.0],
            "split_ratio": [0.0, 1.0, 41412.820312, 0.0],
            "rights_ratio": [0.0, 0.0, 69745.507812, 0.0],
            "rights_price": [0.0, 3.56, 69745.507812, 0.0],
        }
    )
    return sync._cast_contract(df)


class TestOfficialCat1Frame:
    def test_filters_epoch_and_non_cat1_with_mapping(self):
        records = [
            _rec(),                                        # 正常 cat1
            _rec(date=18991230, fenhong=1.0),              # TDX 纪元行 → 滤
            _rec(date=20251219, cat=5, fenhong=999.0),     # 非 cat1 → 滤
            _rec(code="000001", date=19900301, fenhong=0.0, song=1.0, peigu=1.0, price=3.56),
        ]
        df = sync.official_cat1_frame(records)
        assert len(df) == 2
        assert list(df.columns) == sync.GBBQ_COLUMNS
        m = df[df["code"] == "600519"].iloc[0]
        assert m["cash_div"] == pytest.approx(280.24)
        assert m["split_ratio"] == pytest.approx(0.0)
        a = df[df["code"] == "000001"].iloc[0]
        assert a["rights_price"] == pytest.approx(3.56)
        assert a["rights_ratio"] == pytest.approx(1.0)

    def test_dtypes_match_real_parquet(self):
        df = sync.official_cat1_frame([_rec()])
        assert df["code"].iloc[0] == "600519"
        assert df["date"].dtype == "int64" and df["market"].dtype == "int64"
        assert df["cash_div"].dtype == "float64"

    def test_empty_records(self):
        df = sync.official_cat1_frame([])
        assert df.empty and list(df.columns) == sync.GBBQ_COLUMNS


class TestMergeFrames:
    def test_local_non_cat1_preserved_and_cat1_replaced(self):
        local = _local_frame()
        official = sync.official_cat1_frame(
            [
                _rec(date=20250626, fenhong=280.24),                     # 官方新值 (本地已有同键, 覆盖)
                _rec(date=20260626, fenhong=280.24),                     # 官方新增
                _rec(code="000001", date=19900301, fenhong=0.0, song=1.0, peigu=1.0, price=3.56),
            ]
        )
        final = sync.merge_frames(local, official)
        # 本地 cat5 两行原样保留 (官方置零无信息量)
        kept = final[final["category"] == 5]
        assert len(kept) == 2
        assert kept[kept["code"] == "600519"]["cash_div"].iloc[0] == pytest.approx(31856.009766)
        # 本地 cat1 20250626 被官方值覆盖; 20260626 新增; 官方 000001 19900301 覆盖
        c = final[(final["code"] == "600519") & (final["date"] == 20250626)].iloc[0]
        assert c["cash_div"] == pytest.approx(280.24)
        assert len(final[(final["code"] == "600519") & (final["date"] == 20260626)]) == 1

    def test_result_sorted_and_deduped(self):
        local = _local_frame()
        official = sync.official_cat1_frame([_rec(), _rec()])  # 同键两条 → 去重
        final = sync.merge_frames(local, official)
        keys = list(zip(final["code"], final["date"], final["category"]))
        assert len(keys) == len(set(keys))
        assert list(final["date"]) == sorted(final["date"])


class TestVerifyNoLoss:
    def test_passes_when_all_prev_keys_present(self):
        local = _local_frame()
        official = sync.official_cat1_frame(
            [
                _rec(date=20250626, fenhong=280.24),
                _rec(code="000001", date=19900301, fenhong=0.0, song=1.0, peigu=1.0, price=3.56),
            ]
        )
        final = sync.merge_frames(local, official)
        sync.verify_no_loss(local, final)  # 不抛即过

    def test_raises_listing_missing_keys(self):
        local = _local_frame()
        final = sync._cast_contract(pd.DataFrame(columns=sync.GBBQ_COLUMNS))
        with pytest.raises(ValueError, match="无损失守卫失败"):
            sync.verify_no_loss(local, final)


class TestWriteAtomic:
    def test_writes_parquet_with_matching_dtypes(self, tmp_path):
        out = tmp_path / "fq" / "gbbq.parquet"
        df = sync.official_cat1_frame([_rec()])
        sync.write_atomic(df, out)
        written = pd.read_parquet(out)
        assert list(written.columns) == sync.GBBQ_COLUMNS
        assert written["date"].dtype == "int64"

    def test_second_write_creates_bak_and_replaces(self, tmp_path):
        out = tmp_path / "gbbq.parquet"
        sync.write_atomic(sync.official_cat1_frame([_rec()]), out)
        sync.write_atomic(sync.official_cat1_frame([_rec(date=20251219)]), out)
        bak = out.with_suffix(".parquet.bak")
        assert bak.exists()
        old = pd.read_parquet(bak)
        assert old["date"].iloc[0] == 20260626  # bak 是第一版
        assert pd.read_parquet(out)["date"].iloc[0] == 20251219


class TestMain:
    def _patch_fetcher(self, monkeypatch, records):
        monkeypatch.setattr(sync, "fetch_official_records", lambda *a, **k: list(records))

    def test_full_flow_replaces_and_backs_up(self, tmp_path, capsys, monkeypatch):
        out = tmp_path / "fq" / "gbbq.parquet"
        sync.write_atomic(_local_frame(), out)  # 预置"本地"文件
        self._patch_fetcher(
            monkeypatch,
            [
                _rec(date=20250626, fenhong=280.24),
                _rec(date=20260626, fenhong=280.24),
                _rec(code="000001", date=19900301, fenhong=0.0, song=1.0, peigu=1.0, price=3.56),
            ],
        )
        rc = sync.main(["--output", str(out)])
        assert rc == 0
        final = pd.read_parquet(out)
        assert len(final) == 5  # 本地 cat5×2 + 官方 cat1×3 (20250626/000001 覆盖 + 20260626 新增)
        assert (final["category"] == 1).sum() == 3
        assert out.with_suffix(".parquet.bak").exists()
        assert "新增 1" in capsys.readouterr().out

    def test_superset_violation_fails_closed(self, tmp_path, monkeypatch):
        out = tmp_path / "gbbq.parquet"
        sync.write_atomic(_local_frame(), out)
        # 官方缺 000001 19900301 → 本地 cat1 键丢失 → 拒绝写
        self._patch_fetcher(monkeypatch, [_rec(fenhong=280.24)])
        rc = sync.main(["--output", str(out)])
        assert rc == 1
        # 真实文件未被半写 (仍是预置内容)
        assert pd.read_parquet(out)["date"].nunique() == 4

    def test_empty_official_rejects(self, tmp_path, monkeypatch):
        self._patch_fetcher(monkeypatch, [])
        rc = sync.main(["--output", str(tmp_path / "gbbq.parquet")])
        assert rc == 1

    def test_fetch_failure_returns_1(self, tmp_path, monkeypatch):
        def _boom(*a, **k):
            raise OSError("download failed")

        monkeypatch.setattr(sync, "fetch_official_records", _boom)
        assert sync.main(["--output", str(tmp_path / "gbbq.parquet")]) == 1
