"""Write the API's OpenAPI schema to `openapi.json` at the repository root.

Usage (no network or real credentials needed; any placeholder values work):

    SUPABASE_URL=https://example.supabase.co SUPABASE_KEY=sb_secret_dummy python scripts/export_openapi.py
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The app builds its Supabase client on import; placeholders are enough to export the schema.
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "sb_secret_dummy")

from app.main import app  # noqa: E402

OUTPUT = ROOT / "openapi.json"


def render_schema() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUTPUT.write_text(render_schema(), encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT}")
