# Agent 2 — Shared type consolidation

## Methodology
Grep for every type-definition construct across the repo:

```
rg "class \w+\(BaseModel\)|TypedDict|NamedTuple|@dataclass|TypeAlias" -g "*.py"
```

## Inventory

| Symbol | File:Line | Kind | Consumers |
|---|---|---|---|
| `DiffRequest` | `backend/schemas.py:4` | Pydantic | `backend/api.py` (request model on `POST /api/diff*`) |
| `JobStartResponse` | `backend/schemas.py:9` | Pydantic | `backend/api.py` (`POST /api/diff/start` response_model) |
| `ReportPair` | `backend/schemas.py:15` | Pydantic | `backend/api.py` (nested in `ReportRequest`) |
| `ReportRequest` | `backend/schemas.py:21` | Pydantic | `backend/api.py` (`POST /api/report`) |
| `RuntimeProfile` | `backend/runtime.py:13` | `@dataclass(frozen=True)` | `backend/model_service.py`, `tests/test_model_service_runtime.py` |

Non-data classes (not candidates for consolidation):
- `TelemetryStore` — stateful store, `backend/telemetry_store.py:9`
- `JobStore` — stateful store, `backend/status_store.py:6`
- `TribeService` — service singleton, `backend/model_service.py:96`

No `TypedDict`, no `NamedTuple`, no `TypeAlias`, no JSDoc typedefs in frontend.

## Clusters / merge candidates

**None.** Every shape in the repo is used by exactly the modules it logically belongs to:

- `schemas.py` is already the central Pydantic home and is already imported from only one place (`backend/api.py`).
- `RuntimeProfile` is tightly coupled to device/backend detection logic in `runtime.py`; moving it to `schemas.py` would couple the HTTP layer to device-detection and force `schemas.py` to import `dataclasses`. Net: no win.

## Shadowing / name collisions
None. No two types share a name.

## `dict[str, Any]` returns that could be Pydantic models
Deferred to Agent 5 (weak types). Candidates noted for that agent:
- `runtime_to_dict` → `dict[str, Any]`
- Every `/api/diff*` endpoint returns `JSONResponse` with a hand-built dict; could be a `DiffResultModel`, but introducing that affects public JSON shape guarantees and should be a dedicated change, not rolled into types-consolidation.
- `StartupManifest` / telemetry payloads — similar story.

## HTTP response shapes verified
Walked every `response_model=` and every `return JSONResponse(...)` in `backend/api.py` and confirmed the Pydantic-typed ones (`JobStartResponse`) match the manually-built ones (keys: `job_id`, `request_id`, `status`). No drift.

## Recommendations & confidence

| Item | Action | Confidence |
|---|---|---|
| Keep `schemas.py` as canonical Pydantic home | No-op | HIGH |
| Keep `RuntimeProfile` co-located with `runtime.py` | No-op | HIGH |
| Convert dict-return APIs to Pydantic | Defer to a dedicated task | LOW (scope creep) |
| Add `TypedDict` for telemetry event payloads | Defer | LOW (internal shape flux) |

## Implementation
**No changes made.** The type surface is already minimal and correctly partitioned. Any further consolidation would either (a) introduce coupling for no benefit or (b) belong to a different agent's scope.

## Sanity check
```
$ python3 -m py_compile backend/*.py tests/*.py
OK
```
