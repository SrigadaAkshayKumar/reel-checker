"""Rule-based verdict (docs/workflow.md, Phase 3). The LLM never decides; it
only explains the verdict these rules reach from the retrieved evidence."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.config import Settings
from .models import DEBUNKED, LIKELY_OLD_FOOTAGE, NO_CONTRADICTION_FOUND, UNVERIFIED, Check, Claim, Evidence

EVIDENCE_CHECKS = ("own_index", "fact_check", "youtube", "vision_web")


@dataclass
class InputQuality:
    duration: float
    total_frames: int
    usable_frames: int
    has_speech: bool
    has_text: bool  # caption or on-screen text

    def problems(self, settings: Settings) -> list[str]:
        out = []
        if self.duration < settings.min_video_seconds:
            out.append(f"the video is only {self.duration:.1f} s long")
        if self.total_frames and self.usable_frames == 0:
            out.append("every keyframe is too dark or too flat to fingerprint")
        return out


@dataclass
class Verdict:
    verdict: str
    confidence: float
    reasons: list[str] = field(default_factory=list)


def _match_score(e: Evidence) -> float:
    return max(e.similarity or 0.0, e.clip_similarity or 0.0)


def decide(settings: Settings, claim: Claim, evidence: list[Evidence], quality: InputQuality,
           checks: list[Check]) -> Verdict:
    debunks = [e for e in evidence if e.supports == "debunk"]
    if debunks:
        best = max(e.relevance or 0 for e in debunks)
        conf = min(0.95, 0.55 + 0.3 * best + 0.05 * (len(debunks) - 1))
        names = ", ".join(sorted({e.publisher or e.source for e in debunks}))
        return Verdict(DEBUNKED, round(conf, 2), [
            f"{len(debunks)} fact-check(s) rated a matching claim as false or misleading ({names})."])

    earlier = [e for e in evidence if e.supports == "earlier_footage"]
    if earlier:
        best = max(earlier, key=_match_score)
        score = _match_score(best)
        strong = [e for e in earlier if (e.similarity or 0) >= settings.strong_similarity
                  or (e.clip_similarity or 0) >= settings.clip_strong]
        when = f"published {best.date}" if best.date else "seen earlier"
        undated = [] if claim.claimed_date or claim.recency != "none" else [
            "The reel does not say when this happened, so the footage being old may not contradict it."]
        if strong:
            conf = 0.6 + (min(score, 1.0) - settings.strong_similarity) * 3 + 0.08 * (len(strong) - 1)
            return Verdict(LIKELY_OLD_FOOTAGE, round(min(0.95, conf), 2), [
                f"Footage {score:.0%} similar to the reel was {when} ({best.source}), "
                f"before the date the reel claims.",
                f"{len(strong)} independent earlier source(s) match strongly.", *undated])
        conf = 0.35 + (score - settings.weak_similarity) * 1.5
        return Verdict(LIKELY_OLD_FOOTAGE, round(min(0.5, conf), 2), [
            f"Similar footage ({score:.0%}) was {when} ({best.source}); the match is not exact, "
            "so this needs a manual look.", *undated])

    problems = quality.problems(settings)
    if not claim.has_content and not quality.has_speech and not quality.has_text:
        problems.append("no caption, speech or on-screen text to tell what the reel claims")
    if problems:
        return Verdict(UNVERIFIED, 0.0, [f"Not enough to judge: {'; '.join(problems)}."])

    ran = [c for c in checks if c.name in EVIDENCE_CHECKS and c.status == "ok"]
    external = [c for c in ran if c.name != "own_index"]
    if not external:
        not_run = [f"{c.name} ({c.detail})" for c in checks if c.name in EVIDENCE_CHECKS and c.status != "ok"]
        return Verdict(UNVERIFIED, 0.0, [
            "No external evidence search could run: " + "; ".join(not_run) + ".",
            "Use the manual-check links below."])

    coverage = len(ran) / len(EVIDENCE_CHECKS)
    return Verdict(NO_CONTRADICTION_FOUND, round(0.2 + 0.4 * coverage, 2), [
        "No earlier copy of this footage and no fact-check of this claim was found in: "
        + ", ".join(c.name for c in ran) + ".",
        "This is not proof the reel is genuine; it may simply not be indexed yet."])
