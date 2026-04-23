# BrainDiff — Dimensions Specification (FINAL)

Reference: NORTH_STAR_FINAL.md

---

## Decision history
- v1: Used mean raw activation, Destrieux atlas, corpus-based z-score normalization
- v2: Switched to mean ABSOLUTE activation, HCP MMP1.0, within-stimulus normalization
- FINAL: Switched BACK to signed values for primary scores (standard fMRI practice per Falk et al.). abs() used only for normalization denominator and secondary magnitude metric. HCP MMP1.0 confirmed. Within-stimulus normalization kept.

---

## The Scoring Methodology (ALL dimensions)

### Step 1: Raw predictions
TRIBEv2 outputs (T, 20484). Values can be positive (activation above rest) or negative (deactivation below rest). Both are real signals.

### Step 2: Keep values signed
Do NOT take absolute value of the predictions for scoring. Signed values are the standard in fMRI ROI analysis. This is what Falk et al. extract using MarsBaR. This is what predicts real-world behavior.

### Step 3: Extract regional score
```python
regional = preds[:, mask]              # (T, n_vertices) — signed
raw_signed_mean = regional.mean()       # single number — the score
```

### Step 4: Normalize within-stimulus
```python
whole_brain_ref = np.median(np.abs(preds))   # abs ONLY here, for the denominator
normalized = raw_signed_mean / whole_brain_ref
```
Why abs() in the denominator only: the whole-brain median of signed values could be near zero (positive and negative cancel). Using abs for the denominator gives a stable reference scale. The numerator stays signed so we know the direction.

### Step 5: Diff
```python
delta = score_B - score_A    # signed
```
Positive = B activates this region more. Negative = A activates it more.

### Step 6: Secondary magnitude metric
```python
magnitude = abs(delta)       # for the confidence/size assessment only
```

### What the numbers mean
- score = 0.03: "This region has a small positive activation (above rest)"
- score = -0.01: "This region is slightly deactivated (below rest)"
- delta = +0.04: "Version B activates this region more than A by 0.04 units"
- delta = -0.02: "Version A activates this region more than B by 0.02 units"
- magnitude < 0.005: low confidence (difference may be noise)
- magnitude 0.005-0.02: medium confidence
- magnitude > 0.02: high confidence

These thresholds need to be calibrated during Phase 1 testing. The numbers above are starting estimates.

---

## The 5 Dimensions

### 1. Personal Resonance

**Plain English:** "Does this feel like it's about ME?"

**Scientific strength:** ★★★★★ — The #1 validated neural predictor of message effectiveness.

**Key evidence:**
- Falk et al. 2012 (Psych Science): 31 brains → predicted population behavior. mPFC was the signal. Self-report was wrong.
- Falk et al. 2016 (SCAN): 50 brains → predicted 400K email CTRs. R² up to 0.65.
- Scholz et al. 2025 (PNAS Nexus): Mega-analysis of 16 datasets confirmed self-related processing as core predictor.
- Kelley et al. 2002: mPFC significantly more active for "does this describe YOU?" vs "does this describe someone else?"

**Brain region:** Medial prefrontal cortex (mPFC)

**HCP MMP1.0 areas:** 10r, 10v, 9m, 10d, 32, 25 — BOTH hemispheres (mPFC is bilateral along the midline)

**Narrative template:** "Version B activates personal resonance [X]% more strongly. Content that engages this region tends to feel directly relevant to the reader. Higher activation here predicted population-level behavior change in Falk et al., 2012."

---

### 2. Social Thinking

**Plain English:** "Am I thinking about what other people think, feel, or intend?"

**Scientific strength:** ★★★★★

**Key evidence:**
- Saxe & Kanwisher 2003 (NeuroImage): Right TPJ activates specifically for others' beliefs. 3,000+ citations.
- Schurz et al. 2014: Meta-analysis of 73 studies confirming TPJ for social cognition.
- Scholz et al. 2025 (PNAS Nexus): Social processing = one of two key systems predicting message effectiveness.

**Brain region:** Temporoparietal junction (TPJ)

**HCP MMP1.0 areas:** PGi, PGs, TPOJ1, TPOJ2, TPOJ3 — RIGHT hemisphere only (theory of mind is right-lateralized)

**Narrative template:** "Version B activates social thinking [X]% more strongly. This region engages when we consider other people's perspectives and intentions. It's one of two key neural systems linked to message effectiveness (Scholz et al., 2025)."

---

### 3. Brain Effort

**Plain English:** "How hard is the brain working to process this?"

**Scientific strength:** ★★★★☆

**Key evidence:**
- Owen et al. 2005 (Human Brain Mapping): Meta-analysis of 24 working memory studies → dlPFC.
- Duncan & Owen 2000 (Trends in Neurosciences): dlPFC as "multiple demand" cortex.

**Brain region:** Dorsolateral prefrontal cortex (dlPFC)

**HCP MMP1.0 areas:** 46, p9-46v, a9-46v, 8C, 8Av — LEFT hemisphere (verbal working memory is left-lateralized)

**Narrative template:** "Version B demands [X]% more cognitive effort. Higher activation here means the brain is working harder to process the content — which could mean it's harder to understand, or that it's intellectually stimulating. Context matters."

---

### 4. Language Depth

**Plain English:** "How deeply is the brain's meaning-extraction system engaged?"

**Scientific strength:** ★★★★★

**Key evidence:**
- Fedorenko et al. 2010 (J Neurophysiology): Defined the language network as distinct from effort.
- Hagoort 2005 (Trends in Cognitive Sciences): Broca's area as the unification engine for meaning.
- Kutas & Hillyard 1980 (Science): The N400 — brain response scales with semantic surprise.

**Brain region:** Broca's area + Wernicke's area + superior temporal sulcus

**HCP MMP1.0 areas:** 44, 45, PSL, STV, STSdp, STSvp — LEFT hemisphere only (language is left-lateralized)

**Narrative template:** "Version B engages the language system [X]% more deeply. This network processes word meaning, sentence structure, and semantic complexity. More complex or surprising language drives higher activation (Kutas & Hillyard, 1980)."

---

### 5. Gut Reaction

**Plain English:** "Does this hit me viscerally?"

**Scientific strength:** ★★★★☆

**Key evidence:**
- Craig 2009 (Nature Reviews Neuroscience): Anterior insula = seat of interoceptive awareness. 2,000+ citations.
- Singer et al. 2004 (Science): Insula activates for own pain AND watching others' pain (empathy). 4,000+ citations.
- Wager & Barrett 2017: Insula tracks emotional intensity across many emotions.

**Brain region:** Anterior insula

**HCP MMP1.0 areas:** AVI, AAIC, MI — BOTH hemispheres (visceral response is bilateral)

**Narrative template:** "Version B produces [X]% more visceral response. The anterior insula fires for content that hits at a gut level — moral violations, empathy, bodily awareness. It tracks how intensely the content is felt, not what specific emotion (Craig, 2009)."

---

## Example output

### Single text:
```
"You nearly died today. Your family waited outside the hospital."

Personal Resonance:  +0.038 (high — "you", "your family")
Social Thinking:     +0.029 (moderate — family's perspective)
Brain Effort:        -0.005 (low — simple language)
Language Depth:      +0.008 (moderate)
Gut Reaction:        +0.042 (high — "nearly died")
```

### BrainDiff:
```
A: "Q3 revenue grew 3.2% YoY across all segments."
B: "You nearly died today. Your family waited outside."

                      A        B        Delta    Direction
Personal Resonance:  -0.002   +0.038   +0.040   B_higher  ●●●●
Social Thinking:     +0.003   +0.029   +0.026   B_higher  ●●●
Brain Effort:        +0.018   -0.005   -0.023   A_higher  ●●●
Language Depth:      +0.021   +0.008   -0.013   A_higher  ●●
Gut Reaction:        -0.008   +0.042   +0.050   B_higher  ●●●●●
```

---

## Excluded dimensions and why

| Candidate | Why excluded |
|-----------|-------------|
| Fear (amygdala) | Subcortical |
| Reward (ventral striatum) | Subcortical — #2 predictor in PNAS mega-analysis but unreachable |
| Memory (hippocampus) | Subcortical |
| Specific emotions | Need subcortical + cortical interplay |
| Visual processing | Irrelevant for text. Add when supporting video. |
| Auditory processing | Same. |

---

## Honesty section

1. These are TRIBEv2 predictions, not real fMRI scans.
2. Text is converted to speech internally — predictions reflect hearing, not reading.
3. The "average brain" is based on ~700 Western research participants.
4. HCP MMP1.0 parcel boundaries are group averages; real brains vary.
5. Signed values can be near zero for short or neutral texts — small deltas may be noise.
