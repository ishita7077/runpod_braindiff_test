# Agent 5 — Weak-type audit

## Methodology
```
rg "\bAny\b|dict\[.*Any\]|list\[Any\]|tuple\[.*Any" -g "*.py"
```
Then walked every hit and classified it by whether the `Any` is (a) genuinely
heterogeneous, (b) opaque third-party type, (c) inappropriately loose.

## Frontend
Vanilla JS, no TypeScript, no JSDoc types. Skipped.

## Inventory (grouped)

### Appropriate uses of `Any` (kept as-is, HIGH confidence keep)

| Location | Reason |
|---|---|
| `backend/model_service.py:226` — `tuple[np.ndarray, Any, dict[str, int]]` | Middle element is the opaque `segments` object from `self.model.predict()` (pandas/dict output varies by mode). Downstream call sites intentionally discard it (`preds, _, timing = ...`). Typing it would leak a nilearn/TRIBE implementation detail. |
| `backend/brain_mesh.py:18` — `_mesh_arrays(mesh: Any)` | Input is a nilearn surface object whose concrete type is private. Access is duck-typed. |
| `backend/neuralset_mps_patch.py` — multiple `Any` | Monkey-patch into third-party `neuralset` library. `Any` is correct for runtime-patched classes. |
| JSON-payload dicts (`dict[str, Any]`) in `api.py`, `insight_engine.py`, `narrative.py`, `result_semantics.py`, `differ.py`, `scorer.py`, `heatmap.py`, `status_store.py`, `telemetry_store.py`, `startup_manifest.py`, `preflight.py`, `logging_utils.py` | Heterogeneous JSON — each inner value is a different type (float, int, str, list, nested dict, np.ndarray). A proper `TypedDict` per shape is valid but it is a substantial refactor that (a) doesn't eliminate runtime behaviour differences and (b) ripples through HTTP response shapes. **Deferred** — flagged as a separate, intentional follow-up work item. |
| `tests/conftest.py` — `tribe_service: Any \| None` | Intentionally duck-typed; stubs used in tests do not inherit from `TribeService`. |

### Tightened (HIGH confidence, implemented)

| Location | Before | After | Reason |
|---|---|---|---|
| `backend/runtime.py:16` — `RuntimeProfile.config_update` | `dict[str, Any]` | `dict[str, str \| int]` | All values in `_profile_for_device` are strings (`"cpu"`, `"accelerate"`) or ints (`0`). No other producer. |
| `backend/runtime.py:20` — `runtime_to_dict` return | `dict[str, Any]` | `dict[str, str]` | Only returns `{"device": str, "backend": str}` or `{}`. |
| `backend/api.py:84` — `_service_runtime_dict` return | `dict[str, Any]` | `dict[str, str]` | Directly forwards `runtime_to_dict`. |
| `backend/runtime.py` — `from typing import Any` | imported | removed | No longer referenced. |

### Intentionally NOT changed (MEDIUM confidence, deferred with reasoning)

| Location | Why deferred |
|---|---|
| `backend/scorer.py:16` — `score_predictions` signature | Inner dict mixes `float`, `list[float]`, `int`, `np.ndarray`. A `TypedDict` is definable but introduces a new exported type consumed across 3 modules and by tests. Worth doing as a focused PR. |
| `backend/differ.py:18` — `compute_diff` | Same reasoning. Inner shape is the "diff row" consumed by `result_semantics.enrich_dimension_payload`. TypedDict candidate. |
| `backend/result_semantics.py` — `enrich_dimension_payload` | Output rows feed `insight_engine._top_sides` and directly to JSON response. Typing this touches the HTTP contract. |
| Every `dict[str, Any]` parameter on route handlers / job payloads | Touching these changes validation behaviour (Pydantic) and user-visible JSON errors. Out of scope for a cleanup pass. |

## Anti-patterns actively avoided
- Did **not** alias `dict[str, dict[str, Any]]` to a named type just to hide the `Any` — that is cosmetic, not stronger.
- Did **not** introduce `TypedDict` for shapes with 8+ fields without a dedicated review — too likely to drift from runtime truth.
- Did **not** add `cast()` or `# type: ignore` to paper over narrowing gaps.

## Sanity check

```
$ python3 -m py_compile backend/*.py tests/*.py scripts/*.py
COMPILE OK
```

No HTTP response shape changed (return values identical; only static annotations narrowed).

## Recommended follow-up (NOT done here)
A focused, single-purpose PR titled "introduce score/diff/row TypedDicts" that:
1. Defines `ScoreRow`, `MaskEntry`, `DiffRow`, `DimensionPayload` in `backend/schemas.py`.
2. Threads them through `scorer`, `differ`, `result_semantics`, `insight_engine`, `narrative`.
3. Runs the test suite end-to-end to confirm no runtime regressions.

Batch cost: ~4–6h focused work. High reward for type safety; zero behaviour change.
