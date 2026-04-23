# BrainDiff — North Star & Goals (FINAL)

## North Star
Build a product that goes viral, is genuinely useful, and looks professional.

## The Product
Drop in two versions of anything — two tweets, two headlines, two pitches — and see the predicted brain difference as a visual heatmap with plain-English explanation.

## Three Success Criteria
1. **Useful** — helps someone make a better decision about their content before they publish/spend
2. **Viral** — every output is an inherently shareable artifact (the brain diff map + scores)
3. **Professional** — aesthetics and credibility signal real science, not a toy

## Who It's For
Content creators, marketers, founders, communicators — anyone who chooses between two versions of something.

## The Verb
Compare. Not score. Not label. Not predict. Compare.

## The Science
Brain response contrast — comparing how the average human brain processes two stimuli differently. Grounded in the tradition of cognitive subtraction (100,000+ fMRI studies since 1990). Validated by Falk et al. (2012, 2016), Dmochowski et al. (2014), Scholz et al. (2025 PNAS mega-analysis of 16 datasets, 572 participants, 739 messages).

We do NOT call what we do "cognitive subtraction" — we call it "brain response contrast." We cite cognitive subtraction as the foundational method that inspired the approach.

## What We Measure (Tier 1 only)

| Dimension | Brain Region | Atlas (HCP MMP1.0) | Primary Method |
|-----------|-------------|---------------------|----------------|
| Personal Resonance | mPFC | 10r, 10v, 9m, 10d, 32, 25 (bilateral) | Signed mean ROI contrast |
| Social Thinking | TPJ | PGi, PGs, TPOJ1-3 (right) | Signed mean ROI contrast |
| Brain Effort | dlPFC | 46, p9-46v, a9-46v, 8C, 8Av (left) | Signed mean ROI contrast |
| Language Depth | Broca's + Wernicke's + STS | 44, 45, PSL, STV, STSdp, STSvp (left) | Signed mean ROI contrast |
| Gut Reaction | Anterior insula | AVI, AAIC, MI (bilateral) | Signed mean ROI contrast |

## Methodology
1. Get TRIBEv2 prediction for each text: shape (T, 20484)
2. Keep values SIGNED (positive = activation, negative = deactivation — both are informative)
3. For each dimension: compute mean signed activation across its HCP MMP1.0 vertices, then across time
4. For diff: subtract A's score from B's score. Positive = B activated this region more.
5. Heatmap uses same signed math: per-vertex mean(B) - mean(A)

## Narrative Style
Explanatory + cited. Every claim backed by a paper.
"Version B activates personal resonance 40% more. Higher activation here predicted population-level behavior change in Falk et al., 2012."

## What We Don't Claim
- We don't predict engagement, likes, or virality
- We don't read individual brains — this is the average brain
- We don't measure fear, reward, or specific emotions (subcortical)
- The diff shows how the brain processes two stimuli differently — interpretation is the user's job

## Decision Log
| Decision | What we chose | Why |
|----------|--------------|-----|
| Signed vs abs values | **Signed** (primary) | Standard in fMRI ROI analysis. Falk uses signed. More useful for directional diff. abs() only for secondary magnitude metric. |
| Atlas | **HCP MMP1.0** (hard requirement) | Functionally defined, 360 parcels, modern standard. No silent Destrieux fallback. |
| Normalization | **Within-stimulus** (region / whole-brain median of abs) | Self-contained, no corpus needed. |
| Narrative | **Explanatory + cited** | Viral requires meaning. Raw numbers aren't shareable. Every claim has a paper. |
| Framing | **"Brain response contrast"** not "cognitive subtraction" | Honest about what we're doing. Better positioning anyway. |
| Methodology disclosure | **Full page, simple words** | Not a disclaimer. A research journey for curious readers. |
