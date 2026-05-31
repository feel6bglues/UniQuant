import importlib.util
from pathlib import Path


def test_offline_full_test_wrapper_compiles():
    module_path = Path(__file__).resolve().parent.parent / "scripts" / "offline_full_test.py"
    spec = importlib.util.spec_from_file_location("offline_full_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
