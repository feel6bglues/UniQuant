"""P2-3 证据链可复现性: `scripts/maintenance/evidence_manifest.py` 契约测试.

背景（详见 docs/analysis/POST_SIMPLIFICATION_ARCHITECTURE_TRADING_EVALUATION_20261016.md §3 P2-3）：
`data/lake/` 与 `results/` 被 gitignore，实证结论一度只在开发机存在。现以
`results/.gitignore` 白名单 + `results/EVIDENCE_MANIFEST.json` 内容哈希账本闭环，
并由 CI 校验。本文件锁定哈希账本的构建/校验语义，防止"漂移却不报错"。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.maintenance import evidence_manifest as em  # noqa: E402


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """Structure: <tmp>/{results,tests/benchmark}/... with git ls-files stubbed."""
    (tmp_path / "results" / "factor_mining").mkdir(parents=True)
    (tmp_path / "results" / "factor_mining" / "p1.json").write_text('{"a": 1}\n')
    (tmp_path / "results" / "canslim").mkdir(parents=True)
    (tmp_path / "results" / "canslim" / "gate.json").write_text('{"b": 2}\n')
    # Not evidence (ignored by suffix filter).
    (tmp_path / "results" / "notes.txt").write_text("noise\n")

    tracked = [
        "results/factor_mining/p1.json",
        "results/canslim/gate.json",
        "results/notes.txt",
    ]
    monkeypatch.setattr(em, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(em, "MANIFEST_PATH", tmp_path / "results" / "EVIDENCE_MANIFEST.json")
    monkeypatch.setattr(em, "_git_ls_files", lambda roots: list(tracked))
    monkeypatch.setattr(em, "_git_head", lambda: "deadbeef" * 5)
    return tmp_path


class TestEvidenceFilter:
    def test_evidence_suffixes_only(self):
        assert em._is_evidence("results/factor_mining/p1.json")
        assert em._is_evidence("results/x/y.csv")
        assert em._is_evidence("results/x/y.md")
        assert em._is_evidence("results/x/y.parquet")

    def test_non_evidence_rejected(self):
        assert not em._is_evidence("results/notes.txt")
        assert not em._is_evidence("results/log.log")

    def test_manifest_itself_excluded(self):
        assert not em._is_evidence("results/EVIDENCE_MANIFEST.json")


class TestBuild:
    def test_build_covers_only_evidence(self, fake_repo):
        manifest = em.build_manifest()
        assert set(manifest["files"]) == {
            "results/canslim/gate.json",
            "results/factor_mining/p1.json",
        }
        assert manifest["file_count"] == 2
        assert manifest["git_head"] == "deadbeef" * 5
        assert manifest["roots"] == list(em.EVIDENCE_ROOTS)

    def test_digest_matches_hashlib(self, fake_repo):
        manifest = em.build_manifest()
        expected = hashlib.sha256(b'{"a": 1}\n').hexdigest()
        assert manifest["files"]["results/factor_mining/p1.json"]["sha256"] == expected
        assert manifest["files"]["results/factor_mining/p1.json"]["size"] == 9

    def test_total_bytes(self, fake_repo):
        manifest = em.build_manifest()
        assert manifest["total_bytes"] == sum(
            int(entry["size"]) for entry in manifest["files"].values()
        )

    def test_sorting_is_deterministic(self, fake_repo):
        manifest = em.build_manifest()
        assert list(manifest["files"]) == sorted(manifest["files"])

    def test_write_and_load_roundtrip(self, fake_repo):
        manifest = em.build_manifest()
        path = em.write_manifest(manifest)
        assert path.exists()
        assert em.load_manifest()["file_count"] == manifest["file_count"]

    def test_written_json_is_utf8_and_indented(self, fake_repo):
        em.write_manifest(em.build_manifest())
        text = em.MANIFEST_PATH.read_text(encoding="utf-8")
        assert text.endswith("\n")
        # Round-trips through the JSON parser cleanly.
        assert json.loads(text)["version"] == 1


class TestVerify:
    def test_clean_tree_passes(self, fake_repo):
        em.write_manifest(em.build_manifest())
        ok, problems = em.verify_manifest()
        assert ok, problems

    def test_missing_manifest_fails(self, fake_repo):
        ok, problems = em.verify_manifest()
        assert not ok
        assert any("manifest not found" in p for p in problems)

    def test_hash_drift_detected(self, fake_repo):
        em.write_manifest(em.build_manifest())
        (fake_repo / "results" / "factor_mining" / "p1.json").write_text('{"a": 999}\n')
        ok, problems = em.verify_manifest()
        assert not ok
        assert any("HASH DRIFT" in p or "SIZE DRIFT" in p for p in problems)

    def test_same_size_content_change_detected(self, fake_repo):
        """Size-equal edits must still fail on the digest (the whole point)."""
        em.write_manifest(em.build_manifest())
        target = fake_repo / "results" / "canslim" / "gate.json"
        target.write_text('{"b": 3}\n')  # byte-for-byte same length as {"b": 2}
        assert target.stat().st_size == 9
        ok, problems = em.verify_manifest()
        assert not ok
        assert any("HASH DRIFT" in p for p in problems)
        # A size-only check would have passed; assert the digest is what caught it.
        assert not any("SIZE DRIFT" in p for p in problems)

    def test_missing_file_detected(self, fake_repo):
        em.write_manifest(em.build_manifest())
        (fake_repo / "results" / "canslim" / "gate.json").unlink()
        ok, problems = em.verify_manifest()
        assert not ok
        assert any(p.startswith("MISSING:") for p in problems)

    def test_missing_file_allowed_when_opted_in(self, fake_repo):
        em.write_manifest(em.build_manifest())
        (fake_repo / "results" / "canslim" / "gate.json").unlink()
        ok, problems = em.verify_manifest(allow_missing=True)
        assert ok, problems

    def test_new_untracked_evidence_detected(self, fake_repo, monkeypatch):
        em.write_manifest(em.build_manifest())
        (fake_repo / "results" / "factor_mining" / "p2.json").write_text('{"c": 3}\n')
        tracked = [
            "results/factor_mining/p1.json",
            "results/canslim/gate.json",
            "results/notes.txt",
            "results/factor_mining/p2.json",
        ]
        monkeypatch.setattr(em, "_git_ls_files", lambda roots: list(tracked))
        ok, problems = em.verify_manifest()
        assert not ok
        assert any("UNTRACKED IN MANIFEST" in p for p in problems)

    def test_malformed_files_section(self, fake_repo):
        em.MANIFEST_PATH.write_text(json.dumps({"files": []}))
        ok, problems = em.verify_manifest()
        assert not ok
        assert any("malformed" in p for p in problems)


class TestCli:
    def test_build_mode_exit_zero(self, fake_repo, capsys):
        assert em.main(["build"]) == 0
        assert em.MANIFEST_PATH.exists()
        assert "Wrote" in capsys.readouterr().out

    def test_verify_mode_exit_zero_when_clean(self, fake_repo, capsys):
        em.main(["build"])
        assert em.main(["verify"]) == 0
        assert "no drift" in capsys.readouterr().out

    def test_verify_mode_exit_one_on_drift(self, fake_repo, capsys):
        em.main(["build"])
        (fake_repo / "results" / "canslim" / "gate.json").write_text('{"b": 7}\n')
        assert em.main(["verify"]) == 1
        assert "DRIFT" in capsys.readouterr().err


class TestRealRepoIntegration:
    """Guards against the manifest silently covering nothing in the real repo."""

    def test_roots_exist(self):
        for root in em.EVIDENCE_ROOTS:
            assert (PROJECT_ROOT / root).exists(), root

    def test_real_manifest_matches_real_tree(self):
        """The committed ledger must match the committed evidence (CI gate parity)."""
        if not em.MANIFEST_PATH.exists():
            pytest.skip("manifest not built yet")
        ok, problems = em.verify_manifest()
        assert ok, "\n".join(problems)

    def test_real_manifest_is_non_trivial(self):
        if not em.MANIFEST_PATH.exists():
            pytest.skip("manifest not built yet")
        manifest = em.load_manifest()
        assert int(manifest["file_count"]) > 0
        # Key published conclusions must be inside the ledger.
        names = set(manifest["files"])
        assert any("factor_mining/ha_rotation_sim.json" in n for n in names)
        assert any("factor_mining/gp_mining.json" in n for n in names)
        assert any("migration/lake_baseline.json" in n for n in names)
