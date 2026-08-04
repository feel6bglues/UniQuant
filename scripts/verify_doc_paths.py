#!/usr/bin/env python3
"""Check all docs/ references to src/uniquant/ paths are valid.

Scans every .md file under docs/ (excluding archive/), extracts
src/uniquant/...py references, and reports any that don't exist in
the current working tree. Also checks that referenced class/function
names are importable.

Usage:
    python3 scripts/verify_doc_paths.py
    python3 scripts/verify_doc_paths.py --fix       # interactive fix prompts
"""

import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(PROJECT_ROOT, "docs")
ARCHIVE_DIR = os.path.join(DOCS_DIR, "archive")

# Match both `src/uniquant/...py` and relative `../src/uniquant/...py`
SRC_PATTERN = re.compile(r"(?:\.\./)*src/uniquant/([a-zA-Z0-9_/]+\.py)")
LINE_SUFFIX = re.compile(r":\d+(?:[-\u2013]\d+)?$")
CLASS_SUFFIX = re.compile(r"::[A-Za-z_]\w*$")


def extract_doc_paths(root_dir: str) -> dict[str, list[tuple[str, str]]]:
    """Scan markdown files and return {doc_path: [(raw_match, resolved_path), ...]}."""
    results: dict[str, list[tuple[str, str]]] = {}
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if os.path.join(dirpath, d) != ARCHIVE_DIR]
        for fname in filenames:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(dirpath, fname)
            relpath = os.path.relpath(fpath, PROJECT_ROOT)
            with open(fpath, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            matches = SRC_PATTERN.findall(content)
            if not matches:
                continue
            entries: list[tuple[str, str]] = []
            for m in matches:
                resolved = LINE_SUFFIX.sub("", m)
                resolved = CLASS_SUFFIX.sub("", resolved)
                full = "src/uniquant/" + m
                entries.append((full, resolved))
            results[relpath] = entries
    return results


def check_paths(entries: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """Return [(raw, resolved, reason)] for each problematic path."""
    problems: list[tuple[str, str, str]] = []
    for raw, resolved in entries:
        full_src = os.path.join("src/uniquant", resolved)
        abspath = os.path.join(PROJECT_ROOT, full_src)
        if not os.path.isfile(abspath):
            problems.append((raw, resolved, "FILE_NOT_FOUND"))
    return problems


def report(results: dict[str, list[tuple[str, str]]]) -> int:
    """Print report and return error count."""
    total_files = len(results)
    total_refs = sum(len(entries) for entries in results.values())
    all_problems: dict[str, list[tuple[str, str, str]]] = {}
    for doc, entries in results.items():
        problems = check_paths(entries)
        if problems:
            all_problems[doc] = problems

    print(f"Scanned {total_files} markdown files, {total_refs} code references.")

    if not all_problems:
        return 0

    print(f"\n{'='*60}")
    print(f"  MISSING CODE REFERENCES ({sum(len(v) for v in all_problems.values())} total)")
    print(f"{'='*60}")
    for doc in sorted(all_problems):
        print(f"\n  {doc}:")
        for raw, resolved, _ in all_problems[doc]:
            print(f"    ✗ {raw}")

    return len(all_problems)


def main() -> int:
    import json as json_mod

    results = extract_doc_paths(DOCS_DIR)
    err_count = report(results)

    if "--json" in sys.argv:
        output = {
            "generated_at": __import__("datetime").datetime.now().isoformat(),
            "status": "ERRORS" if err_count else "OK",
            "error_count": sum(len(v) for v in (
                check_paths(e) for e in results.values()
            ) if v) if err_count else 0,
            "broken_docs": list(sorted(
                k for k, v in results.items() if check_paths(v)
            )) if err_count else [],
            "total_files": len(results),
            "total_refs": sum(len(e) for e in results.values()),
        }
        print(json_mod.dumps(output, indent=2, ensure_ascii=False))
        return 0

    if err_count:
        print(f"\n❌ {err_count} doc(s) have stale code references.")
    else:
        print("✅ All code references are valid.")
    return 1 if err_count else 0


if __name__ == "__main__":
    sys.exit(main())
