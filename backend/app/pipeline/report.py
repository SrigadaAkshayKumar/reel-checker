"""Report: plain-language summary (Gemini, grounded only in the retrieved
evidence, with a template fallback), manual-check links, side-by-side frame
comparisons, and JSON / Markdown / console renderings."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote, quote_plus

from PIL import Image, ImageDraw

from ..core.http import HttpError
from . import fingerprint as fp
from .context import Context
from .llm import LLMError
from .models import VERDICT_LABELS, Claim, Evidence, Keyframe
from .verdict import Verdict

DISCLAIMER = ("Automated check: it reports evidence it found and can be wrong. It never proves a reel "
              "is real, and it says nothing about the people who shared it.")

SUMMARY_PROMPT = """Write the summary for an automated fact-check report on a social-media reel.

Verdict (decided by fixed rules, do not change it): {verdict}
Why: {reasons}
What the reel claims: {claim}
Evidence found (the ONLY facts you may use):
{evidence}

Rules:
- 4-6 short plain-language lines for an ordinary phone user.
- Use only the evidence above. Never invent sources, dates, places or numbers.
- Be honest about uncertainty. "No contradiction found" is not proof the reel is real.
- Talk about the footage and the claim, never accuse a person or account of lying.
- summary: in English.
- summary_local: the same in the language with code "{lang}"; empty if that is English or unknown."""

SUMMARY_SCHEMA = {
    "type": "OBJECT",
    "properties": {"summary": {"type": "STRING"}, "summary_local": {"type": "STRING"}},
    "required": ["summary"],
}


def _evidence_lines(evidence: list[Evidence]) -> str:
    if not evidence:
        return "(none)"
    rows = []
    for e in evidence[:10]:
        bits = [e.source, e.title, e.url]
        if e.publisher:
            bits.append(f"by {e.publisher}")
        if e.date:
            bits.append(f"dated {e.date}")
        if e.rating:
            bits.append(f"rating: {e.rating}")
        if e.similarity is not None:
            bits.append(f"frame similarity {e.similarity:.0%}")
        bits.append(f"role: {e.supports}")
        rows.append("- " + " | ".join(bits))
    return "\n".join(rows)


def template_summary(verdict: Verdict, claim: Claim, evidence: list[Evidence]) -> str:
    """Used without Gemini. The verdict and claim are shown next to it everywhere, so not repeated."""
    lines = list(verdict.reasons)
    top = [e for e in evidence if e.supports in ("debunk", "earlier_footage")][:2]
    for e in top:
        lines.append(f"See: {e.title} ({e.url})")
    return "\n".join(lines)


def summarize(ctx: Context, verdict: Verdict, claim: Claim, evidence: list[Evidence]) -> tuple[str, str, str]:
    """Returns (summary, summary in the reel's language, engine)."""
    fallback = template_summary(verdict, claim, evidence)
    if not (ctx.settings.llm_summary and ctx.llm.available):
        return fallback, "", "template"
    prompt = SUMMARY_PROMPT.format(
        verdict=VERDICT_LABELS[verdict.verdict], reasons=" ".join(verdict.reasons),
        claim=claim.claim_text or "(unclear)", evidence=_evidence_lines(evidence),
        lang=claim.language or "unknown")
    try:
        data = ctx.llm.generate_json([prompt], SUMMARY_SCHEMA, temperature=0.2)
    except LLMError:
        return fallback, "", "template"
    summary = str(data.get("summary", "")).strip()
    local = str(data.get("summary_local", "")).strip()
    return (summary or fallback), local, "gemini" if summary else "template"


def manual_links(claim: Claim) -> list[dict]:
    q = claim.search_queries[0] if claim.search_queries else (claim.claim_text or "")
    fc = claim.factcheck_queries[0] if claim.factcheck_queries else q
    links = [
        {"name": "Google Lens", "url": "https://lens.google.com/", "how": "Upload one of the saved keyframes"},
        {"name": "Yandex Images", "url": "https://yandex.com/images/search?rpt=imageview",
         "how": "Upload a keyframe; Yandex is often best for finding older copies"},
        {"name": "TinEye", "url": "https://tineye.com/", "how": "Upload a keyframe and sort by oldest"},
    ]
    if fc:
        links.append({"name": "Google Fact Check Explorer",
                      "url": f"https://toolbox.google.com/factcheck/explorer/search/{quote(fc)};hl=en",
                      "how": "Existing fact-checks of the claim"})
    if q:
        links.append({"name": "YouTube search", "url": f"https://www.youtube.com/results?search_query={quote_plus(q)}",
                      "how": "Look for older uploads of the same scene"})
    return links


def side_by_side(reel_frame: str, other: bytes, label_left: str, label_right: str, out: Path) -> Path:
    # Trim letterbox bars so the two pieces of footage sit at the same size.
    left = fp.content_box(Image.open(reel_frame).convert("RGB"))
    right = fp.content_box(fp.open_image(other))
    h = 360
    left = left.resize((max(1, int(left.width * h / left.height)), h))
    right = right.resize((max(1, int(right.width * h / right.height)), h))
    canvas = Image.new("RGB", (left.width + right.width + 12, h + 28), (255, 255, 255))
    canvas.paste(left, (0, 28))
    canvas.paste(right, (left.width + 12, 28))
    draw = ImageDraw.Draw(canvas)
    draw.text((6, 8), label_left, fill=(20, 20, 20))
    draw.text((left.width + 18, 8), label_right, fill=(20, 20, 20))
    canvas.save(out, "JPEG", quality=85)
    return out


def save_visuals(ctx: Context, out_dir: Path, frames: list[Keyframe], picked: list[Keyframe],
                 evidence: list[Evidence]) -> tuple[list[str], list[dict]]:
    """Copy the frames used for manual checks and build comparison images for
    the frame matches. Returns (keyframe files, comparisons)."""
    frame_dir = out_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    by_index = {k.index: k for k in frames}
    saved = []
    for k in picked:
        dst = frame_dir / f"keyframe_{k.index:02d}_{k.time:.1f}s.jpg"
        dst.write_bytes(Path(k.path).read_bytes())
        saved.append(str(dst.relative_to(out_dir)))
    comparisons = []
    matches = [e for e in evidence if e.thumbnail_url and e.matched_frame is not None
               and (e.similarity or 0) >= ctx.settings.weak_similarity][:3]
    for i, e in enumerate(matches):
        try:
            img = ctx.http.get_bytes(e.thumbnail_url)
        except HttpError:
            continue
        reel = by_index.get(e.matched_frame)
        if not reel:
            continue
        dst = out_dir / f"compare_{i + 1}.jpg"
        try:
            side_by_side(reel.path, img, f"Reel @ {reel.time:.1f}s", f"{e.source} {e.date or ''}", dst)
        except OSError:
            continue
        comparisons.append({"image": dst.name, "evidence_url": e.url, "similarity": e.similarity})
    return saved, comparisons


# --- renderings --------------------------------------------------------------

def to_markdown(report: dict) -> str:
    v = report["verdict"]
    lines = [f"# Reel check: {VERDICT_LABELS[v]}", "",
             f"**Confidence:** {report['confidence']:.0%}  ",
             f"**Checked:** {report['created_at']}  ",
             f"**Partial report:** {'yes, some checks could not run' if report['partial'] else 'no'}", "",
             "## Summary", "", report["summary"], ""]
    if report.get("summary_local"):
        lines += [report["summary_local"], ""]
    c = report["claim"]
    lines += ["## What the reel claims", "",
              f"- **Claim:** {c.get('claim_text') or '(unclear)'}",
              f"- **Event:** {c.get('event') or '-'}",
              f"- **Place:** {c.get('location') or '-'}",
              f"- **Claimed date:** {c.get('claimed_date') or '-'} ({c.get('recency')})",
              f"- **Language:** {c.get('language') or '-'}", ""]
    lines += ["## Evidence", ""]
    if report["evidence"]:
        lines += ["| Source | Item | Date | Similarity | Role |", "|---|---|---|---|---|"]
        for e in report["evidence"]:
            title = (e.get("title") or e.get("url") or e["source"]).replace("|", "/")[:90]
            item = f"[{title}]({e['url']})" if e.get("url") else title
            sim = f"{e['similarity']:.0%}" if e.get("similarity") is not None else (e.get("rating") or "-")
            who = f"{e['source']}" + (f" ({e['publisher']})" if e.get("publisher") else "")
            lines.append(f"| {who} | {item} | {e.get('date') or '-'} | {sim} | {e['supports']} |")
    else:
        lines.append("Nothing found.")
    lines.append("")
    if report.get("comparisons"):
        lines += ["## Side by side", ""]
        lines += [f"![{c['evidence_url']}]({c['image']})" for c in report["comparisons"]]
        lines.append("")
    lines += ["## Checks", ""]
    lines += [f"- **{c['name']}**: {c['status']} {('- ' + c['detail']) if c['detail'] else ''}"
              for c in report["checks"]]
    lines += ["", "## Check it yourself", ""]
    lines += [f"- [{m['name']}]({m['url']}): {m['how']}" for m in report["manual_links"]]
    if report.get("keyframes"):
        lines += ["", "Keyframes saved for upload: " + ", ".join(f"`{k}`" for k in report["keyframes"])]
    lines += ["", f"_{report['disclaimer']}_", ""]
    return "\n".join(lines)


def to_console(report: dict) -> str:
    v = report["verdict"]
    bar = "=" * 64
    out = [bar, f" VERDICT: {VERDICT_LABELS[v].upper()}   (confidence {report['confidence']:.0%})"
           + ("   [partial]" if report["partial"] else ""), bar, "", report["summary"], ""]
    c = report["claim"]
    out += [f"Claim:  {c.get('claim_text') or '(unclear)'}",
            f"Date:   {c.get('claimed_date') or '-'} ({c.get('recency')})   Lang: {c.get('language') or '-'}", ""]
    if report["evidence"]:
        out.append("Evidence:")
        for e in report["evidence"][:8]:
            sim = f" sim {e['similarity']:.0%}" if e.get("similarity") is not None else ""
            rating = f" [{e['rating']}]" if e.get("rating") else ""
            out.append(f"  - {e['source']:<10} {e.get('date') or '----------'}{sim}{rating} "
                       f"{(e.get('title') or '')[:60]}")
            if e.get("url"):
                out.append(f"    {e['url']}")
        out.append("")
    out.append("Checks: " + ", ".join(f"{c['name']}={c['status']}" for c in report["checks"]))
    return "\n".join(out)


def write(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    j = out_dir / "report.json"
    m = out_dir / "report.md"
    j.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    m.write_text(to_markdown(report), encoding="utf-8")
    return j, m
