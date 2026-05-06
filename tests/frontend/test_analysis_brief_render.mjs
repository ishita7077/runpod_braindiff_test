// Phase E.1 — analysis_brief render block guard.
//
// The brief block must:
//   1. exist as renderAnalysisBrief in results.html
//   2. be invoked from render() between hero and frame2
//   3. early-return ('') when slot.source !== 'llm' OR brief value is missing
//   4. NOT use any banned generic phrases as hardcoded copy
//   5. cite evidence_refs verbatim from the slot value
//
// Static check against the source string. Sufficient because the renderer is
// pure: same input -> same HTML.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(
  path.join(__dirname, '..', '..', 'frontend_new', 'results.html'),
  'utf8',
);

const failures = [];
function check(label, ok, detail) {
  if (!ok) failures.push(`${label}\n  → ${detail}`);
}

check(
  'render() invokes renderAnalysisBrief',
  /renderAnalysisBrief\(c\)/.test(html),
  'expected `renderAnalysisBrief(c)` inside render()',
);

const fnMatch = html.match(/function renderAnalysisBrief[\s\S]*?\n\}/);
if (!fnMatch) {
  failures.push('renderAnalysisBrief function not found');
} else {
  const body = fnMatch[0];
  check(
    'renderAnalysisBrief: returns "" when source !== "llm"',
    /slot\.source\s*!==\s*['"]llm['"]/.test(body),
    'must early-return when slot.source is not "llm"',
  );
  check(
    'renderAnalysisBrief: reads slot.value',
    /slot\s*&&\s*slot\.value/.test(body),
    'must read brief = slot.value',
  );
  check(
    'renderAnalysisBrief: handles missing brief.thesis without crashing',
    /brief\.thesis\s*\|\|\s*['"]['"]/.test(body),
    'must render `brief.thesis || ""` so undefined doesn\'t become "undefined"',
  );
  // No hardcoded generic phrases.
  const banned = ['make it more engaging', 'improve clarity', 'optimize content'];
  banned.forEach((phrase) => {
    if (new RegExp(phrase, 'i').test(body)) {
      failures.push(`renderAnalysisBrief contains banned phrase '${phrase}'`);
    }
  });
  check(
    'renderAnalysisBrief: renders evidence_refs verbatim',
    /evidence_refs/.test(body) && /<code>/.test(body),
    'must wrap each evidence_ref in <code> so the timestamp is visible',
  );
}

if (failures.length) {
  console.error('analysis_brief render guard FAILED:');
  failures.forEach((f) => console.error('  - ' + f));
  process.exit(1);
}
console.log('analysis_brief render guard PASSED');
