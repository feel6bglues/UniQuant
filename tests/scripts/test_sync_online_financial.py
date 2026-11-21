"""sync_online_financial 单元测试 (通达信官方财务数据在线同步, 第二十二轮)。

背景: mootdx.affair 走通达信官方 HTTP 文件分发 (tdxfin/gpcw*.zip, 与已死的
TCP 行情协议无关), 2026-11-21 实测索引/下载/解析全通, 且项目
``TDXFinancialImporter._parse_gpcw_file`` 可直接吃下载文件 (与 Wine 本地
gpcw*.dat 同格式)。

全部用例注入假索引/假下载器/假导入器, 不触网、不读真实湖 (CI 安全)。
"""

import hashlib
import io
import zipfile

import pytest

import scripts.maintenance.sync_online_financial as sync


def _zip_bytes(date: str = "20260930", payload: bytes = b"X" * 64) -> bytes:
    """确定性 zip 字节流 (固定 ZipInfo 时间戳, MD5 可预计算)。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo(f"gpcw{date}.dat", date_time=(2026, 10, 30, 0, 0, 0)), payload)
    return buf.getvalue()


def _entry(date: str, size: int = 5_490_000) -> dict:
    """带正确 zip 文件 MD5 的官方索引条目 (校验对象是 zip 整体而非载荷)。"""
    return {
        "filename": f"gpcw{date}.zip",
        "hash": hashlib.md5(_zip_bytes(date)).hexdigest(),
        "filesize": size,
    }


def _index() -> list:
    return [
        _entry("20260930"),
        _entry("20260630"),
        _entry("20260331"),
        {"filename": "gpcw20261231.zip", "hash": "hash-future", "filesize": 164},  # 占位预告
        {"filename": "other.zip", "hash": "h", "filesize": 999_999},  # 非 gpcw 噪声
    ]


class _FakeDownloader:
    """记录调用并写出确定性 zip 字节流 (MD5 稳定, 导入器被 mock)。"""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, downdir, filename: str) -> bool:
        self.calls.append((str(downdir), filename))
        date = sync.GPCW_ZIP_RE.match(filename).group(1)
        (downdir / filename).write_bytes(_zip_bytes(date))
        return True


class _FakeImporter:
    """捕获构造参数与 import_batch 调用, 返回固定计数。"""

    last_instance: "_FakeImporter | None" = None

    def __init__(self, tdx_dir, output_dir, stock_codes_file):
        self.tdx_dir = tdx_dir
        self.output_dir = output_dir
        self.stock_codes_file = stock_codes_file
        self.fingerprint = None
        self.batch_args = None
        _FakeImporter.last_instance = self

    def import_batch(self, force=False, **kwargs):
        self.batch_args = {"force": force}
        return (1, 0, 0)


@pytest.fixture(autouse=True)
def _fake_importer(monkeypatch):
    monkeypatch.setattr(sync, "TDXFinancialImporter", _FakeImporter)
    _FakeImporter.last_instance = None


class TestFetchIndex:
    def test_filters_non_dict_and_non_gpcw_entries(self):
        raw = [1, "x", {"filename": "gpcw20260930.zip", "filesize": 100}, {"bad": 1}]
        out = sync.fetch_index(lambda: raw)
        assert out == [{"filename": "gpcw20260930.zip", "filesize": 100}]

    def test_default_uses_mootdx_affair(self, monkeypatch):
        import sys as _sys
        import types

        called = []

        class _FakeAffair:
            @staticmethod
            def files():
                called.append(1)
                return [{"filename": "gpcw20260331.zip", "filesize": 100}]

        monkeypatch.setitem(_sys.modules, "mootdx.affair", types.SimpleNamespace(Affair=_FakeAffair))
        out = sync.fetch_index()
        assert called and out == [{"filename": "gpcw20260331.zip", "filesize": 100}]


class TestSelectEntries:
    def test_filters_placeholder_and_noise_sorted_desc(self):
        out = sync.select_entries(_index(), latest=99)
        assert [e["filename"] for e in out] == ["gpcw20260930.zip", "gpcw20260630.zip", "gpcw20260331.zip"]

    def test_latest_n_takes_newest(self):
        out = sync.select_entries(_index(), latest=2)
        assert [e["filename"] for e in out] == ["gpcw20260930.zip", "gpcw20260630.zip"]

    def test_want_all_returns_everything_real(self):
        assert len(sync.select_entries(_index(), want_all=True)) == 3

    def test_empty_index(self):
        assert sync.select_entries([], latest=1) == []


class TestDownloadAndExtract:
    def test_downloads_verifies_and_extracts(self, tmp_path):
        dl = _FakeDownloader()
        entry = _entry("20260930")
        dat = sync.download_and_extract(entry, tmp_path / "cache", tmp_path / "staging" / "vipdoc" / "cw", dl)
        assert dl.calls == [(str(tmp_path / "cache"), "gpcw20260930.zip")]
        assert dat.name == "gpcw20260930.dat"
        assert dat.exists()

    def test_cache_hit_skips_download_but_still_verifies_md5(self, tmp_path):
        dl = _FakeDownloader()
        entry = _entry("20260930")
        first = sync.download_and_extract(entry, tmp_path, tmp_path / "cw", dl)
        second = sync.download_and_extract(entry, tmp_path, tmp_path / "cw", dl)
        assert len(dl.calls) == 1  # 缓存命中
        assert first == second

    def test_md5_mismatch_raises_with_filename(self, tmp_path):
        dl = _FakeDownloader()
        entry = dict(_entry("20260930"), hash="0" * 32)
        with pytest.raises(ValueError, match="gpcw20260930.zip"):
            sync.download_and_extract(entry, tmp_path, tmp_path / "cw", dl)


class TestRunImport:
    def test_builds_importer_with_staging_and_isolated_fingerprint(self, tmp_path):
        counts = sync.run_import(
            staging_root=tmp_path / "staging",
            output_dir=tmp_path / "lake_financial",
            stock_codes_file=tmp_path / "all_stock_codes.csv",
            fingerprint_path=tmp_path / "cache" / "fp.json",
        )
        assert counts == (1, 0, 0)
        imp = _FakeImporter.last_instance
        assert imp.tdx_dir == tmp_path / "staging"
        assert imp.output_dir == tmp_path / "lake_financial"
        assert imp.fingerprint.filepath == tmp_path / "cache" / "fp.json"  # 指纹隔离
        assert imp.batch_args == {"force": False}


class TestMain:
    def _patch_index(self, monkeypatch):
        monkeypatch.setattr(sync, "fetch_index", lambda *a, **k: _index())

    def test_dry_run_no_download_no_import(self, tmp_path, capsys, monkeypatch):
        self._patch_index(monkeypatch)
        dl = _FakeDownloader()
        rc = sync.main([
            "--dry-run", "--latest", "1",
            "--cache-dir", str(tmp_path), "--output-dir", str(tmp_path / "lake"),
            "--stock-codes", str(tmp_path / "codes.csv"),
        ])
        assert rc == 0
        assert dl.calls == []
        assert _FakeImporter.last_instance is None
        assert "gpcw20260930.zip" in capsys.readouterr().out

    def test_end_to_end_with_fakes(self, tmp_path, monkeypatch):
        self._patch_index(monkeypatch)
        extracted: list[str] = []

        def _fake_extract(entry, cache_dir, staging_cw_dir, downloader=None):
            extracted.append(entry["filename"])
            return staging_cw_dir / entry["filename"].replace(".zip", ".dat")

        monkeypatch.setattr(sync, "download_and_extract", _fake_extract)
        rc = sync.main([
            "--latest", "1",
            "--cache-dir", str(tmp_path / "cache"),
            "--output-dir", str(tmp_path / "lake"),
            "--stock-codes", str(tmp_path / "codes.csv"),
        ])
        assert rc == 0
        assert extracted == ["gpcw20260930.zip"]
        imp = _FakeImporter.last_instance
        assert imp is not None
        assert imp.tdx_dir == tmp_path / "cache" / "staging"
        assert imp.output_dir == tmp_path / "lake"
        assert imp.batch_args == {"force": False}

    def test_index_failure_returns_1(self, monkeypatch, tmp_path):
        def _boom(*a, **k):
            raise OSError("network down")

        monkeypatch.setattr(sync, "fetch_index", _boom)
        rc = sync.main(["--cache-dir", str(tmp_path), "--output-dir", str(tmp_path)])
        assert rc == 1
