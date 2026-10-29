# Reel Fact-Checker: web app

Next.js 16 (App Router, Cache Components) frontend for the FastAPI backend in `../backend`.

| Route | What |
|---|---|
| `/` | Pitch, upload box (checks type, size and duration in the browser), how it works, what verdicts mean |
| `/check/[jobId]` | Live progress: queue position, then each pipeline step; opens the report by itself |
| `/r/[id]` | The report: verdict, claim, summary, side-by-side frames, evidence, reverse-image-search links, share, feedback. Server-rendered and cached; Open Graph tags for WhatsApp / Telegram previews |
| `/privacy` | Privacy & terms in plain language |

The browser uploads straight to the backend (CORS), so 50 MB videos never pass through the Next.js server
(Vercel caps request bodies far below that).

## Run locally

```bash
# terminal 1: backend
cd backend && CORS_ORIGINS=http://localhost:3000 PUBLIC_BASE_URL=http://localhost:3000 uvicorn app.main:app --port 8000

# terminal 2: frontend
cd frontend && npm install && npm run dev      # http://localhost:3000
```

## Environment

| Variable | Default | |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend URL as the browser sees it. **Baked in at build time.** |
| `NEXT_PUBLIC_SITE_URL` | `http://localhost:3000` | This site's public URL: share links and preview metadata |
| `API_URL` | `NEXT_PUBLIC_API_URL` | Optional server-side backend URL (e.g. an internal address) |
| `NEXT_PUBLIC_MAX_UPLOAD_MB` / `NEXT_PUBLIC_MAX_VIDEO_SECONDS` | 50 / 90 | Keep equal to the backend's limits |

On the backend set `CORS_ORIGINS` to this site's URL and `PUBLIC_BASE_URL` to the same, so its share links point here.
The "Open in Google Lens / Yandex / TinEye" buttons appear when the backend is publicly reachable; on localhost
the report offers frame downloads instead.

## Deploy

Either the `web` service in `../compose.yaml` (standalone server, `Dockerfile` here) or Vercel with Root
Directory `frontend`: see [`../docs/deploy.md`](../docs/deploy.md).

## Checks

```bash
npm run lint && npm run typecheck && npm test && npm run build
npm run e2e:build && E2E_PYTHON=../.venv/bin/python npm run e2e   # Playwright: real backend, external APIs faked
```

`AGENTS.md` is written by Next.js; it points coding agents at the bundled docs in `node_modules/next/dist/docs/`.
