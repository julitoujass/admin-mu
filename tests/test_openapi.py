import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_export_module():
    spec = importlib.util.spec_from_file_location("export_openapi", ROOT / "scripts" / "export_openapi.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_openapi_matches_the_app():
    committed = (ROOT / "openapi.json").read_text(encoding="utf-8")

    assert committed == load_export_module().render_schema(), (
        "openapi.json is out of date: run `python scripts/export_openapi.py` and commit the result"
    )
