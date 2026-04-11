# Brain Diff Daily Changelog (2026-04-11)

## Scope
- Stabilized local Apple Silicon execution path for Brain Diff.
- Improved backend runtime truthfulness and frontend behavior around long-running jobs.
- Restructured frontend into a public landing experience plus separate app experience.
- Added discovery-oriented narrative framing and follow-up experiment guidance.

## Backend Updates
- Updated runtime/text-backend handling to better reflect MPS vs CPU realities.
- Improved preflight/runtime diagnostics and preserved honest readiness/status reporting.
- Expanded insight generation with:
  - discovery-framed headline templates,
  - lightweight content-quality detection,
  - follow-up experiment suggestions by dominant dimension.
- Updated narrative fallback headline behavior to match discovery framing.

## Frontend Updates
- Split architecture into:
  - `index.html` (public landing page),
  - `app.html` (interactive Brain Diff application).
- Added new landing experience:
  - trust-first hero,
  - read-only live demo section,
  - "how to read this" explainer cards,
  - science story section,
  - methodology one-pager,
  - dedicated CTA flow to app.
- Added app enhancements:
  - experiment question labeling from examples,
  - writing-move card,
  - follow-up experiment section,
  - optional share-name rendering on share image.

## UX and Motion
- Restored and expanded motion systems for the landing page:
  - animated hero particle canvas,
  - reveal-on-scroll transitions,
  - animated evidence-chip entrances,
  - animated demo bar fills,
  - interactive hover micro-motions for cards and methodology steps,
  - rotating brain preview.

## Reliability and Troubleshooting Notes
- Investigated repeated run failures tied to WhisperX/ffmpeg and torchcodec/libav loading paths.
- Verified a subsequent full run completed successfully on local MPS runtime.
- Confirmed current local server health endpoints report ready state.

## Validation
- Ran targeted backend tests after major updates:
  - `tests/test_insight_engine.py`
  - `tests/test_api.py`
- Result: all targeted tests passed.

## Notes
- This changelog captures work completed today for repository traceability.
