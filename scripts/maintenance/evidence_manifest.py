#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evidence-chain manifest: content-hash ledger for published research artifacts.

Why this exists
---------------
The data lake (``data/lake/``, multi-GB) and bulk research output are large and
regenerable, so they are not tracked as blobs. Historically that left *every*
empirical conclusion (the P-series factor studies, the H-A reconciliation, the
QFQ/migration verification) with no auditable trail in the repository — the
evidence chain existed only on the developer's machine.

This script closes that gap without committing the bulk: it records a SHA-256
digest (plus size) for **every tracked evidence artifact**, derived from the git
index (``git ls-files``). Because the index is exactly what the repository
actually ships, the manifest and the allowlist in ``results/.gitignore`` can
never disagree.

Usage
-----
    python scripts/maintenance/evidence_manifest.py build
    python scripts/maintenance/evidence_manifest.py verify
    python scripts/maintenance/evidence_manifest.py verify --allow-missing

``verify`` exits non-zero on any drift (changed digest, missing file, or a new
untracked-in-manifest evidence file), so CI can gate on it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "results" / "EVIDENCE_MANIFEST.json"

# Evidence roots (relative to the repo root). Only *tracked* files underneath
# these roots are covered, so the manifest always mirrors what the repo ships.
EVIDENCE_ROOTS: Tuple[str, ...] = ("results", "tests/benchmark")

# Extensions that count as evidence (structured results / published summaries).
EVIDENCE_SUFFIXES: Tuple[str, ...] = (".json", ".csv", ".md", ".parquet")


def _git_ls_files(roots: Iterable[str]) -> List[str]:
    """Return tracked files under ``roots`` (paths relative to the repo root)."""
    cmd = ["git", "ls-files", "--", *roots]
    try:
        out = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _is_evidence(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    if rel.endswith("EVIDENCE_MANIFEST.json"):
        return False
    return rel.lower().endswith(EVIDENCE_SUFFIXES)


def _relative_paths(roots: Iterable[str] = EVIDENCE_ROOTS) -> List[str]:
    """All evidence files that should be covered, sorted for determinism."""
    tracked = [p for p in _git_ls_files(roots) if _is_evidence(p)]
    if tracked:
        return sorted(tracked)
    # Fallback (no git / not a repo): walk the roots directly.
    found: List[str] = []
    for root in roots:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and _is_evidence(str(path.relative_to(REPO_ROOT))):
                found.append(str(path.relative_to(REPO_ROOT)))
    return sorted(found)


def build_manifest() -> Dict[str, object]:
    files: Dict[str, Dict[str, object]] = {}
    total = 0
    for rel in _relative_paths():
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        size = path.stat().st_size
        total += size
        files[rel] = {"sha256": _sha256(path), "size": size}
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(),
        "roots": list(EVIDENCE_ROOTS),
        "file_count": len(files),
        "total_bytes": total,
        "files": files,
    }


def write_manifest(manifest: Dict[str, object]) -> Path:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return MANIFEST_PATH


def load_manifest() -> Dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def verify_manifest(allow_missing: bool = False) -> Tuple[bool, List[str]]:
    """Compare the tree against the recorded manifest. Returns (ok, problems)."""
    problems: List[str] = []
    if not MANIFEST_PATH.exists():
        return False, [f"manifest not found: {MANIFEST_PATH}"]

    recorded = load_manifest()
    files = recorded.get("files")
    if files is None:
        files = {}
    if not isinstance(files, dict):
        return False, ["manifest 'files' section is malformed"]

    current = set(_relative_paths())
    recorded_keys = set(files)

    for rel in sorted(recorded_keys):
        entry = files[rel] or {}
        path = REPO_ROOT / rel
        if not path.exists():
            if not allow_missing:
                problems.append(f"MISSING: {rel}")
            continue
        size = path.stat().st_size
        if int(entry.get("size", -1)) != size:
            problems.append(
                f"SIZE DRIFT: {rel} (recorded {entry.get('size')}, actual {size})"
            )
        actual_sha = _sha256(path)
        if entry.get("sha256") != actual_sha:
            problems.append(
                f"HASH DRIFT: {rel} (recorded {str(entry.get('sha256'))[:12]}…, "
                f"actual {actual_sha[:12]}…)"
            )

    for rel in sorted(current - recorded_keys):
        problems.append(f"UNTRACKED IN MANIFEST: {rel} (run `build`)")

    return (not problems), problems


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "verify"))
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="verify: ignore recorded files that are absent from the tree",
    )
    args = parser.parse_args(argv)

    if args.mode == "build":
        manifest = build_manifest()
        path = write_manifest(manifest)
        print(
            f"Wrote {path.relative_to(REPO_ROOT)}: "
            f"{manifest['file_count']} evidence files, "
            f"{manifest['total_bytes']} bytes, head={manifest['git_head'][:12]}"
        )
        return 0

    ok, problems = verify_manifest(allow_missing=args.allow_missing)
    if ok:
        print("Evidence manifest verified: no drift.")
        return 0
    print("Evidence manifest DRIFT detected:", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
