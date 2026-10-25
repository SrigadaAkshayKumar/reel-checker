# Fingerprint benchmark: 2026-10-25 09:35

6 source videos × 17 edits (**synthetic footage**: a self-check of the method, not a measurement on real reels)

## Current thresholds (strong 0.9, weak 0.8)

Recall 100% averaged over edits · false matches 0 of 510 cross-source pairs

| Edit | What it imitates | Recall | False matches |
|---|---|---|---|
| reencode | heavy re-compression at 480p | 100% | 0/30 |
| crop10 | 10% crop | 100% | 0/30 |
| crop20 | 20% crop | 100% | 0/30 |
| mirror | mirrored | 100% | 0/30 |
| letterbox_9x16 | landscape clip in a vertical reel | 100% | 0/30 |
| blurbg_9x16 | vertical reel over a blurred copy of itself | 100% | 0/30 |
| caption | caption strip burned into the picture | 100% | 0/30 |
| caption_9x16 | vertical reel with a caption in the top bar | 100% | 0/30 |
| watermark | channel logo in the corner | 100% | 0/30 |
| color | colour grading | 100% | 0/30 |
| blur | soft / out of focus | 100% | 0/30 |
| speed | sped up 1.33x | 100% | 0/30 |
| rotate3 | tilted 3 degrees | 100% | 0/30 |
| pip60 | picture-in-picture at 60% | 100% | 0/30 |
| screenrec | phone screen recording of the reel | 100% | 0/30 |
| excerpt | 10-second excerpt | 100% | 0/30 |
| combo | crop + mirror + caption + colour + heavy re-compression | 100% | 0/30 |

## Separation

Worst 10% of true matches reach 0.91 on their best frame; the closest wrong source reaches 0.78 (99th percentile 0.75). Thresholds belong in the gap.

## Best safe setting

strong 0.94, weak 0.8: recall 100%. No false matches here, and at most 0.01 expected chance matches per reel in a 1,000,000-fingerprint index (binomial estimate; real images are less random, so keep the margin).

| Edit | Recall |
|---|---|
| reencode | 100% |
| crop10 | 100% |
| crop20 | 100% |
| mirror | 100% |
| letterbox_9x16 | 100% |
| blurbg_9x16 | 100% |
| caption | 100% |
| caption_9x16 | 100% |
| watermark | 100% |
| color | 100% |
| blur | 100% |
| speed | 100% |
| rotate3 | 100% |
| pip60 | 100% |
| screenrec | 100% |
| excerpt | 100% |
| combo | 100% |

## Grid

Chance matches = expected unrelated matches per reel in a 1,000,000-fingerprint index.

| Strong | Weak | Recall | False matches here | Chance matches at scale |
|---|---|---|---|---|
| 0.84 | 0.7 | 100% | 31 | 4.17e+04 |
| 0.84 | 0.74 | 100% | 0 | 116 |
| 0.84 | 0.76 | 100% | 0 | 12.3 |
| 0.84 | 0.78 | 100% | 0 | 1.81 |
| 0.84 | 0.8 | 100% | 0 | 0.843 |
| 0.84 | 0.82 | 99% | 0 | 0.839 |
| 0.84 | 0.84 | 99% | 0 | 0.839 |
| 0.86 | 0.7 | 100% | 31 | 4.17e+04 |
| 0.86 | 0.74 | 100% | 0 | 115 |
| 0.86 | 0.76 | 100% | 0 | 11.5 |
| 0.86 | 0.78 | 100% | 0 | 0.993 |
| 0.86 | 0.8 | 100% | 0 | 0.0274 |
| 0.86 | 0.82 | 97% | 0 | 0.0236 |
| 0.86 | 0.84 | 97% | 0 | 0.0234 |
| 0.86 | 0.86 | 94% | 0 | 0.0234 |
| 0.88 | 0.7 | 100% | 31 | 4.17e+04 |
| 0.88 | 0.74 | 100% | 0 | 115 |
| 0.88 | 0.76 | 100% | 0 | 11.5 |
| 0.88 | 0.78 | 100% | 0 | 0.972 |
| 0.88 | 0.8 | 100% | 0 | 0.00725 |
| 0.88 | 0.82 | 97% | 0 | 0.0034 |
| 0.88 | 0.84 | 97% | 0 | 0.00322 |
| 0.88 | 0.86 | 94% | 0 | 0.00321 |
| 0.9 | 0.7 | 100% | 31 | 4.17e+04 |
| 0.9 | 0.74 | 100% | 0 | 115 |
| 0.9 | 0.76 | 100% | 0 | 11.5 |
| 0.9 | 0.78 | 100% | 0 | 0.97 |
| 0.9 | 0.8 | 100% | 0 | 0.00443 |
| 0.9 | 0.82 | 97% | 0 | 0.000576 |
| 0.9 | 0.84 | 97% | 0 | 0.000387 |
| 0.9 | 0.86 | 94% | 0 | 0.000379 |
| 0.92 | 0.7 | 100% | 31 | 4.17e+04 |
| 0.92 | 0.74 | 100% | 0 | 115 |
| 0.92 | 0.76 | 100% | 0 | 11.5 |
| 0.92 | 0.78 | 100% | 0 | 0.969 |
| 0.92 | 0.8 | 100% | 0 | 0.00408 |
| 0.92 | 0.82 | 97% | 0 | 0.000234 |
| 0.92 | 0.84 | 97% | 0 | 4.56e-05 |
| 0.92 | 0.86 | 93% | 0 | 3.78e-05 |
| 0.94 | 0.7 | 100% | 31 | 4.17e+04 |
| 0.94 | 0.74 | 100% | 0 | 115 |
| 0.94 | 0.76 | 100% | 0 | 11.5 |
| 0.94 | 0.78 | 100% | 0 | 0.969 |
| 0.94 | 0.8 | 100% | 0 | 0.00405 |
| 0.94 | 0.82 | 97% | 0 | 0.000197 |
| 0.94 | 0.84 | 97% | 0 | 7.93e-06 |
| 0.94 | 0.86 | 93% | 0 | 2.02e-07 |

This measures fingerprints only. It says nothing about claim extraction or the external searches; `run.py eval` measures the whole pipeline on labelled reels.
