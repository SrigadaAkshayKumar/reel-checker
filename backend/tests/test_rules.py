"""Verdict rules, fact-check rating parsing and claim parsing, without media."""
from app.pipeline.evidence.factcheck_api import rating_is_false
from app.pipeline.models import DEBUNKED, LIKELY_OLD_FOOTAGE, NO_CONTRADICTION_FOUND, UNVERIFIED, Check, Claim, Evidence
from app.pipeline.text import has_recency_marker, overlap, terms, tokens
from app.pipeline.verdict import InputQuality, decide

GOOD = InputQuality(duration=20, total_frames=8, usable_frames=8, has_speech=True, has_text=True)
CLAIM = Claim(claim_text="Plane crash at Hyderabad today", keywords=["plane crash", "hyderabad"])
RAN = [Check("own_index", "ok"), Check("fact_check", "ok"), Check("youtube", "ok"), Check("vision_web", "ok")]


def test_debunk_wins(settings):
    ev = [Evidence("fact_check", "Old video", "u1", supports="debunk", relevance=0.8, publisher="BOOM"),
          Evidence("youtube", "x", "u2", similarity=0.97, supports="earlier_footage")]
    v = decide(settings, CLAIM, ev, GOOD, RAN)
    assert v.verdict == DEBUNKED and 0.7 < v.confidence <= 0.95


def test_strong_earlier_match(settings):
    ev = [Evidence("youtube", "x", "u", date="2015-01-01", similarity=0.97, supports="earlier_footage")]
    v = decide(settings, CLAIM, ev, GOOD, RAN)
    assert v.verdict == LIKELY_OLD_FOOTAGE and v.confidence >= 0.75


def test_weak_earlier_match_is_low_confidence(settings):
    ev = [Evidence("youtube", "x", "u", date="2015-01-01", similarity=0.84, supports="earlier_footage")]
    v = decide(settings, CLAIM, ev, GOOD, RAN)
    assert v.verdict == LIKELY_OLD_FOOTAGE and v.confidence <= 0.5


def test_similar_but_later_is_only_a_lead(settings):
    ev = [Evidence("youtube", "x", "u", date="2026-10-25", similarity=0.99, supports="lead")]
    assert decide(settings, CLAIM, ev, GOOD, RAN).verdict == NO_CONTRADICTION_FOUND


def test_poor_input_is_unverified(settings):
    dark = InputQuality(duration=8, total_frames=4, usable_frames=0, has_speech=False, has_text=False)
    assert decide(settings, Claim(), [], dark, RAN).verdict == UNVERIFIED
    short = InputQuality(duration=1.0, total_frames=1, usable_frames=1, has_speech=True, has_text=True)
    assert decide(settings, CLAIM, [], short, RAN).verdict == UNVERIFIED


def test_no_external_checks_is_unverified_not_clean(settings):
    checks = [Check("own_index", "ok"), Check("fact_check", "quota", "used up"),
              Check("youtube", "skipped", "no key"), Check("vision_web", "skipped", "no key")]
    v = decide(settings, CLAIM, [], GOOD, checks)
    assert v.verdict == UNVERIFIED and v.confidence == 0
    assert "fact_check (used up)" in v.reasons[0]


def test_nothing_found_is_no_contradiction(settings):
    v = decide(settings, CLAIM, [], GOOD, RAN)
    assert v.verdict == NO_CONTRADICTION_FOUND
    assert "not proof" in " ".join(v.reasons)


def test_ratings():
    for r in ["False", "Misleading", "Partly false", "Missing context", "Old video", "FAKE", "फर्जी",
              "भ्रामक", "తప్పు", "Altered", "Untrue"]:
        assert rating_is_false(r), r
    for r in ["True", "Correct", "Mostly true", "Accurate"]:
        assert not rating_is_false(r), r


def test_indic_tokens_keep_vowel_signs():
    assert "హైదరాబాద్" in tokens("ఈరోజు హైదరాబాద్ లో విమాన ప్రమాదం")
    assert "हैदराबाद" in tokens("आज हैदराबाद में विमान हादसा!")
    assert has_recency_marker("ఈరోజు హైదరాబాద్")
    assert has_recency_marker("BREAKING: plane crash")


def test_overlap():
    q = terms("plane crash hyderabad airport")
    assert overlap(q, "Old video of plane crash in Hyderabad shared as recent") >= 0.7
    assert overlap(q, "Cricket match result in Mumbai") == 0.0


def test_undated_claim_notes_that_old_footage_may_not_contradict(settings):
    ev = [Evidence("youtube", "x", "u", date="2015-01-01", similarity=0.97, supports="earlier_footage")]
    v = decide(settings, Claim(claim_text="A plane crash", keywords=["plane"]), ev, GOOD, RAN)
    assert v.verdict == LIKELY_OLD_FOOTAGE and "does not say when" in v.reasons[-1]
    dated = Claim(claim_text="Plane crash today", keywords=["plane"], recency="current", claimed_date="2026-10-25")
    assert "does not say when" not in " ".join(decide(settings, dated, ev, GOOD, RAN).reasons)
