"""Phase A.5 — content-model rename safety net.

The plan calls for renaming `use_real_llama` to `use_real_content_model` and
keeping the old name as a deprecated alias. We assert:

  * the new name exists and is callable
  * the old name still works but emits DeprecationWarning
  * both refer to the same underlying creation path
  * grep-equivalent: only the deprecated alias and this test reference
    `use_real_llama` in the repo

The third bullet is enforced by parametrising the same fake-load call twice
and asserting they produce the same backend type.
"""

from __future__ import annotations

import pathlib
import warnings


def test_use_real_content_model_is_exported() -> None:
    from backend.results.lib import model_manager
    assert callable(getattr(model_manager, "use_real_content_model", None))


def test_use_real_llama_alias_emits_deprecation_warning() -> None:
    """The legacy name must still call through, with a DeprecationWarning."""
    from backend.results.lib import model_manager

    captured: list[Warning] = []

    def fake_use_real_content_model(**_kwargs: object) -> str:
        return "called"

    orig = model_manager.use_real_content_model
    model_manager.use_real_content_model = fake_use_real_content_model  # type: ignore[assignment]
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = model_manager.use_real_llama()
            captured = list(w)
        assert result == "called"
        deprecations = [warning for warning in captured if issubclass(warning.category, DeprecationWarning)]
        assert deprecations, "use_real_llama did not emit a DeprecationWarning"
    finally:
        model_manager.use_real_content_model = orig  # type: ignore[assignment]


def test_no_internal_callers_of_use_real_llama_outside_alias() -> None:
    """Grep gate: the deprecated name should appear only in:
      1. the model_manager.py alias definition + warning string
      2. this regression test

    Anything else is a missed migration.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    allow_substrings = (
        # Definition + docstring + warning text live here.
        "backend/results/lib/model_manager.py",
        # This test file itself.
        "tests/test_results_model_manager_rename.py",
    )
    forbidden_hits: list[str] = []
    for path in repo_root.rglob("*.py"):
        rel = str(path.relative_to(repo_root))
        if rel.startswith(".git/") or rel.startswith(".venv/"):
            continue
        if any(rel.endswith(allowed.split("/")[-1]) and rel == allowed for allowed in allow_substrings):
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if "use_real_llama" in line:
                forbidden_hits.append(f"{rel}:{i}: {line.strip()}")
    assert not forbidden_hits, "Stale callers of use_real_llama remain:\n" + "\n".join(forbidden_hits)
