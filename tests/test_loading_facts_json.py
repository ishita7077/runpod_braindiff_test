import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FACTS_PATH = ROOT / "frontend" / "data" / "tribe_loading_facts.json"


def test_tribe_loading_facts_json_valid() -> None:
    assert FACTS_PATH.is_file()
    data = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    assert "meta" in data
    assert data["meta"].get("review_cadence_days") == 14
    facts = data["facts"]
    assert isinstance(facts, list) and len(facts) >= 3
    for f in facts:
        assert f.get("title")
        assert f.get("body")
        if f.get("source_url"):
            assert str(f["source_url"]).startswith("http")


@pytest.mark.skipif(not FACTS_PATH.is_file(), reason="facts file missing")
def test_validate_loading_facts_script_exits_zero() -> None:
    import subprocess
    import sys

    script = ROOT / "scripts" / "validate_loading_facts.py"
    r = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
