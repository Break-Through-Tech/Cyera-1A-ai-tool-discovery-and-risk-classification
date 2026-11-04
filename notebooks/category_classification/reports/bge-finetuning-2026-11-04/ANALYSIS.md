# Interpretation of the bounded BGE experiments

The experiments did not establish a reliable improvement in the primary target,
validation homepage category accuracy. Keep the existing backend configuration.
All results use 2,739 validation descriptions and 106 validation homepages, k=15,
the unchanged cutoff, and a training-only reference index. The test split was
not scored. See [the measured comparison](REPORT.md) and [complete metrics](comparison.csv).

The original 128-token BGE baseline scored 55/106 homepages (51.89%). The
64-update random run scored 56/106 (52.83%), fixing one case without a regression.
Its second seed scored 55/106, fixing one case and regressing one. Across the two
seeds, the mean was 52.36% and the range was 51.89–52.83%. The one-case gain did
not repeat. Two seeds on this small reused validation set do not establish an
independent performance claim.

The 256-update random run and the matched mixed-sampling run each scored 54/106
homepages (50.94%). Each fixed two homepage cases but regressed three. Mixed
sampling improved description accuracy to 56.70%, with 51 errors fixed and 38
introduced, but lowered homepage macro-F1 to 0.3261 from the matching baseline's
0.3792. Catalog-description improvement did not transfer to the homepage target.
The retained random update-128 checkpoint also had no homepage accuracy gain.
The deployed baseline, with its original preprocessing/runtime, scored 57/106
(53.77%) and remains unchanged. Preprocessing/runtime effects must be kept
separate from encoder-training effects.

The mixed sampler supplied 533 semi-hard negatives, 487 random negatives and
four random fallbacks in 1,024 unique triplets. The actual semi-hard fraction was
52.05%, with a 0.74% fallback rate among semi-hard requests. It covered 2,371
training tools, versus 2,415 for random run B and 719 for random run A. Losses
across different samplers are not directly comparable because the triplets differ;
checkpoint selection used KNN performance rather than minimum training loss.

Input mismatch is a concrete remaining issue to investigate. Training descriptions
had a 12-token median, with only 2/8,214 longer than 128 tokens. The 265 eligible
training homepages had a 539-token median; 78.87% exceeded 128 tokens and 68.68%
exceeded 256. These counts measure truncation, not the location of important
functional information. Training-only homepage anchors and matched 128/256-token
comparisons are supported as separate experiments; no homepage-transfer training
or longer-token accuracy experiment was mixed into the reported runs.

The training-only human-review queue is at
`artifacts/category_finetuning/label-review-v2/`. It combines bounded neighbor
search with existing frozen near-description flags restricted to training IDs,
prioritizes repeated category confusions and near-identical cross-category text,
and includes empty human-decision/provenance fields. Disagreements can reflect
label ambiguity or multifunctional tools; they are not automatic corrections.
No approved versioned category corrections were supplied, so corrected-label
comparisons remain unmeasured. The implementation evaluates original and trained
BGE against the same corrected reference labels when approved overrides are used.

Training and checkpoint/full-evaluation time are reported separately, including
the expensive index encodings. The reference and trained candidates, all saved
checkpoints, example-level votes and neighbors, original pilot files and default
backend configuration remain available. No cutoff, neighbor-count or margin
tuning, learning-rate grid, trainable-block expansion or Gemini fallback was introduced.

Verification: 20 offline experiment tests and all six backend category tests pass.
Checks cover unique sampling, training/group isolation, deterministic epoch
shuffling, interrupted versus uninterrupted weights/RNG across epochs, callback
mode restoration, crash-truncated log tails, content-checked embedding caches,
saved-model reload, neighbor voting and human-review queue isolation.
