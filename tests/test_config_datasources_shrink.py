"""WS-C: config `data_sources` 五源收缩 (D1/Step3 预注册裁决) — TDD 契约。

预注册验收 (第二十轮更新: tdxdata 新协议在线源接线, mootdx_online 转废弃):
  ① config 可加载且 data_sources.sources 恰含三项
     (mootdx_local / mootdx_online / tdxdata_online);
  ② mootdx_local.enabled is True; tdxdata_online.enabled is True (新协议在线通道);
     mootdx_online.enabled is False (旧协议 bars 2026-09 被服务端拒绝, 已废弃);
  ③ ConfigValidator 对收缩后的 config 校验通过 (data_sources 相关 0 错误);
  ④ 已删源名 (sina/tencent/ths/eastmoney/baostock/efinance 及三个 NOT YET
     IMPLEMENTED 占位源) 不再出现在 config.yaml 的 data_sources 段文本中。

范围声明: 只改 config/config.yaml (data_sources 段) + config_validator.py;
源文件剪除属 Step4, 不在本组范围。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uniquant.shared.config_loader import get_config
from uniquant.shared.config_validator import ConfigValidator

CONFIG_YAML = Path(__file__).resolve().parent.parent / "config" / "config.yaml"

EXPECTED_SOURCES = {"mootdx_local", "mootdx_online", "tdxdata_online"}

# Step3 已删源名 — 均不得再出现在 data_sources 段
REMOVED_SOURCE_TOKENS = [
    "StockDataSource",
    "IndexDataSource",
    "EtfDataSource",
    "BaoStockSource",
    "SinaSource",
    "TencentSource",
    "EastmoneySource",
    "EfinanceSource",
    "ThsSource",
    "sina",
    "tencent",
    "baostock",
    "eastmoney",
    "efinance",
    "ths",
    "data_types",
    "industry_concept",
]


def _data_sources_section_text() -> str:
    """截取 config.yaml 顶层 `data_sources:` 段到下一个顶层键为止。"""
    lines = CONFIG_YAML.read_text(encoding="utf-8").splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("data_sources:"):
            start = i
            break
    assert start is not None, "config.yaml 缺少 data_sources 顶层段"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if line and not line[0].isspace() and not line.startswith("#"):
            end = j
            break
    return "\n".join(lines[start:end])


@pytest.fixture(scope="module")
def config():
    return get_config()


# ① 收缩结果: sources 恰含三项 (两 mootdx + tdxdata 在线源)
def test_sources_shrunk_to_two_mootdx_entries(config):
    sources = config.get("data_sources", {}).get("sources", {})
    assert isinstance(sources, dict), "data_sources.sources 应为 dict (源名→配置体)"
    assert set(sources.keys()) == EXPECTED_SOURCES


# ② 启用状态: 本地源启用, tdxdata 新协议在线源启用, 旧协议在线源废弃
def test_mootdx_local_enabled_online_disabled(config):
    sources = config.get("data_sources", {}).get("sources", {})
    assert sources["mootdx_local"]["enabled"] is True
    assert sources["mootdx_online"]["enabled"] is False
    assert sources["tdxdata_online"]["enabled"] is True


# ③ 收缩后 config 通过 ConfigValidator
def test_config_validator_passes_after_shrink(config):
    errors = ConfigValidator(config).validate_all()
    assert errors == [], f"收缩后 config 校验应通过, 实得: {errors}"


# ③b 已删源名不出现在 data_sources 段文本
def test_removed_source_names_absent_from_data_sources_section():
    section = _data_sources_section_text()
    for token in REMOVED_SOURCE_TOKENS:
        assert token not in section, (
            f"已删源名/死配置 '{token}' 仍出现在 data_sources 段"
        )


# ③c 保留源的 class 路径必须可导入 (防止收缩后填了不存在的类)
def test_retained_source_classes_importable(config):
    import importlib

    sources = config.get("data_sources", {}).get("sources", {})
    for name, body in sources.items():
        class_path = body.get("class")
        assert class_path, f"{name} 缺少 class 字段"
        module_name, _, attr = class_path.rpartition(".")
        assert module_name, f"{name} class 路径应为 'pkg.mod.Class' 形式"
        module = importlib.import_module(module_name)
        assert hasattr(module, attr), f"{name} class 路径 {class_path} 无法解析"
