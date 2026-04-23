# Agent 8 — AI slop, stubs, unnecessary comments

## Methodology
Searched for the usual tells of AI-generated noise:

```
# narrating comments
rg "^\s*(#|//)\s*(Added|Creates|Returns|Gets|Sets|Updates|Checks|Loads|Saves)\s"

# time / status chatter
rg "(?i)\b(previously|used to|before|in (the|a) future|eventually|later we|we (can|will|should))\b"

# scoped slop markers
rg "(?i)lorem ipsum|your code here|dummy data|fake data|stub implementation"

# in-motion rework markers
rg "(?i)^\s*#\s*(note:|todo:|fixme|xxx|hack|placeholder|for now|temporary|will add|will implement|replaced|removed)"

# dead guard remnants
rg "if \(false\)|// @ts-ignore"
```

## Findings

**Codebase is actually well-commented.** Comments across `backend/` and
`frontend_new/` explain non-obvious intent (why MPS requires `accelerate`, why
telemetry splits a monolithic call into two events, why routes register before
the static mount, why whisperx on MPS falls back to int8). None of them are
"Increment the counter"-style narration.

### Slop patterns — NOT found
- No `Added/Creates/Returns` narrating comments (1 match — `// Returns a setHighlight(key) function that paints the region` — is a legitimate JSDoc-style return description, kept).
- No `lorem ipsum` / `your code here` / placeholder content anywhere.
- No `// @ts-ignore` (no TypeScript), no `if (false)` dead-branch guards (the one Agent 1 found was already killed).
- No "now uses / replaces / we will" in-motion AI-voice comments.

### Useful comments flagged as "placeholder" but kept
| Location | Comment | Verdict |
|---|---|---|
| `frontend_new/index.html:1607, 2163` | body-copy describing memory encoding — "Not what the reader feels now — what they will still remember tomorrow" | **KEEP** — product copy, not slop |
| `frontend_new/index.html:877, 962` | `TODO verify against paper: exact campaign titles and effect sizes` | **KEEP** — actionable research note flagging unverified facts in the Falk 2012 case-study panel |
| `frontend_new/index.html:2082` | `// Placeholder sphere (compare / lens canvases) — original motion.` | **KEEP** — meaningfully distinguishes the sphere fallback from the real-mesh render path |
| `tests/test_sanity_pairs.py:13-14` | `# Placeholder shape for phase gate: uses canonical directional expectations. Full semantic validation requires model inference over curated pairs.` | **KEEP** — honest about the test's limitation; provides real context for a future improver |
| `frontend_new/input.html:632` | `// Canonical soft-warning rules — mirror of KNOWN_FAILURE_MODES.md §1.` | **KEEP** — points the reader to the source of truth |

### Banner separators (`# ---------`)
4 files have them (`api.py`, `conftest.py`, `preview_server.py`,
`test_model_smoke.py`). All are section anchors in longer files. Navigational
value is real; left untouched.

### Stubs
None found. `tests/test_sanity_pairs.py` contains synthetic fixture data, not a
stub — it is gated behind `RUN_TRIBEV2_SANITY=1` and is honest about its
limitation (see table above).

## Implementation
**No changes made.**

Every comment considered for removal was either:
1. Explaining domain-specific constraints (e.g., MPS/accelerate device rules)
2. Pointing at an authoritative spec (KNOWN_FAILURE_MODES.md, paper citations)
3. A legitimate `TODO verify` flagging unverified content
4. A section separator that aids file navigation

Comments were NOT removed just because they're comments. This is a domain-heavy
project (neuro imaging, HuggingFace / Transformers / nilearn interop); inline
context is load-bearing.

## Sanity check
```
$ python3 -m py_compile backend/*.py tests/*.py scripts/*.py
OK
```

No code changes — this agent is purely a report.
