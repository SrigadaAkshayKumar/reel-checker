"""Server-rendered pages: the public share page /r/{id} (with Open Graph tags
so WhatsApp / X show a preview card) and a minimal upload page at / for use
until the Next.js frontend (Phase 5) exists. Mobile-first, no JS framework."""
from __future__ import annotations

from html import escape
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from ..core.config import Settings
from ..db.store import Store
from ..pipeline.models import VERDICT_LABELS
from . import views
from .deps import check_id, get_settings, get_store

router = APIRouter()

SOURCE_LABELS = {"fact_check": "Fact-check", "youtube": "YouTube", "own_index": "Known footage",
                 "vision_web": "Web image match"}  # same wording as the frontend (lib/present.ts)

# Neutral blue, never green, for "no contradiction": it is not a "real" stamp.
VERDICT_TONE = {"DEBUNKED": "bad", "LIKELY_OLD_FOOTAGE": "warn", "NO_CONTRADICTION_FOUND": "info",
                "UNVERIFIED": "muted"}

CSS = """
:root{color-scheme:light dark;--bg:#f6f7f9;--card:#fff;--text:#16181d;--sub:#5b6270;--line:#e3e6eb;
--link:#1f5fbf;--on-link:#fff;
--bad:#b42318;--bad-bg:#fdecea;--warn:#a15c00;--warn-bg:#fff4e0;--info:#1f5fbf;--info-bg:#e8f0fc;
--muted:#4b5563;--muted-bg:#eef0f3}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--text:#e8eaee;--sub:#9aa3b2;
--line:#2a2f3a;--link:#7fb0ff;--on-link:#0f1115;--bad:#ff8a80;--bad-bg:#3a1714;--warn:#ffc266;--warn-bg:#3a2a10;
--info:#8fb8ff;--info-bg:#15243d;--muted:#c3c9d4;--muted-bg:#232833}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans","Noto Sans Telugu",
"Noto Sans Devanagari",sans-serif}
main{max-width:720px;margin:0 auto;padding:16px}a{color:var(--link)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:12px 0}
.badge{display:inline-block;font-weight:700;font-size:20px;padding:6px 12px;border-radius:8px}
.bad{color:var(--bad);background:var(--bad-bg)}.warn{color:var(--warn);background:var(--warn-bg)}
.info{color:var(--info);background:var(--info-bg)}.muted{color:var(--muted);background:var(--muted-bg)}
.sub{color:var(--sub);font-size:14px}h1{font-size:18px;margin:0 0 8px}h2{font-size:16px;margin:0 0 8px}
.ev{border-top:1px solid var(--line);padding:10px 0}.ev:first-of-type{border-top:0}
.ev a{word-break:break-word}.tag{font-size:12px;padding:2px 6px;border-radius:6px;margin-left:6px}
img{max-width:100%;height:auto;border-radius:8px;display:block;margin:8px 0}
.row{display:flex;gap:8px;flex-wrap:wrap}button,.btn{font:inherit;padding:10px 14px;border-radius:8px;
border:1px solid var(--line);background:var(--card);color:var(--text);text-decoration:none;cursor:pointer}
.primary{background:var(--link);color:var(--on-link);border-color:var(--link);font-weight:600}
input,textarea{font:inherit;width:100%;padding:10px;border-radius:8px;border:1px solid var(--line);
background:var(--card);color:var(--text)}label{display:block;margin:12px 0 4px;font-weight:600}
ul{padding-left:20px}pre{white-space:pre-wrap}
"""


def _page(title: str, body: str, head: str = "") -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>
{head}<style>{CSS}</style></head><body><main>{body}</main></body></html>""")


def _evidence_html(e: dict, match_threshold: float) -> str:
    role = {"debunk": ("Fact-check", "bad"), "earlier_footage": ("Earlier footage", "warn")}.get(
        e.get("supports"), ("Lead", "muted"))
    bits = []
    if e.get("publisher"):
        bits.append(escape(e["publisher"]))
    if e.get("date"):
        bits.append(escape(e["date"]))
    if e.get("similarity") is not None:
        # Unrelated footage scores ~50-65%; a bare "72% similar" reads like a partial match.
        sim = e["similarity"]
        bits.append(f"{sim:.0%} frame match" if sim >= match_threshold else "frames do not match")
    if e.get("rating"):
        bits.append("rated “" + escape(e["rating"]) + "”")
    title = escape(e.get("title") or e.get("url") or SOURCE_LABELS.get(e["source"], e["source"]))
    link = (f'<a href="{escape(e["url"])}" rel="nofollow noopener" target="_blank">{title}</a>'
            if e.get("url") else f"<strong>{title}</strong>")
    return (f'<div class="ev">{link}<span class="tag {role[1]}">{role[0]}</span>'
            f'<div class="sub">{escape(SOURCE_LABELS.get(e["source"], e["source"]))} · {" · ".join(bits)}</div></div>')


@router.get("/r/{report_id}", response_class=HTMLResponse)
def share_page(report_id: str, settings: Settings = Depends(get_settings), store: Store = Depends(get_store)):
    stored = store.report_by_id(check_id(report_id))
    if not stored:
        raise HTTPException(404, "report not found")
    r = views.public_report(stored, settings.public_base_url)
    label = VERDICT_LABELS[r["verdict"]]
    tone = VERDICT_TONE[r["verdict"]]
    claim = r["claim"].get("claim_text") or "(the claim could not be read)"
    first_line = (r["summary"].splitlines() or [label])[0]
    base = settings.public_base_url.rstrip("/")
    og_image = (f'<meta property="og:image" content="{escape(base + r["comparisons"][0]["image_url"])}">'
                if base and r["comparisons"] else "")
    head = (f'<meta property="og:title" content="Reel check: {escape(label)}">'
            f'<meta property="og:description" content="{escape(first_line[:200])}">'
            f'<meta property="og:type" content="article">{og_image}'
            f'<meta name="description" content="{escape(first_line[:200])}">')
    share_text = quote(f"Reel check: {label}. {claim[:120]} {r['share_url']}")

    parts = [f'<div class="card"><span class="badge {tone}">{escape(label)}</span>'
             f'<div class="sub" style="margin-top:8px">Confidence {r["confidence"]:.0%} · checked '
             f'{escape(r["created_at"][:10])}{" · partial report" if r["partial"] else ""}</div>'
             f'<p><strong>The reel claims:</strong> {escape(claim)}</p>'
             f'<pre style="font:inherit;margin:0">{escape(r["summary"])}</pre>'
             + (f'<pre style="font:inherit">{escape(r["summary_local"])}</pre>' if r.get("summary_local") else "")
             + "</div>"]
    if r["comparisons"]:
        imgs = "".join(f'<img src="{escape(c["image_url"])}" alt="Reel frame next to earlier footage" '
                       f'loading="lazy"><div class="sub">Left: the reel. Right: '
                       f'<a href="{escape(c["evidence_url"])}" rel="nofollow noopener">earlier copy</a></div>'
                       for c in r["comparisons"])
        parts.append(f'<div class="card"><h2>Side by side</h2>{imgs}</div>')
    ev = "".join(_evidence_html(e, settings.weak_similarity) for e in r["evidence"][:10])
    parts.append(f'<div class="card"><h2>Evidence</h2>{ev or "<p class=sub>Nothing found.</p>"}</div>')
    links = "".join(f'<li><a href="{escape(m["url"])}" rel="nofollow noopener" target="_blank">'
                    f'{escape(m["name"])}</a> <span class="sub">{escape(m["how"])}</span></li>'
                    for m in r["manual_links"])
    parts.append(f'<div class="card"><h2>Check it yourself</h2><ul>{links}</ul></div>')
    parts.append(f"""<div class="card"><h2>Share</h2><div class="row">
<a class="btn primary" href="https://wa.me/?text={share_text}" target="_blank" rel="noopener">WhatsApp</a>
<button onclick="navigator.clipboard.writeText(location.href).then(()=>this.textContent='Copied')">Copy link</button>
</div></div>
<div class="card"><h2>Was this correct?</h2><div class="row">
<button onclick="fb(true)">Yes</button><button onclick="fb(false)">No, report an error</button></div>
<div id="fb-note" style="display:none"><label for="note">What is wrong? (optional)</label>
<textarea id="note" rows="3" maxlength="1000"></textarea>
<div class="row" style="margin-top:8px"><button class="primary" onclick="send(false)">Send</button></div></div>
<p id="fb-done" class="sub" style="display:none">Thanks, this helps us improve.</p></div>
<p class="sub">{escape(r["disclaimer"])}</p>
<script>
function fb(ok){{if(ok)send(true);else document.getElementById('fb-note').style.display='block'}}
function send(ok){{fetch('/api/reports/{report_id}/feedback',{{method:'POST',
headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{correct:ok,note:ok?'':document.getElementById('note').value}})}}).finally(()=>{{
document.getElementById('fb-note').style.display='none';document.getElementById('fb-done').style.display='block'}})}}
</script>""")
    return _page(f"Reel check: {label}", "".join(parts), head)


@router.get("/", response_class=HTMLResponse)
def upload_page():
    return _page("Reel Fact-Checker", """
<h1>Is this reel old footage?</h1>
<p class="sub">Upload the reel (or a screen recording of it). We look for earlier copies and existing
fact-checks. The video is deleted after the check.</p>
<form id="f" class="card">
<label for="file">Video (up to 90 s)</label><input id="file" name="file" type="file" accept="video/*" required>
<label for="caption">Caption (optional)</label>
<textarea id="caption" name="caption" rows="2" placeholder="Paste the post's caption if you have it"></textarea>
<label for="posted">Date it was posted (optional)</label><input id="posted" name="posted_date" type="date">
<div class="row" style="margin-top:12px"><button class="primary" type="submit">Check this reel</button></div>
</form>
<div id="status" class="card" style="display:none"></div>
<script>
const names={queued:'Waiting in line',starting:'Starting',extracting:'Extracting frames and audio',
transcribing:'Listening and reading text',understanding:'Working out what the reel claims',
searching:'Searching for earlier copies and fact-checks',comparing:'Comparing evidence',done:'Done'};
const box=document.getElementById('status');
function show(t){box.style.display='block';box.textContent=t}
document.getElementById('f').onsubmit=async e=>{e.preventDefault();show('Uploading…');
const fd=new FormData(e.target);if(!fd.get('posted_date'))fd.delete('posted_date');
const res=await fetch('/api/analyze',{method:'POST',body:fd});const j=await res.json();
if(!res.ok){show((j.detail&&j.detail.message)||'Upload failed');return}poll(j)};
async function poll(j){while(j.status==='queued'||j.status==='running'){
show(j.status==='queued'&&j.queue_position?`Waiting in line (#${j.queue_position})`:(names[j.step]||'Working')+'…');
await new Promise(r=>setTimeout(r,1500));j=await (await fetch('/api/jobs/'+j.job_id)).json()}
if(j.status==='done')location.href=j.share_url;else show(j.error||'The check failed')}
</script>""")
