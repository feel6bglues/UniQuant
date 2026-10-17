"""Guard: ``tests/conftest.py`` pre-creates mootdx's config dirs before collection.

Why this exists
---------------
``mootdx.utils.get_config_path()`` is called at *import* time (via the
``@file_cache`` decorators in ``mootdx.utils.adjust`` / ``mootdx.utils.holiday``)
and runs, with no ``exist_ok``::

    Path(pathname).exists() or Path(pathname).mkdir(parents=True)

On a fresh runner where ``~/.mootdx`` does not exist yet, two ``pytest-xdist``
workers can both pass the ``exists()`` check and one then raises
``FileExistsError`` *during collection*, killing the worker and surfacing as
``Different tests were collected between gw0 and gw1``.  This was observed on the
CI ``coverage`` job (2026-10-17, run 39024111065) — a third-party TOCTOU defect,
not a code defect of ours.

``tests/conftest.py`` therefore pre-creates the library's own config dirs at
import time so the racy ``exists()`` short-circuits.  These tests lock that
invariant in: if someone removes the conftest block (or a future parallel runner
imports test modules before conftest), the race can silently return.
"""

from __future__ import annotations

import os

import pytest

# ``get_config_path`` is called with these config names at import time by mootdx;
# each maps to a parent directory under ``~/.mootdx`` that must pre-exist.
_REQUIRED_SUBDIRS = (".mootdx", os.path.join(".mootdx", "caches"), os.path.join(".mootdx", "xdxr"))


def test_mootdx_config_dirs_precreated_by_conftest():
    """The dirs must already exist *without* us calling ``get_config_path``."""
    home = os.path.expanduser("~")
    if not os.access(home, os.W_OK):
        pytest.skip(f"HOME not writable, conftest guard is a best-effort no-op: {home}")
    missing = [sub for sub in _REQUIRED_SUBDIRS if not os.path.isdir(os.path.join(home, sub))]
    assert not missing, f"conftest must pre-create mootdx config dirs, missing: {missing}"


def test_precreation_is_idempotent_and_race_safe():
    """Re-running the same ``makedirs(exist_ok=True)`` must not raise.

    ``exist_ok=True`` is what makes the guard safe when several xdist workers
    execute it concurrently (the exact failure mode of the unguarded third-party
    ``mkdir``).
    """
    home = os.path.expanduser("~")
    for sub in _REQUIRED_SUBDIRS:
        path = os.path.join(home, sub)
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:  # HOME not writable -> the guard is a documented no-op
            pytest.skip(f"HOME not writable: {path}")
        assert os.path.isdir(path)
