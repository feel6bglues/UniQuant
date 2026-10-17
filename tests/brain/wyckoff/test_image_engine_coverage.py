"""第九轮（2026-10-17）覆盖率补测：``brain/wyckoff/image_engine.py``。

``ImageEngine`` 负责扫描图表文件夹、提取视觉证据、识别时间周期与图像质量。
此前仅 13.7% 行覆盖（CI 口径）。本文件以**合成数据**覆盖其全部分支：

* 文件夹 / 显式文件列表扫描（存在性、格式、递归、目录跳过）；
* 标的推断四级优先级、时间周期识别、基础质量分级；
* 视觉证据聚合（最常见周期 / 质量、信任级别三分支、空清单早退）；
* 清单 JSON 落盘、``scan_and_extract``、``run`` 与 CLI ``main``。

所有文件 I/O 一律使用 pytest ``tmp_path``：写入的是极小的**伪图片字节**
（引擎只按后缀与文件大小判断，不真正解码图像）。
不触网、不读数据湖、不依赖 czsc / backtrader / mootdx / akshare / baostock。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from uniquant.brain.wyckoff import image_engine as ie
from uniquant.brain.wyckoff.image_engine import ImageEngine
from uniquant.brain.wyckoff.models import ImageEvidenceBundle


# ──────────────── helpers ────────────────


def _write_png(path: Path, size_bytes: int = 1024) -> Path:
    """写入一个**精确** ``size_bytes`` 字节的伪 PNG 文件（引擎按大小分级，不解码）。

    内容为 8 字节 PNG 头 + 零填充，总量恰为 ``size_bytes``。
    """
    header = b"\x89PNG\r\n\x1a\n"
    body = b"\x00" * max(size_bytes - len(header), 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((header + body)[:size_bytes].ljust(size_bytes, b"\x00"))
    return path


# ──────────────── __init__ ────────────────


class TestInit:
    def test_default_config_stores_constants(self) -> None:
        engine = ImageEngine()
        assert engine.supported_formats == ie.SUPPORTED_IMAGE_FORMATS
        assert engine.timeframe_patterns == ie.TIMEFRAME_PATTERNS
        assert engine.symbol_patterns == ie.SYMBOL_PATTERNS
        assert engine.config is None

    def test_explicit_config_is_kept(self) -> None:
        cfg = {"chart_dir": "/tmp/x"}
        assert ImageEngine(cfg).config == cfg


# ──────────────── scan_chart_directory ────────────────


class TestScanChartDirectory:
    def test_missing_directory_returns_warning(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope"
        manifest = ImageEngine().scan_chart_directory(str(missing))
        assert manifest["files"] == []
        assert len(manifest["warnings"]) == 1
        assert "文件夹不存在" in manifest["warnings"][0]

    def test_non_recursive_globs_only_top_level(self, tmp_path: Path) -> None:
        _write_png(tmp_path / "a_daily.png")
        _write_png(tmp_path / "sub" / "b_weekly.png")
        manifest = ImageEngine().scan_chart_directory(str(tmp_path), recursive=False)
        names = sorted(f["file_name"] for f in manifest["files"])
        assert names == ["a_daily.png"]

    def test_recursive_finds_nested_and_skips_dirs_and_other_formats(
        self, tmp_path: Path
    ) -> None:
        _write_png(tmp_path / "top.png")
        _write_png(tmp_path / "sub" / "nested_600519_daily.png")
        (tmp_path / "notes.txt").write_text("not an image", encoding="utf-8")
        # 一个目录本身会被 rglob 返回，但 is_file() 为假 → 必须被跳过
        (tmp_path / "empty_dir").mkdir()

        manifest = ImageEngine().scan_chart_directory(str(tmp_path), recursive=True)
        names = sorted(f["file_name"] for f in manifest["files"])
        assert names == ["nested_600519_daily.png", "top.png"]

        nested = next(f for f in manifest["files"] if f["file_name"].startswith("nested"))
        assert nested["relative_dir"] == "sub"
        assert nested["symbol"] == "600519.SH"
        assert nested["timeframe"] == "daily"

    def test_top_level_relative_dir_is_dot(self, tmp_path: Path) -> None:
        _write_png(tmp_path / "chart.png")
        manifest = ImageEngine().scan_chart_directory(str(tmp_path))
        assert manifest["files"][0]["relative_dir"] == "."

    def test_supported_formats_all_accepted(self, tmp_path: Path) -> None:
        for i, ext in enumerate(sorted(ie.SUPPORTED_IMAGE_FORMATS)):
            _write_png(tmp_path / f"file{i}{ext}")
        manifest = ImageEngine().scan_chart_directory(str(tmp_path))
        assert len(manifest["files"]) == len(ie.SUPPORTED_IMAGE_FORMATS)

    def test_target_symbol_propagated(self, tmp_path: Path) -> None:
        _write_png(tmp_path / "plain_chart.png")
        manifest = ImageEngine().scan_chart_directory(str(tmp_path), target_symbol="000002.SZ")
        assert manifest["files"][0]["symbol"] == "000002.SZ"


# ──────────────── scan_chart_files ────────────────


class TestScanChartFiles:
    def test_missing_file_warning(self, tmp_path: Path) -> None:
        manifest = ImageEngine().scan_chart_files([str(tmp_path / "absent.png")])
        assert manifest["files"] == []
        assert "文件不存在" in manifest["warnings"][0]

    def test_directory_path_warning(self, tmp_path: Path) -> None:
        target = tmp_path / "600519"
        target.mkdir()
        manifest = ImageEngine().scan_chart_files([str(target)])
        assert manifest["files"] == []
        assert "不是文件" in manifest["warnings"][0]

    def test_unsupported_suffix_warning(self, tmp_path: Path) -> None:
        bad = tmp_path / "chart.bmp"
        bad.write_text("x", encoding="utf-8")
        manifest = ImageEngine().scan_chart_files([str(bad)])
        assert manifest["files"] == []
        assert "不支持格式" in manifest["warnings"][0]

    def test_valid_file_is_described(self, tmp_path: Path) -> None:
        png = _write_png(tmp_path / "600519_daily.png", size_bytes=200 * 1024)
        manifest = ImageEngine().scan_chart_files([str(png)])
        assert len(manifest["files"]) == 1
        info = manifest["files"][0]
        assert info["file_name"] == "600519_daily.png"
        assert info["symbol"] == "600519.SH"
        assert info["timeframe"] == "daily"
        assert info["image_quality"] == "medium"
        assert info["relative_dir"] == tmp_path.name

    def test_mixed_batch_collects_warnings_and_files(self, tmp_path: Path) -> None:
        good = _write_png(tmp_path / "ok_weekly.png")
        bad = tmp_path / "bad.gif"
        bad.write_text("x", encoding="utf-8")
        manifest = ImageEngine().scan_chart_files(
            [str(tmp_path / "missing.png"), str(bad), str(good)]
        )
        assert len(manifest["files"]) == 1
        assert len(manifest["warnings"]) == 2


# ──────────────── _get_modified_time ────────────────


class TestGetModifiedTime:
    def test_formats_existing_file(self, tmp_path: Path) -> None:
        png = _write_png(tmp_path / "a.png")
        stamp = ImageEngine()._get_modified_time(png)
        # "%Y-%m-%d %H:%M:%S"
        assert len(stamp) == 19 and stamp[4] == "-" and stamp[13] == ":"

    def test_missing_file_returns_unknown(self, tmp_path: Path) -> None:
        stamp = ImageEngine()._get_modified_time(tmp_path / "absent.png")
        assert stamp == "unknown"


# ──────────────── _infer_symbol ────────────────


class TestInferSymbol:
    @pytest.mark.parametrize(
        ("file_name", "expected"),
        [
            ("000001.SZ.png", "000001.SZ"),  # 优先级1：完整带后缀，原样返回
            ("600519_daily.png", "600519.SH"),  # 6 开头 → SH
            ("000001_chart.png", "000001.SZ"),  # 0 开头 → SZ
            ("300750_weekly.png", "300750.SZ"),  # 3 开头 → SZ
            ("900001_chart.png", "900001"),  # 6 位但非 6/0/3 → 原样数字
        ],
    )
    def test_priority_one_filename(self, file_name: str, expected: str) -> None:
        assert ImageEngine()._infer_symbol(file_name, "irrelevant") == expected

    @pytest.mark.parametrize(
        ("parent_dir", "expected"),
        [
            ("600519", "600519.SH"),
            ("300750", "300750.SZ"),
            ("2024-05-01_600519_sh", "600519.SH"),  # 目录含 6 位数字
            ("600519.SH", "600519.SH"),  # 完整后缀 → 原样
            ("900001", "900001"),  # 6 位非 6/0/3 → 原样
        ],
    )
    def test_priority_two_parent_dir(self, parent_dir: str, expected: str) -> None:
        assert ImageEngine()._infer_symbol("plain_chart.png", parent_dir) == expected

    def test_filename_beats_parent_dir(self) -> None:
        got = ImageEngine()._infer_symbol("600519_x.png", "300750")
        assert got == "600519.SH"

    def test_priority_three_explicit_symbol(self) -> None:
        got = ImageEngine()._infer_symbol("plain.png", "no_code_here", "000002.SZ")
        assert got == "000002.SZ"

    def test_priority_four_unassigned(self) -> None:
        got = ImageEngine()._infer_symbol("plain.png", "no_code_here")
        assert got == "unassigned"


# ──────────────── _infer_timeframe ────────────────


class TestInferTimeframe:
    @pytest.mark.parametrize(
        ("file_name", "expected"),
        [
            ("chart_weekly.png", "weekly"),
            ("chart_周线.png", "weekly"),
            ("chart_week.png", "weekly"),
            ("chart_daily.png", "daily"),
            ("chart_日线.png", "daily"),
            ("chart_60m.png", "60m"),
            ("chart_60min.png", "60m"),
            ("chart_30m.png", "30m"),
            ("chart_15m.png", "15m"),
            ("chart_5m.png", "5m"),
            ("chart_plain.png", "unknown_tf"),
        ],
    )
    def test_patterns(self, file_name: str, expected: str) -> None:
        assert ImageEngine()._infer_timeframe(file_name) == expected

    def test_case_insensitive(self) -> None:
        assert ImageEngine()._infer_timeframe("CHART_WEEKLY.PNG") == "weekly"


# ──────────────── _assess_image_quality_basic ────────────────


class TestAssessImageQualityBasic:
    @pytest.mark.parametrize(
        ("size_bytes", "expected"),
        [
            (600 * 1024, "high"),
            (200 * 1024, "medium"),
            (30 * 1024, "low"),
            (1024, "unusable"),
            (20 * 1024, "unusable"),  # 恰好 20KB：非 > 20KB → unusable
            (20 * 1024 + 1, "low"),
            (500 * 1024, "medium"),  # 恰好 500KB：非 > 500KB → medium
        ],
    )
    def test_size_tiers(self, tmp_path: Path, size_bytes: int, expected: str) -> None:
        png = _write_png(tmp_path / "q.png", size_bytes=size_bytes)
        assert png.stat().st_size == size_bytes
        assert ImageEngine()._assess_image_quality_basic(png) == expected

    def test_stat_error_falls_back_to_medium(self, tmp_path: Path) -> None:
        assert ImageEngine()._assess_image_quality_basic(tmp_path / "absent.png") == "medium"


# ──────────────── extract_visual_evidence ────────────────


class TestExtractVisualEvidence:
    def _file(self, **overrides) -> dict:
        base = {
            "file_path": "/x/a.png",
            "file_name": "a.png",
            "relative_dir": ".",
            "modified_time": "2026-10-17 00:00:00",
            "symbol": "600519.SH",
            "timeframe": "daily",
            "image_quality": "high",
        }
        base.update(overrides)
        return base

    def test_empty_manifest_early_return(self) -> None:
        bundle = ImageEngine().extract_visual_evidence({"files": []})
        assert isinstance(bundle, ImageEvidenceBundle)
        assert bundle.files == []
        assert bundle.detected_timeframe == "unknown_tf"
        assert bundle.image_quality == "unusable"
        assert bundle.trust_level == "low"

    def test_missing_files_key_early_return(self) -> None:
        bundle = ImageEngine().extract_visual_evidence({})
        assert bundle.files == []
        assert bundle.trust_level == "low"

    def test_high_trust_when_known_timeframe(self) -> None:
        manifest = {
            "files": [
                self._file(timeframe="daily", image_quality="high"),
                self._file(timeframe="daily", image_quality="medium"),
                self._file(timeframe="weekly", image_quality="medium"),
            ]
        }
        bundle = ImageEngine().extract_visual_evidence(manifest)
        assert bundle.detected_timeframe == "daily"  # 最常见
        assert bundle.image_quality == "high"  # quality_order 优先 high
        assert bundle.trust_level == "high"
        assert bundle.detected_timeframes == ["daily"]
        assert bundle.manifest is not None
        assert bundle.manifest.total_count == 3
        assert bundle.overall_image_quality == "high"

    def test_medium_trust_when_low_quality(self) -> None:
        manifest = {"files": [self._file(image_quality="low")]}
        bundle = ImageEngine().extract_visual_evidence(manifest)
        assert bundle.image_quality == "low"
        assert bundle.trust_level == "low"  # low → trust low

    def test_unusable_quality_maps_to_medium_trust(self) -> None:
        manifest = {"files": [self._file(image_quality="unusable")]}
        bundle = ImageEngine().extract_visual_evidence(manifest)
        assert bundle.image_quality == "unusable"
        assert bundle.trust_level == "medium"  # else 分支

    def test_unknown_timeframe_blocks_high_trust(self) -> None:
        manifest = {"files": [self._file(timeframe="unknown_tf", image_quality="high")]}
        bundle = ImageEngine().extract_visual_evidence(manifest)
        assert bundle.detected_timeframe == "unknown_tf"
        assert bundle.trust_level == "medium"  # high 质量但周期未知 → else
        assert bundle.detected_timeframes == []

    def test_items_use_get_defaults(self) -> None:
        # 仅提供必填键 → 所有可选字段走 .get 默认值
        manifest = {"files": [{"file_path": "/x/b.png", "file_name": "b.png"}]}
        bundle = ImageEngine().extract_visual_evidence(manifest)
        item = bundle.manifest.files[0]
        assert item.relative_dir == ""
        assert item.modified_time == ""
        assert item.symbol == "unassigned"
        assert item.inferred_timeframe == "unknown_tf"
        assert item.image_quality == "medium"


# ──────────────── generate_chart_manifest_json ────────────────


class TestGenerateChartManifestJson:
    def test_creates_parent_dirs_and_writes_json(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "deep" / "manifest.json"
        manifest = {"files": [{"file_name": "a.png"}], "warnings": []}
        ImageEngine().generate_chart_manifest_json(manifest, str(out))
        assert out.exists()
        import json

        assert json.loads(out.read_text(encoding="utf-8")) == manifest


# ──────────────── scan_and_extract ────────────────


class TestScanAndExtract:
    def test_without_output_path(self, tmp_path: Path) -> None:
        _write_png(tmp_path / "600519_daily.png")
        evidence, manifest = ImageEngine().scan_and_extract(str(tmp_path))
        assert len(manifest["files"]) == 1
        assert evidence.files
        assert evidence.detected_timeframe == "daily"

    def test_with_output_manifest_written(self, tmp_path: Path) -> None:
        _write_png(tmp_path / "600519_weekly.png", size_bytes=600 * 1024)
        out = tmp_path / "manifest.json"
        evidence, manifest = ImageEngine().scan_and_extract(
            str(tmp_path), "600519.SH", str(out)
        )
        assert out.exists()
        assert evidence.trust_level == "high"
        assert manifest["files"][0]["symbol"] == "600519.SH"


# ──────────────── run ────────────────


class TestRun:
    def test_chart_files_branch(self, tmp_path: Path) -> None:
        png = _write_png(tmp_path / "600519_daily.png")
        bundle = ImageEngine().run(chart_files=[str(png)])
        assert bundle.files == [str(png)]

    def test_chart_dir_branch(self, tmp_path: Path) -> None:
        _write_png(tmp_path / "600519_daily.png")
        bundle = ImageEngine().run(chart_dir=str(tmp_path))
        assert len(bundle.files) == 1

    def test_no_input_returns_default_bundle(self) -> None:
        bundle = ImageEngine().run()
        assert isinstance(bundle, ImageEvidenceBundle)
        assert bundle.files == []

    def test_chart_files_precedence_over_dir(self, tmp_path: Path) -> None:
        png = _write_png(tmp_path / "only_file.png")
        bundle = ImageEngine().run(chart_files=[str(png)], chart_dir=str(tmp_path))
        assert bundle.files == [str(png)]


# ──────────────── CLI main ────────────────


class TestCliMain:
    def test_main_runs_end_to_end(self, tmp_path: Path, monkeypatch) -> None:
        chart_dir = tmp_path / "charts"
        _write_png(chart_dir / "600519_daily.png")
        out_manifest = tmp_path / "out" / "manifest.json"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "image_engine",
                "--chart-dir",
                str(chart_dir),
                "--symbol",
                "600519.SH",
                "--output-manifest",
                str(out_manifest),
            ],
        )
        ie.main()
        assert out_manifest.exists()
