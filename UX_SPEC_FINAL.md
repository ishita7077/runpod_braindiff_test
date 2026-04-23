# BrainDiff — UX Specification (FINAL)

Reference: NORTH_STAR_FINAL.md

This document defines every screen state, every interaction, and every word the user sees. It is the contract between the design vision and the code.

---

## 1. Product Choreography

The user experience is a sequence of 6 states. Each state has a clear purpose, a clear visual, and a clear exit.

### State 1: Landing

**Purpose:** Make the user understand what this does in 3 seconds and want to try it.

**What they see:**
```
┌─────────────────────────────────────────────────┐
│                                                 │
│              BrainDiff                         │
│                                                 │
│   See how two pieces of content land            │
│   differently in the human brain.               │
│                                                 │
│   ┌──────────────┐    ┌──────────────┐         │
│   │ Version A    │    │ Version B    │         │
│   │              │    │              │         │
│   │ paste text   │    │ paste text   │         │
│   │              │    │              │         │
│   └──────────────┘    └──────────────┘         │
│                                                 │
│           [ BrainDiff ]                        │
│                                                 │
│   Try an example:                               │
│   Corporate vs Human  ·  Clickbait vs Honest    │
│                                                 │
│   ─────────────────────────────────────────     │
│   Powered by TRIBEv2 (Meta FAIR)               │
│   Methodology →                                 │
│                                                 │
└─────────────────────────────────────────────────┘
```

**Rules:**
- NO explanation paragraph. No "how it works." The subtitle IS the explanation.
- Two text boxes side by side. Equal size. Labeled "Version A" and "Version B." Placeholder text: "Paste your first version here" / "Paste your second version here"
- The button says "BrainDiff" — not "Compare" or "Analyze" or "Submit"
- Example pairs are clickable one-liners below the button. Clicking one fills both text boxes instantly.
- "Methodology →" is a text link to the methodology page. Small. Bottom. For the curious.
- The landing state should feel like a tool, not a marketing page. No hero images, no testimonials, no pricing. Just the two boxes and the button.

### State 2: Compare Flow (user pastes text)

**What happens when the user types or pastes:**
- Text boxes grow vertically as content is added (auto-resize, max 300px height then scroll)
- Character count appears bottom-right of each box: "142 / 5000"
- If one box is empty when they hit the button → gentle shake animation on the empty box, placeholder text turns red briefly
- If text < 10 characters → proceed but the response will include a warning

**The button:**
- Disabled (grayed) until both boxes have text
- On hover: subtle glow
- On click: immediately transitions to loading state

### State 3: Loading Sequence

**Purpose:** Keep the user engaged during the 5-10 second processing time. Make the wait feel like something is happening, not like the app froze.

**What they see:**
```
┌─────────────────────────────────────────────────┐
│                                                 │
│   ◉ Processing through TRIBEv2...              │
│                                                 │
│   [brain outline, slowly filling with color]    │
│                                                 │
│   Converting text to speech...                  │
│   Predicting neural response for Version A...   │
│   Predicting neural response for Version B...   │
│   Computing brain contrast...                   │
│                                                 │
└─────────────────────────────────────────────────┘
```

**Rules:**
- Show a simplified brain outline that gradually fills with a warm color gradient (left to right, like blood flow)
- Below it, 4 status lines that appear sequentially as each real step completes:
  1. "Converting text to speech..." (TTS step)
  2. "Predicting neural response for Version A..." (first TRIBEv2 run)
  3. "Predicting neural response for Version B..." (second TRIBEv2 run)
  4. "Computing brain contrast..." (diff calculation)
- Each line gets a checkmark when done
- These are REAL status updates from the backend (sent via server-sent events or polling), not fake timers
- If it takes > 15 seconds, show: "Still processing — longer texts take more time"
- If it fails, show: "Something went wrong. Try shorter text or try again." with a retry button

### State 4: Result Reveal

**Purpose:** Show the answer with drama. This is the moment that determines whether they screenshot it.

**The reveal is NOT instant.** Results appear in a choreographed sequence:

1. **Hero headline fades in** (0.0s) — the single most important finding
2. **Winner callout appears** (0.3s) — which version "won" on the biggest dimension
3. **5 delta bars animate in** (0.6s) — bars grow from center outward, staggered by 0.1s each
4. **Brain heatmap fades in** (1.2s) — the visual hero
5. **Explanation text appears** (1.5s) — the narrative paragraph
6. **Share button pulses once** (2.0s) — subtle attention draw

Total reveal: 2 seconds. Fast enough to not feel slow, slow enough to feel intentional.

### State 5: Low-Confidence State

**When it triggers:** Any dimension with magnitude < 0.005, or text < 10 characters, or very large length mismatch between A and B.

**What it looks like:** The affected dimension's bar is drawn with a DASHED outline instead of solid. The delta number shows with a "~" prefix: "~+0.003" instead of "+0.003". Hovering shows a tooltip: "Small difference — may not be meaningful."

**The overall result still shows.** We don't hide results or show a big warning. We just visually indicate which dimensions are noisy. This respects the user's intelligence.

### State 6: Share Flow

**Trigger:** User clicks "Share" or "Copy Image" button.

**What happens:**
1. The share artifact is captured (see Section 5 for exact spec)
2. Brief flash animation on the result area (like a camera shutter)
3. "Copied to clipboard!" toast notification (disappears after 2s)
4. The image is also available as a downloadable PNG via "Download" secondary button

**No login required. No account required. No paywall. No email gate.** Share is frictionless.

---

## 2. Result Hierarchy

The result screen has exactly this visual hierarchy, top to bottom. Nothing rearranged. Nothing optional.

### Layer 1: Hero Headline

The single most screenshottable line on the page.

**Format:** One sentence describing the biggest shift.

**Template:**
```
"Version B hits harder on [biggest dimension in plain English]"
```
or
```
"Version A demands more [biggest dimension in plain English]"
```

**Examples:**
- "Version B hits harder on personal resonance"
- "Version A demands more brain effort"
- "Nearly identical brain response — the difference is in language depth"

**Rules:**
- Max 12 words
- Uses dimension names in PLAIN ENGLISH (never "mPFC" or "dlPFC" in the headline)
- If the biggest delta is low-confidence, the headline says "Nearly identical brain response" instead of picking a winner
- Font: largest on the page. Serif. White on dark.

### Layer 2: Winner Callout

A compact summary strip directly below the headline.

**Format:**
```
B wins on 3 dimensions  ·  A wins on 1  ·  1 tied
```

**Rules:**
- "Wins" means delta magnitude > 0.005 (above noise threshold)
- "Tied" means delta magnitude < 0.005
- One line. Small text. Gray. Informational, not dramatic.

### Layer 3: Five Delta Bars

The core data display.

**Layout:**
```
Personal Resonance    ████████████░░░░░░░░░░░░  A: 0.012  B: 0.038  +0.026 →
Social Thinking       ░░░░░░░░████████████████  A: 0.029  B: 0.003  -0.026 ←
Brain Effort          ░░░░░░░░░░░░░██████░░░░░  A: 0.018  B: 0.011  -0.007 ←
Language Depth        ░░░░░░░░░░░░████████████  A: 0.031  B: 0.008  -0.023 ←
Gut Reaction          ██████████████████░░░░░░  A: -0.003 B: 0.042  +0.045 →
```

**Design:**
- Bars centered on zero. Extend RIGHT for B > A (green/teal). Extend LEFT for A > B (red/coral).
- Bar length proportional to delta magnitude (longest delta = full bar width, others scaled relative)
- Each row shows: Dimension name | Bar | Score A | Score B | Delta with arrow
- Sorted by delta magnitude (biggest difference at top) — NOT in fixed order
- Low-confidence dimensions: dashed bar outline, "~" prefix on delta
- Hover on any bar: tooltip with the brain region name and one-sentence explanation

**Dimension names in UI language (never use jargon in the bars):**

| Internal name | UI label | Tooltip |
|---|---|---|
| personal_resonance | Personal Resonance | "How much the brain processes this as self-relevant (mPFC)" |
| social_thinking | Social Thinking | "How much the brain considers others' perspectives (TPJ)" |
| brain_effort | Brain Effort | "How hard the brain works to process this (dlPFC)" |
| language_depth | Language Depth | "How deeply the brain extracts meaning (Broca's + Wernicke's)" |
| gut_reaction | Gut Reaction | "How viscerally the brain responds (anterior insula)" |

### Layer 4: Brain Heatmap

**What it shows:** 4 views of the brain surface (lateral left, lateral right, medial, top-down) with the signed vertex-level diff painted on. Red/warm = B activated more. Blue/cool = A activated more. Gray = no difference.

**Size:** Full width of the result area. This is the HERO VISUAL — the thing that makes screenshots look impressive.

**Label:** "Brain activation difference: red = Version B higher, blue = Version A higher"

**Generated on backend** using nilearn's `plot_surf_stat_map` and returned as PNG/SVG.

### Layer 5: Explanation

The narrative paragraph. Explanatory + cited.

**Template:**
```
"Version B activates personal resonance [X]% more strongly — the brain region
that processes self-relevant content. In published research, higher activation
here predicted real-world behavior change at population scale (Falk et al., 2012).

The biggest drop is in language depth — Version A engages the meaning-extraction
system [X]% more, suggesting more complex or novel language.

Brain effort and gut reaction showed [similar/different] patterns."
```

**Rules:**
- Max 4 sentences
- Every claim references a paper
- Uses "the brain region that..." framing (educates while explaining)
- Neutral dimensions get one summary sentence, not individual treatment
- Never says "you should use Version B" — state what the brain does, let the user decide

### Layer 6: Methodology Drill-Down

A single text link at the bottom of results: "How this works →"

Links to the methodology page (see Section 6). Does NOT open in a new tab — scrolls to a section below, or opens as an expandable panel. The user should be able to go from "I'm curious" to "I understand" without leaving the result.

---

## 3. Visual Language

### Screen Structure
```
┌─────────────────────────────────────────────────┐
│  BrainDiff                    Methodology →    │  ← fixed top bar
├─────────────────────────────────────────────────┤
│                                                 │
│  [INPUT AREA or RESULTS AREA]                   │  ← main content
│                                                 │
├─────────────────────────────────────────────────┤
│  TRIBEv2 · Meta FAIR · Population-average brain │  ← persistent footer
└─────────────────────────────────────────────────┘
```

### Visual Priority (what the eye hits first)
1. Hero headline (biggest text, top of results)
2. Brain heatmap (biggest visual, middle of results)
3. Delta bars (the data, between headline and heatmap)
4. Explanation text (below heatmap)
5. Everything else

### How "science" is signaled without looking academic
- **Dark background** — signals seriousness (Bloomberg, NASA mission control, medical imaging software)
- **Serif font for headlines** — signals editorial authority (NYT, Nature, The Economist)
- **Monospace for data** — signals precision (terminal, code, scientific instruments)
- **Brain heatmap** — the single strongest "this is real science" signal. A 3D brain with activation colors IS the credibility.
- **Cited claims in the explanation** — "(Falk et al., 2012)" signals peer review without being a paper
- **NO lab coat imagery. NO DNA helixes. NO "powered by AI" badges.** These are what fake science tools use.

### How "shareable" is balanced with "credible"
- The hero headline is shareable (plain English, dramatic, tweetable)
- The brain heatmap is shareable (visually stunning, looks impressive)
- The delta bars are shareable (clear data, easy to read in a screenshot)
- The citations are credible (real papers, real authors, real journals)
- The methodology link is credible (transparency, "we show our work")
- The persistent footer is credible ("population-average brain" — we're not hiding limitations)

The balance: **the TOP of the result is optimized for sharing. The BOTTOM is optimized for credibility.** A screenshot captures the shareable parts. A curious reader scrolls to the credible parts.

---

## 4. Output Semantics

### What each dimension means in user-facing language

| Dimension | User-facing meaning | What to do with it |
|---|---|---|
| Personal Resonance | "Does this feel like it's about the reader?" | If your goal is behavior change or personal connection, higher is better |
| Social Thinking | "Does this make you think about other people?" | If your goal is empathy, perspective-taking, or social sharing, higher is better |
| Brain Effort | "Is the brain working hard to process this?" | Higher is NOT always bad — could mean intellectually engaging OR confusing. Depends on your audience. |
| Language Depth | "How much semantic processing is happening?" | Higher = more complex or surprising language. Good for depth, bad for accessibility. |
| Gut Reaction | "Does this hit viscerally?" | Higher = stronger felt response. Good for emotional content, could be too intense for some contexts. |

### What "confidence" means to the user
- **High confidence:** "The difference is clear."
- **Medium confidence:** "There's a difference, but it's modest."
- **Low confidence (~):** "The difference is small enough to be noise. Don't make decisions based on this dimension."

The user never needs to understand the math behind confidence. They just need to know: solid bar = real difference, dashed bar = maybe noise.

### What claims are SAFE to make in the UI
- "Version B activates [region] more strongly" ✅
- "Higher [dimension] has been linked to [outcome] in research" ✅
- "The brain processes these two texts differently in [region]" ✅
- "[Dimension] is one of two neural systems linked to message effectiveness (Scholz et al., 2025)" ✅

### What claims are FORBIDDEN in the UI
- "Version B will get more engagement" ❌
- "Version B is better" ❌
- "Your audience will prefer Version B" ❌
- "This content will go viral" ❌
- "BrainDiff predicts performance" ❌
- Any claim without a citation ❌

---

## 5. Share Artifact Spec

The share image is the single most important growth mechanism. It must look perfect on Twitter, LinkedIn, and iMessage.

### Dimensions
- **Width:** 1200px (Twitter card standard)
- **Height:** 675px (16:9 ratio, fits Twitter and LinkedIn preview)
- **Background:** Same dark background as the app
- **Format:** PNG (not JPEG — text needs to be crisp)

### Layout
```
┌─────────────────────────────────────────────────────────────────┐
│  BrainDiff                                                     │
│                                                                 │
│  "Q3 revenue grew 3.2% YoY..."    vs    "You nearly died..."   │
│                                                                 │
│  ── Version B hits harder on gut reaction ──                    │
│                                                                 │
│  Gut Reaction      ████████████████████  +0.045 →               │
│  Personal Res.     ██████████████       +0.026 →                │
│  Social Thinking   █████████            +0.018 →                │
│  Language Depth    ░░░░░████            -0.013 ←                │
│  Brain Effort      ░░░░░░░░████         -0.023 ←                │
│                                                                 │
│  [brain heatmap - small, right-aligned]                         │
│                                                                 │
│  braindiff.xyz  ·  TRIBEv2 / Meta FAIR  ·  April 2026          │
└─────────────────────────────────────────────────────────────────┘
```

### Rules
- Both texts shown, truncated to ~60 characters with "..."
- Hero headline centered
- 5 bars with deltas (no raw scores — too cluttered for a share image)
- Brain heatmap: small, right-aligned, one view only (lateral right — most recognizable brain shape)
- Bottom line: brand + model + date. Small. Gray.
- NO "Share on Twitter" or social icons IN the image. Those are buttons on the page.

### What can be omitted from the share image
- Raw score_a and score_b numbers (show only deltas)
- The full explanation paragraph (too much text)
- The methodology link
- Confidence indicators (too nuanced for a screenshot)

### What CANNOT be omitted
- Both input texts (truncated)
- The hero headline
- All 5 delta bars
- The brain heatmap (even small — it's the visual hook)
- "braindiff.xyz" branding
- Model/date attribution

---

## 6. Methodology Page

This is NOT a disclaimer. It's a research journey written for a curious reader who has GPT available to look things up. Simple words. Real science. The reader should finish it feeling smarter.

### Structure

**Title:** "How BrainDiff Works"

**Section 1: What this does (2 sentences)**
BrainDiff shows how two pieces of content engage the human brain differently. It uses a brain model trained on real fMRI scans of 700+ people to predict which brain regions respond more to each version.

**Section 2: Where the brain data comes from**
The predictions come from TRIBEv2, an open-source model released by Meta's AI research lab in March 2026. It was trained on 1,115 hours of fMRI recordings — brain scans that track blood flow while people watched movies, listened to podcasts, and read text. When neurons in a brain region fire, they need oxygen. Fresh blood rushes to that spot. The fMRI picks up this blood flow change. TRIBEv2 learned the pattern: given a stimulus, it predicts where blood would flow in the average brain.

One important detail: when you paste text into BrainDiff, TRIBEv2 converts it to speech first and processes it as audio. This means the predictions reflect how the brain would respond to HEARING the text read aloud, not silently reading it. The brain regions for listening and reading overlap about 80%, but they're not identical.

**Section 3: What the 20,484 numbers are**
TRIBEv2's output is 20,484 numbers, one per point on the brain's cortical surface. Imagine the brain's outer layer (the cortex — the wrinkly part) covered with 20,484 evenly-spaced pins, like pins on a map. Each pin gets a number: how much blood flow is predicted at that spot. Positive = more than resting state. Negative = less than resting state (the region is actively suppressing).

These 20,484 pins sit on a standard template called fsaverage5. The same pin #7,342 is in the same spot on everyone's brain. This lets us compare across people and across texts.

**Section 4: How we group pins into brain regions**
We use the HCP MMP1.0 atlas (Glasser et al. 2016, published in Nature), which divides the cortex into 360 named areas based on brain function, not just shape. We group specific areas into 5 dimensions:

[Show the 5 dimensions with their area names and brain region names — same table as DIMENSIONS_SPEC_FINAL.md but in plain English]

**Section 5: Why these 5 and not others**
Two rules: (1) the region must be on the cortical surface (TRIBEv2 can't see deep-brain structures like the amygdala), and (2) published research must show it matters for how people process content.

The most important evidence: Emily Falk at the University of Michigan scanned 31 smokers watching anti-smoking ads. She found that activation in the medial prefrontal cortex (our "personal resonance" dimension) predicted which ad campaign would drive the most quit-line calls at population scale — when the smokers' own opinions predicted wrong. She replicated this with 50 brains predicting 400,000 email click-through rates.

A mega-analysis published in PNAS Nexus in 2025 pooled 16 brain imaging studies (572 participants, 739 messages) and confirmed: self-related processing and social processing are the two neural systems that most consistently predict whether a message works.

We can't measure reward (the other key predictor from the mega-analysis) because the reward center (ventral striatum) is deep inside the brain, not on the surface.

**Section 6: How we compute the comparison**
For each text:
1. TRIBEv2 predicts blood flow at 20,484 points, one prediction per second of audio
2. For each of our 5 dimensions, we average the predicted blood flow across the points that belong to that brain region, then average across time
3. We keep the sign: positive means the region activated, negative means it suppressed

For the comparison:
4. We subtract Version A's score from Version B's score
5. Positive difference = Version B activated this region more. Negative = Version A did.

This is a brain response contrast — comparing how two stimuli engage the brain differently. It's grounded in the tradition of cognitive subtraction, the foundational method of fMRI research since 1990, where scientists compare brain activity between two conditions to see what changes.

**Section 7: What this is NOT**
- It does not predict engagement, likes, or sales
- It does not read YOUR brain — it predicts the average brain of 700+ research participants
- It does not measure fear, reward, or specific emotions (those require deep-brain structures we can't see)
- It does not guarantee that "higher personal resonance" means "better content" — that depends on your goal

**Section 8: Why compare, not score**
We deliberately built a comparison tool, not a scoring tool. Here's why:

A single score ("your tweet is 73/100") invites the question "is that good?" — and we can't answer that honestly. We haven't proven that any specific score predicts real-world outcomes.

A comparison ("Version B activates personal resonance 40% more than Version A") is factually true regardless. The model predicts different brain patterns for different inputs. The DIFFERENCE is the information. Whether that difference matters for your goals is your call, not ours.

This is also how the science works. Falk didn't score individual ads on an absolute scale. She compared which ad produced MORE mPFC activation, and the one with more predicted the population's behavior better.

**Section 9: Whose brain is "average"?**
TRIBEv2 was trained on data from 700+ volunteers at research institutions. These are overwhelmingly Western, educated, and likely right-handed adults who agreed to lie inside an fMRI scanner for hours. This is the "average brain" we're predicting. Your brain, your audience's brain, may respond differently — especially across cultures, age groups, and neurological conditions.

---

## What this UX spec does NOT include (by design)

- **Mobile layout.** v0 is desktop. Mobile is v1.
- **Accounts or saved results.** v0 is anonymous. Save is v1.
- **Multiple comparisons.** v0 is two texts at a time. Multi-comparison is v1.
- **Video/audio input.** v0 is text only. Multimodal is v1.
- **Pricing.** v0 is free. Monetization is not a v0 question.
