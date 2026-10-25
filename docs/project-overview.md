# Project Overview: Reel Fact-Checker

## One-Line Pitch
A web app that tells you whether an Instagram reel is showing real, current events or old footage passed off as news.

## The Problem
Fake and misleading reels spread fast. A common pattern is recycled footage:

- A plane crash video from 10 years ago is posted with the caption "today at Hyderabad".
- Old military test footage is shared as if Indian jets were shot down during a war.

Ordinary viewers have no quick way to check. By the time a fact-check article appears, the reel has already been seen by millions and has caused panic, hate or misinformation.

## What I Want to Build
A SaaS application where a user submits a reel and gets a clear report within about a minute:

1. **What the reel claims** (event, place, date), pulled from its caption, on-screen text and speech.
2. **Where the footage really comes from**, including the earliest time and place it appeared online.
3. **A verdict** on whether the footage matches the claim, with the evidence and source links shown.

## Who It Is For
- **Everyday social media users** who want to check a shocking reel before sharing it
- **Journalists and fact-checkers** who need a fast first-pass check
- **Students and volunteer groups** who run community awareness efforts
- **Later:** news organisations, through an API

## How It Will Work (Simple View)
1. The user uploads the reel (or a screen recording of it).
2. The system extracts key frames, audio and text.
3. It searches for earlier appearances of the same footage and for existing fact-checks.
4. It compares the claim with the evidence.
5. It shows a report: verdict, confidence, sources and a shareable link.

## Verdicts
| Verdict | Meaning |
|---|---|
| Debunked | Fact-checkers have already reviewed this claim |
| Likely old footage | Matching footage exists with an earlier date |
| No contradiction found | Nothing earlier found (not proof that it is real) |
| Unverified | Not enough information to judge |

The app never claims a reel is "100% real". It reports evidence and is honest about uncertainty.

## Key Features (MVP)
- Upload a reel and get an automatic analysis
- Claim extraction from speech and on-screen text, including Telugu, Hindi and English
- Search for earlier uploads and existing fact-checks
- Evidence report with side-by-side frames and source links
- Shareable result page that people can post on WhatsApp and social media
- Manual-check helper links (Google Lens, Yandex)

## Later Features
- WhatsApp and Telegram bot (forward a reel, get a report)
- Browser extension
- Audio fingerprint matching
- AI-generated video detection
- Location and weather consistency checks
- API and dashboard for newsrooms

## What Makes It Different
- Focused on the most common kind of misinformation: **old footage presented as new**
- Gives **evidence and sources**, not just a "fake" label
- Builds its own **database of known recycled footage**, which gets more valuable over time
- Designed for Indian users: regional languages and India-focused events
- Built entirely on **free tools and free APIs**, so it can start with zero cost

## Constraints and Decisions
- **No scraping of Instagram.** Users provide the file, which avoids legal and blocking problems.
- **"Real time" means on-demand.** Each reel is analysed in 30 to 60 seconds, not live monitoring of all of Instagram.
- **Free stack only:** ffmpeg, Whisper, OCR, CLIP, Google Fact Check API, YouTube Data API, Gemini free tier, free hosting.
- **Privacy:** uploaded videos are deleted after analysis; only fingerprints and results are kept.

## Success Measures
- Correctly flags known recycled-footage test cases
- Very few genuine reels wrongly flagged as old
- Report ready in under 60 seconds
- Users share reports and come back to check more reels

## Risks and How to Handle Them
| Risk | Plan |
|---|---|
| Free API quotas run out | Cache every result, check own database first, return partial reports |
| Wrong verdict | Show confidence and sources, add a "report an error" button, review early results manually |
| No earlier match exists | Say "no contradiction found" instead of calling it real |
| Heavily edited or cropped footage | Use CLIP embeddings alongside hashes; keep improving thresholds with test data |
| Misuse or defamation concerns | Report only what the evidence shows, never accuse a person |

## Roadmap
| Stage | Goal |
|---|---|
| Weeks 1-3 | Working script: claim extraction and evidence search |
| Weeks 4-5 | Backend API and web interface |
| Weeks 5-6 | Own index of known footage, testing |
| Week 7 | Deploy on free hosting |
| Week 8+ | Launch to journalists and students, collect feedback, add the WhatsApp bot |

## Vision
Make checking a viral reel as easy as sharing it, so that people stop and verify before forwarding.
