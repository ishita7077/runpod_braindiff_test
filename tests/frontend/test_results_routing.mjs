// Phase B.3 — frontend smoke that fails when results_content is ignored.
//
// Goal: a static check that proves
//   1. run.html only routes completed jobs to the canonical rich pages
//      (results.html, text-results.html); never to legacy *-results.html.
//   2. video-results.js and audio-results.js redirect to the canonical
//      rich page when results_content is present, unless ?legacy=1.
//   3. admin.html's resultUrl never points to the legacy debug pages
//      as the primary destination.
//
// We don't have jsdom in this repo, so we do the strongest static check we
// can: scan the source for the redirect/return literals and assert their
// presence. If anyone removes them, the test fails. This catches regressions
// without requiring a browser.
//
// Run: node tests/frontend/test_results_routing.mjs

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, '..', '..');

const failures = [];
function check(label, ok, detail) {
  if (!ok) failures.push(`${label}\n  → ${detail}`);
}

// 1. run.html — primary routing function points to rich pages only when no legacy param.
const runHtml = fs.readFileSync(path.join(root, 'frontend_new', 'run.html'), 'utf8');
check(
  'run.html: resultsPageForMode primary routes to text-results.html for text/audio',
  /resultsPageForMode[\s\S]*?return\s+'\.\/text-results\.html'/.test(runHtml),
  "expected `return './text-results.html'` inside resultsPageForMode",
);
check(
  'run.html: resultsPageForMode primary routes to results.html for video',
  /resultsPageForMode[\s\S]*?return\s+'\.\/results\.html'/.test(runHtml),
  "expected `return './results.html'` inside resultsPageForMode",
);
check(
  'run.html: resultsPageForMode honours ?legacy=1 escape hatch',
  /forceLegacy[\s\S]*?legacy/.test(runHtml),
  "expected legacy escape hatch (forceLegacy + legacy=1) in resultsPageForMode",
);

// 2. video-results.js / audio-results.js — must self-redirect on results_content.
function checkLegacyRedirect(file, target) {
  const src = fs.readFileSync(path.join(root, 'frontend_new', file), 'utf8');
  check(
    `${file}: reads results_content`,
    /results_content/.test(src),
    'expected the file to inspect job.result.results_content',
  );
  check(
    `${file}: checks ?legacy=1 escape hatch`,
    /params\.get\("legacy"\)\s*===\s*"1"/.test(src),
    'expected `params.get("legacy") === "1"` guard',
  );
  check(
    `${file}: redirects to ${target} when results_content present`,
    new RegExp(`/${target.replace('.', '\\.')}`).test(src) && /location\.replace/.test(src),
    `expected location.replace pointing to /${target}`,
  );
  check(
    `${file}: validates results_content.v1 schema before redirecting`,
    /results_content\.v1/.test(src),
    "expected to gate the redirect on schema_version === 'results_content.v1'",
  );
}

checkLegacyRedirect('video-results.js', 'results.html');
checkLegacyRedirect('audio-results.js', 'text-results.html');

// 3. admin.html — primary URL builder must not point at legacy pages.
const adminHtml = fs.readFileSync(path.join(root, 'frontend_new', 'admin.html'), 'utf8');
const resultUrlBlock = adminHtml.match(/function resultUrl[\s\S]*?\n\}/);
if (!resultUrlBlock) {
  failures.push('admin.html: could not locate resultUrl function');
} else {
  const block = resultUrlBlock[0];
  if (/audio-results\.html/.test(block)) {
    failures.push('admin.html resultUrl: should not link primary admin views at audio-results.html');
  }
  if (/video-results\.html/.test(block)) {
    failures.push('admin.html resultUrl: should not link primary admin views at video-results.html');
  }
  check(
    'admin.html resultUrl: links to text-results.html for text/audio',
    /text-results\.html/.test(block),
    'expected text-results.html in resultUrl',
  );
  check(
    'admin.html resultUrl: links to results.html for video',
    /results\.html/.test(block),
    'expected results.html in resultUrl',
  );
}

// 4. Belt-and-braces: results.html must read results_content as primary.
const resultsHtml = fs.readFileSync(path.join(root, 'frontend_new', 'results.html'), 'utf8');
check(
  'results.html: reads data.result.results_content',
  /data\.result\s*&&\s*data\.result\.results_content/.test(resultsHtml),
  'expected `data.result && data.result.results_content` in bootFromJob',
);

if (failures.length) {
  console.error('Phase B routing smoke FAILED:');
  failures.forEach((f) => console.error('  - ' + f));
  process.exit(1);
}
console.log('Phase B routing smoke PASSED');
