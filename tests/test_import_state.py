import json

from uniquant.shared.import_state import ImportStateManager, ThreadSafeImportCounter


class TestThreadSafeImportCounter:
    def test_counter_tracks_progress(self):
        counter = ThreadSafeImportCounter()
        counter.set_total(3)
        counter.increment_success()
        counter.increment_failed()

        assert counter.get_progress() == (1, 1, 2, 3)
        assert counter.get_stats() == {
            "success": 1,
            "failed": 1,
            "total": 3,
            "processed": 2,
        }


class TestImportStateManager:
    def test_loads_default_state_when_missing_or_invalid(self, tmp_path):
        manager = ImportStateManager(tmp_path)
        assert manager.get_stats() == {"total": 0, "success": 0, "failed": 0}

        state_file = tmp_path / "import_state.json"
        state_file.write_text("{bad json", encoding="utf-8")

        invalid = ImportStateManager(tmp_path)
        assert invalid.get_stats() == {"total": 0, "success": 0, "failed": 0}

    def test_update_state_and_read_stats(self, tmp_path):
        source_file = tmp_path / "source.txt"
        source_file.write_text("payload", encoding="utf-8")

        manager = ImportStateManager(tmp_path)
        manager.update_state("000001", "sz", source_file, 12, "2026-04-01", status="success")

        state = manager.get_state("000001", "sz")
        assert state is not None
        assert state["records"] == 12
        assert state["last_data"] == "2026-04-01"
        assert state["status"] == "success"
        assert manager.get_stats() == {"total": 1, "success": 1, "failed": 0}

        saved = json.loads((tmp_path / "import_state.json").read_text(encoding="utf-8"))
        assert "000001.SZ" in saved["fingerprints"]

    def test_is_import_needed_for_new_failed_missing_and_changed_files(self, tmp_path):
        source_file = tmp_path / "source.txt"
        source_file.write_text("v1", encoding="utf-8")

        manager = ImportStateManager(tmp_path)
        assert manager.is_import_needed("000001", "SZ", source_file) is True

        manager.update_state("000001", "SZ", source_file, 1, "2026-04-01")
        assert manager.is_import_needed("000001", "SZ", source_file) is False

        manager.update_state("000002", "SZ", source_file, 1, "2026-04-01", status="failed")
        assert manager.is_import_needed("000002", "SZ", source_file) is True

        missing_file = tmp_path / "missing.txt"
        manager.update_state("000003", "SZ", missing_file, 1, "2026-04-01")
        assert manager.is_import_needed("000003", "SZ", missing_file) is False

        source_file.write_text("version 2 with more bytes", encoding="utf-8")
        assert manager.is_import_needed("000001", "SZ", source_file) is True

    def test_clear_state_and_clear_all(self, tmp_path):
        source_file = tmp_path / "source.txt"
        source_file.write_text("payload", encoding="utf-8")

        manager = ImportStateManager(tmp_path)
        manager.update_state("000001", "SZ", source_file, 1, "2026-04-01")
        manager.update_state("000002", "SH", source_file, 2, "2026-04-02", status="failed")

        manager.clear_state("000001", "SZ")
        assert manager.get_state("000001", "SZ") is None
        assert manager.get_stats() == {"total": 1, "success": 0, "failed": 1}

        manager.clear_all()
        assert manager.get_stats() == {"total": 0, "success": 0, "failed": 0}

    def test_handles_oserror_when_file_stat_fails(self, tmp_path, monkeypatch):
        source_file = tmp_path / "source.txt"
        source_file.write_text("payload", encoding="utf-8")
        manager = ImportStateManager(tmp_path)
        manager.update_state("000001", "SZ", source_file, 1, "2026-04-01")

        class _BrokenPath:
            def exists(self):
                return True

            def stat(self):
                raise OSError("stat failed")

        broken_source = _BrokenPath()
        assert manager.is_import_needed("000001", "SZ", broken_source) is True
