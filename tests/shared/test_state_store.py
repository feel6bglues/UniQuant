from pathlib import Path
from unittest.mock import patch

import pytest

from uniquant.shared.state_store import DiskStateStore, StateStore


class TestDiskStateStore:
    """持久化状态存储单测套件"""

    def test_implements_protocol(self, tmp_path: Path):
        store = DiskStateStore(root_dir=tmp_path)
        assert isinstance(store, StateStore)

    def test_put_get_delete_lifecycle(self, tmp_path: Path):
        store = DiskStateStore(root_dir=tmp_path)
        key = "test_module_state"
        payload = {"status": "ACTIVE", "counter": 42, "symbols": ["600519", "000001"]}

        # 初始不存在
        assert store.exists(key) is False
        assert store.get(key) is None

        # 写入
        store.put(key, payload)
        assert store.exists(key) is True
        saved = store.get(key)
        assert saved == payload

        # 删除
        deleted = store.delete(key)
        assert deleted is True
        assert store.exists(key) is False
        assert store.get(key) is None

        # 重复删除返回 False
        assert store.delete(key) is False

    def test_invalid_key_validation(self, tmp_path: Path):
        store = DiskStateStore(root_dir=tmp_path)
        with pytest.raises(ValueError, match="Invalid state store key"):
            store.get("../bad_key")
        with pytest.raises(ValueError, match="Invalid state store key"):
            store.put("key with spaces", {"a": 1})
        with pytest.raises(ValueError, match="Invalid state store key"):
            store.delete("key/slash")

    def test_non_dict_data_raises_type_error(self, tmp_path: Path):
        store = DiskStateStore(root_dir=tmp_path)
        with pytest.raises(TypeError, match="State data must be a dict"):
            store.put("invalid_data", "string_data")  # type: ignore

    def test_corrupted_json_returns_none(self, tmp_path: Path):
        store = DiskStateStore(root_dir=tmp_path)
        key = "corrupted_state"
        bad_file = tmp_path / f"{key}.json"
        bad_file.write_text("{corrupted json not valid", encoding="utf-8")

        assert store.get(key) is None

    def test_atomic_write_failure_leaves_target_intact(self, tmp_path: Path):
        """故障注入: 模拟 os.replace 故障，断言原有状态未受损坏且无临时文件泄漏"""
        store = DiskStateStore(root_dir=tmp_path)
        key = "atomic_key"
        original_data = {"version": 1, "data": "stable"}
        store.put(key, original_data)

        new_data = {"version": 2, "data": "broken"}
        with patch("os.replace", side_effect=OSError("Disk write simulated fault")):
            with pytest.raises(OSError, match="Disk write simulated fault"):
                store.put(key, new_data)

        # 断言旧状态 100% 完整无损
        assert store.get(key) == original_data
        # 断言无泄漏的 .tmp 文件
        tmp_files = list(tmp_path.glob(".*.tmp.*"))
        assert len(tmp_files) == 0
