# Gemma 3 1B Output Quality — Improvement Brief

**Mission:** Get Gemma 3 1B to produce publication-quality copy for the BrainDiff results page across 8 slot types. Right now most slots fall back to template text because Gemma's output fails strict validators.

**Your role:** Read this brief, then propose (a) better prompts per slot, (b) suggested validator changes if any rule is unrealistic, (c) sampling parameter tweaks, (d) anything else that ships better copy fast. Hand the proposals back; I'll wire them in.

---

## Product context (60 seconds)

BrainDiff takes two pieces of content (text, audio, or short video, max 30s) and runs them through Meta's **TRIBE v2** brain-prediction model. TRIBE outputs per-second activation across **7 cortical systems**:

| Key | Display name | Region |
|---|---|---|
| `personal_resonance` | Personal Resonance | mPFC — self-relevant processing |
| `attention` | Attention | DAN — dorsal attention network |
| `brain_effort` | Brain Effort | dlPFC — cognitive control |
| `gut_reaction` | Gut Reaction | anterior insula — visceral response |
| `memory_encoding` | Memory Encoding | vlPFC — subsequent memory |
| `social_thinking` | Social Thinking | rTPJ — theory of mind |
| `language_depth` | Language Depth | Broca + Wernicke |

The pipeline:
1. TRIBE → 7-system per-second timeseries for both inputs
2. Deterministic analysis → matches cognitive "recipes" (Slow Build → Deep Encode, Hook → Hold, etc.) and detects "chord moments" (when 2+ systems cross threshold simultaneously)
3. **Gemma writes the editorial copy** — headlines, body, recipe descriptions, chord meanings, coupling callouts

The whole product is positioned as a **strategy comparison**, never a contest. "Two ads, one cortex. Here's where they diverge."

---

## What's wrong right now

I ran a real text comparison: WSJ-style copy ("The Federal Reserve held its benchmark interest rate steady…") vs Fox-style copy ("The Fed is STUCK. They can't lower rates…"). Result page on text-results.html:

- **Headline** rendered: *"Two videos. Two cortical recipes. Different strategies, same brain."* — generic template fallback. The actual Gemma headline failed validation.
- **Body** rendered: *"These two videos recruit the cortex differently. Each runs a distinct cognitive recipe — different systems pulled, different timing, different cortical fingerprints. Neither is winning. They're playing different games."* — generic fallback.
- **Recipe descriptions** for both sides: *"The cortical signature for this video did not match a named recipe in the current library. Closest match noted in audit logs. *Built for novel pattern.*"* — fallback. Same text on both sides → no contrast.
- **Coupling callouts**: missing entirely (validator rejection or Gemma silent fail)
- **Chord meanings**: not yet rendered in current frontend, but data exists

These all carry a `FALLBACK` source badge in dev mode, confirming the pipeline tried Gemma → got rejected by validator → used template.

---

## The model

- `google/gemma-3-1b-it` (text-only, 1B params, IFEval 80.2)
- Loaded via HuggingFace `transformers.AutoModelForCausalLM` with `bfloat16` (float16 is broken for Gemma 3 — produces empty output)
- Sampling params: `temperature=1.0`, `top_p=0.95`, `top_k=64`, `do_sample=True` (Gemma 3 official recommended config)
- `apply_chat_template` is used; one user message per call; no system role (Gemma 3 doesn't support it — system prompts must be embedded in the first user turn)
- Per-slot timeout: 600 seconds
- Runs on RunPod serverless GPU (A40 / RTX A5000)

---

## Constraints (validators) — these are why outputs get rejected

Every slot validator runs these checks. **Banned patterns** (universal across all slots):

| Code | Regex | Reason |
|---|---|---|
| `BANNED_PERCENT` | `\b\d{1,3}\s?%` | No "89%" claims |
| `BANNED_R_VALUE` | `\br\s?=\s?[-+]?\d?\.?\d+` | No "r=0.87" |
| `BANNED_P_VALUE` | `\bp\s?[<>=]\s?\d?\.?\d+` | No "p<0.05" |
| `BANNED_CITATION` | `\bet\s+al\.?` | No academic citations |
| `BANNED_YEAR` | `\b(19\|20)\d{2}\b` | No year stamps |
| `BANNED_WINNER_FRAMING` | `\b(wins?\|loses?\|winner\|loser\|better than\|worse than)\b` | Strategy comparison, never contest |

**Per-slot rules:**

| Slot | Sentences | Words | Other |
|---|---|---|---|
| `headline` | exactly 2 | each ≤ 10 | no anatomical terms ("insula", "cortex", "prefrontal") |
| `body` | 2–4 | ≤ 90 | — |
| `recipe_description` | ≤ 3 | ≤ 60 | **must contain timestamp (M:SS)**; **must contain `*Built for X*` italic tag** (single-asterisk-wrapped) |
| `recipe_match_rationale` | 1 | ≤ 35 | required JSON fields: library_id, name, confidence ∈ [0,1], rationale |
| `coupling_callout` | exactly 2 | ≤ 38 | must reference both system display names |
| `chord_contextual_meaning` | 1–4 | ≤ 100 | must contain timestamp OR quote fragment OR video title |
| `chord_context` | 1 | ≤ 22 | must reference timestamp / creator / quote / cortical detail |
| `frame2_sub` | 2–4 | ≤ 90 | must mention both recipe names; must include the word "chord" |

**My suspicion on what's failing most:**
- `recipe_description` fails because Gemma forgets the `*Built for X*` italic tag or skips the timestamp
- `coupling_callout` fails because Gemma uses generic words ("memory and language") instead of the exact display names
- `headline` fails the "exactly 2 sentences, each ≤10 words" — Gemma writes 1 long sentence or 3 short ones
- `body` fails the "neither winning" rule when Gemma instinctively uses "better"/"worse"

Validators don't currently retry — one fail → fallback. There are no per-slot retry loops or repair attempts.

---

## All 8 prompt templates (verbatim, current)

### `headline.txt`
```
You are writing the hero headline for a Brain Diff results page.

Brain Diff compares two videos by predicting cortical activation in 7 systems
and identifying their cognitive recipes. Every page is a STRATEGY comparison.
Never winner-vs-loser. Never "X wins Y" framing.

The headline LEADS WITH THE SHARPEST INSIGHT FROM THE COUPLING ANALYSIS.
The strongest coupling pattern across both videos has already been identified
deterministically. Your job: write 2 short declarative sentences that name
that contrast in plain English, using the video TITLES (no creator names).

Format: 2 short sentences. Each sentence ≤ 10 words. The two sentences should
mirror each other in structure — same verb pattern, opposite content. Use
plain English. Never use anatomical terms (no "insula," no "cortex," no
"prefrontal," no system jargon). Never include numeric percentages, r-values,
citations, or year stamps.

Inputs:
- Video A title: {video_a_title}
- Video B title: {video_b_title}
- THE LEAD INSIGHT (the strongest coupling pattern, drives the headline):
{lead_insight}
- Top 3 system-mean deltas (raw signal, no axis-labels):
{top_deltas}

Voice exemplars (study these carefully):
{exemplars}

Generate 5 candidate headlines following this pattern. Then select the one
with strongest contrast, sharpest plain-language framing, and clearest line
to the lead insight. Output only the selected headline as a single string.
No explanation. No quotes around it.
```

### `body.txt`
```
You are writing the body paragraph below the hero headline on a Brain Diff
results page.

The headline has just landed a sharp claim drawn from the strongest coupling
pattern in this comparison. The body paragraph's job: SUPPORT THE HEADLINE
in plain language — explain WHY the cortex behaved this way, ground it in
what the videos actually did, and HOOK the reader to keep reading.

Do NOT pad with "different strategies, neither is winning" filler. That's
generic — the user has already understood the page is a strategy comparison
from the headline. Your job is to convince them the contrast is REAL and
worth scrolling for.

Format: 2-3 sentences, ≤ 60 words. Direct claims, no hedge language. Use
the video TITLES (no creator names). No anatomical jargon, no percentages,
no citations, no year stamps, no winner/loser framing.

Inputs:
- The headline (already chosen, must be supported): {headline}
- Video A title: {video_a_title}
- Video B title: {video_b_title}
- The lead insight that drove the headline:
{lead_insight}
- Top 2 system deltas with direction:
{top_2_deltas}
- Recipe A name + short description: {recipe_a_name} — {recipe_a_short}
- Recipe B name + short description: {recipe_b_name} — {recipe_b_short}

Voice exemplars (study carefully — these are the body anchors):
{exemplars}

Generate 3 candidate body paragraphs. Select the one that most clearly
supports the headline AND ends with a sentence that pulls the reader into
the rest of the page. Output only the selected paragraph as a single string.
No explanation.
```

### `recipe_description.txt`
```
You are writing the description paragraph for one video's recipe in a Brain Diff
strategy insight panel.

Brain Diff is a STRATEGY comparison. The description's job: take the matched
recipe's general template and customize it with this specific video's actual
cortical events. The result must feel like it was written about THIS video,
not the recipe in general.

Format: 2 sentences max, ≤ 35 words total. The first sentence describes what
the cortex did across the runtime. The second sentence is the "Built for X"
tag-line. The "Built for X" suffix MUST be wrapped in single asterisks like
*Built for retention.* — this gets rendered as italic.

The description MUST contain at least one timestamp from the input data
(format M:SS, e.g. 0:32).

No anatomical jargon. No percentages. No citations. No winner/loser framing.

Inputs:
- Matched recipe: {recipe_name}
- Recipe description template: {recipe_description_template}
- Built for tag: {built_for_tag}
- Video's chord moments with timestamps:
{chord_moments_formatted}
- Video's top 2 dimension peaks:
{top_peaks_formatted}
- Video subject: {video_display_name}

Voice exemplars:
{exemplars}

Generate 2 candidate descriptions in this voice. Select the one that uses the
most specific timestamp evidence. Output only the selected description.
No explanation.
```

### `recipe_match_rationale.txt`
```
You are writing a one-sentence rationale for a Brain Diff recipe match.

The recipe match itself was already determined deterministically by score-based
matching against a structured library. Your only job: write ONE plain-English
sentence explaining why this recipe matched, citing the score breakdown.

Format: 1 sentence, ≤ 35 words. No anatomical jargon. No percentages.
No citations. No winner/loser framing.

Inputs:
- Matched recipe name: {recipe_name}
- Matched recipe library_id: {library_id}
- Confidence score (0-1): {confidence}
- Score breakdown:
{score_breakdown_formatted}
- Video subject: {video_display_name}
- Top 2 cortical features that drove the match:
{top_features}

Output: just the sentence, no quotes, no preamble.
```

### `coupling_callout.txt`
```
You are writing one coupling callout for a Brain Diff results page Network
Coordination panel.

A "coupling callout" describes how strongly two cortical systems fire together
within a single video, and what that means for the cortex's cognitive strategy.
Brain Diff is a STRATEGY comparison — every callout reinforces this framing.

Format: 2 sentences, ≤ 38 words total. The first sentence describes what the
systems DID (rose together / pulled apart / one suppressed the other). The
second sentence ends with a recipe-relevant cognitive consequence — what the
cortex was DOING because of this coupling pattern.

Must reference both system names. No anatomical jargon. No percentages.
No citations. No winner/loser framing.

Inputs:
- Video subject: {video_display_name}
- Coupling type: {coupling_type} (strongest | weakest | anti)
- System pair: {system_a} ↔ {system_b}
- r-value: {r_value}
- Qualitative descriptor: {descriptor}
- This video's recipe: {recipe_name}

Voice exemplars:
{exemplars}

Generate 2 candidate callouts in this voice. Select the one with the strongest
recipe-relevant ending. Output only the selected 2-sentence callout as a
single string. No explanation.
```

### `chord_contextual_meaning.txt`
```
You are rewriting the meaning of a chord — but for THIS specific firing in
THIS specific video, not the generic textbook explanation.

The chord type's generic meaning is provided as reference. Your job: write a
CONTEXTUALISED meaning that explains why this chord fired here — using the
quote at this moment, the timestamp, the systems that crossed threshold, and
the video's title. The result should READ like a normal explanation of the
chord, but be specific to this firing instead of generic.

This REPLACES the generic meaning on the page — the user only sees yours.
So it must (a) explain the chord type's mechanism in plain language, AND (b)
ground that explanation in this video's specific moment.

Format: 2-3 sentences, ≤ 70 words. Direct, specific, plain English. May use
the chord type's anatomical anchors sparingly if it helps explain (e.g.
"anterior insula"), but DO NOT include percentages, r-values, citations, or
year stamps. No winner/loser framing. Use the video TITLE, not creator names.

Inputs:
- Chord type: {chord_name}
- Generic meaning (reference only — rewrite, don't quote): {generic_meaning}
- Firing timestamp (M:SS): {timestamp_human}
- Video title: {video_title}
- Quote at this moment: {quote}
- Specific cortical values that triggered the chord: {formula_values}
- The systems that crossed threshold for this chord: {triggering_systems}

Voice exemplars for this chord type (anchors):
{exemplars}

Generate 2 candidate contextualised meanings. Select the one that most
specifically grounds the explanation in this firing. Output only the selected
meaning. No explanation, no quotes around the output.
```

### `chord_context.txt`
```
You are writing one personalized sentence to append to a chord's general
meaning in the Brain Diff results page.

The chord type's meaning is already explained generically above your sentence.
Your job: add ONE sentence that grounds this specific firing in this specific
video. Reference the quote, the timestamp, the creator name, or a specific
cortical detail.

Format: 1 sentence, ≤ 22 words. Direct, specific, no hedge language.
No anatomical jargon. No percentages. No citations. No winner/loser framing.

Inputs:
- Chord type: {chord_name}
- Chord general meaning (already on page, do not repeat): {chord_meaning}
- Firing timestamp (M:SS): {timestamp_human}
- Firing video subject: {video_display_name}
- Quote at this moment: {quote}
- Specific values that triggered the chord: {formula_values}

Voice exemplars (this slot's anchors):
{exemplars}

Generate 2 candidate sentences. Select the one with the most specific grounding.
Output only the selected sentence as a single string. No explanation.
```

### `frame2_sub.txt`
```
You are writing the sub-paragraph below the Frame 02 heading on a Brain Diff
results page.

Frame 02 introduces the chord progression — the sequence of cortical events
each video fires across its runtime. The sub-paragraph's job: name both
recipes, explain what a chord is in plain language, set up the timeline below.

Format: 2-3 sentences, ≤ 50 words. Must reference both recipe names.
Must define what "chord" means in one phrase. No anatomical jargon.
No percentages. No citations. No winner/loser framing.

Inputs:
- Recipe A name: {recipe_a_name}
- Recipe B name: {recipe_b_name}
- Total chords detected (combined): {total_chord_count}
- Runtime: {runtime_seconds}s

Voice exemplars:
{exemplars}

Generate 2 candidates. Select the one that most clearly distinguishes the
two recipes. Output only the selected paragraph. No explanation.
```

---

## Voice we want (the bar to clear)

The product positions itself as data-grounded but plainspoken. Not academic, not corporate, not breathless. Examples of the **target tone** for each slot type:

**Headline** (must be: 2 sentences, each ≤10 words, mirrored structure):
- *"Fear drives every frame of the first video. Curiosity drives every frame of the second."*
- *"One ad earns attention through threat. The other earns it through wonder."*
- *"This pitch lands in the body. That one lands in the mind."*

**Body** (2–4 sentences, ≤90 words, supports the headline, ends with a hook):
- *"Both videos hit the same length, but the cortex never agreed on what mattered. The first kept the brain's threat system on a slow boil — heart-rate predictions stay elevated for 23 seconds straight. The second swapped that for a memory-encoding spike at 0:14 that's still firing six seconds later. The systems each one recruits explain why one feels visceral and the other feels useful."*

**Recipe description** (≤3 sentences, ≤60 words, must include timestamp + `*Built for X*`):
- *"The cortex front-loads attention by 0:08, then layers in memory encoding through the back half — a structure that primes recall before the message even lands. *Built for retention.*"*

**Coupling callout** (exactly 2 sentences, ≤38 words, must name both systems):
- *"Memory Encoding and Attention rose together across the runtime. The cortex was treating the message like a goal to be solved, not a scene to be watched."*

**Chord contextual meaning** (1–4 sentences, ≤100 words):
- *"At 0:14 — the line 'we're going to find out' — Suspense and Threat Detection cross threshold together. The cortex hits the specific alertness that comes before a high-stakes decision, not panic but the focused readiness of someone about to commit."*

**Frame2 sub** (2–4 sentences, ≤90 words, must mention both recipes + word "chord"):
- *"Hook → Hold and Slow Build → Deep Encode unfold differently across the runtime. A chord fires when two cortical systems cross threshold at the same second and hold; this is where each video's strategy becomes legible at the second-by-second level."*

---

## What I want back from you

Please return:

1. **A revised prompt for each of the 8 slots.** Same input variables (don't change the schema), but the prompt body should be re-engineered for what a 1B model can actually follow reliably. Specifically:
   - Make the format constraints unmissable (consider showing format as a literal example output, not a description)
   - Cut anything Gemma 1B will get confused by (multi-step "generate N candidates then pick" instructions are probably too much for 1B — replace with single-shot or chain-of-thought-then-final)
   - Embed system-level instructions in the first user turn (Gemma 3 has no system role)
   - Show 2–3 GOOD/BAD example pairs inline if it helps the model lock in
   - Keep the voice spec vivid

2. **A list of validator changes you recommend** if any rule is unrealistic for Gemma 1B. For each: which validator, what to relax/remove, and why. Don't relax anything that hurts brand voice (e.g., banned patterns stay).

3. **Sampling parameter recommendations.** Current is `temperature=1.0, top_p=0.95, top_k=64, do_sample=True` per Gemma 3 official docs. If you'd change them per slot (e.g. `headline` benefits from lower temperature for tighter format adherence), say so.

4. **Optional: a "validator-aware repair loop" suggestion.** Right now: one shot, fail → fallback. A simple repair loop ("here's what you wrote, here's what failed, fix it in one re-roll") could lift pass rates 30-50%. If you propose this, give me the prompt template for the repair turn.

5. **A test plan.** What 3-4 input pairs (text comparisons) should I run end-to-end to verify your changes hold? Pick contrasts that exercise different slots (e.g., a high-coupling pair to stress `coupling_callout`, a chord-rich pair to stress `chord_contextual_meaning`).

Format your reply as: numbered sections matching the 5 deliverables above. Use code blocks for prompts. Be opinionated.

---

## Files I'll wire your output into

- Prompts: `backend/results/prompt_templates/<slot>.txt`
- Validators: `backend/results/validators/<slot>.py`
- Sampling params: `backend/results/lib/model_manager.py` `GenerationRequest` defaults
- Repair loop (if added): new method on `ModelManager` or in each slot's runner

Schema and field names won't change — only the natural-language content of prompts and the rule thresholds in validators.
