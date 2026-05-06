// Phase A.2 — regression test for renderChordDetail's ReferenceError.
//
// The bug: results.html's renderChordDetail referenced `meaning.formula_human`,
// but `meaning` was never defined in that scope (only `lib` and `m.meaning`
// exist). Clicking any chord would throw ReferenceError and break the right
// panel.
//
// We can't load the full page DOM here without jsdom (not in deps), so the
// test extracts the renderChordDetail function body from results.html and
// asserts:
//   1. it does NOT contain the bare identifier `meaning.formula_human`
//   2. it DOES contain the safe `lib.formula_human` access
//
// Run: node tests/frontend/test_results_chord_detail.mjs

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(
  path.join(__dirname, '..', '..', 'frontend_new', 'results.html'),
  'utf8',
);

// Pull the renderChordDetail function so we're not testing the whole file.
const fnMatch = html.match(/function renderChordDetail\([^]*?\n\}\n/);
if (!fnMatch) {
  console.error('FAIL: could not locate renderChordDetail in results.html');
  process.exit(1);
}
const body = fnMatch[0];

const failures = [];

// Forbidden: bare `meaning.` access. Must be `m.meaning` or `lib.` instead.
// Allow `m.meaning.value` and `(m.meaning && m.meaning.value)`.
const lines = body.split('\n');
lines.forEach((ln, idx) => {
  // strip valid `m.meaning` / `lib.meaning` accesses, then check what's left.
  const stripped = ln
    .replace(/m\.meaning(?:\.\w+)?/g, '')
    .replace(/lib\.meaning(?:\.\w+)?/g, '');
  if (/\bmeaning\.\w+/.test(stripped)) {
    failures.push(`line ${idx + 1}: bare meaning.<X> access — should be lib.<X> or m.meaning.<X>`);
    failures.push(`  → ${ln.trim()}`);
  }
});

// Required: lib.formula_human must appear in the function (the fixed access).
if (!/lib\.formula_human/.test(body)) {
  failures.push('renderChordDetail must reference lib.formula_human at least once');
}

if (failures.length) {
  console.error('renderChordDetail regression check FAILED:');
  failures.forEach((f) => console.error('  ' + f));
  process.exit(1);
}
console.log('renderChordDetail regression check PASSED');
