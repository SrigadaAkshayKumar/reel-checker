# Deploying Reel Fact-Checker (Phase 8)

One free VM runs everything behind HTTPS: Caddy (automatic Let's Encrypt certificates), the API, a separate
analysis worker, and (optionally) the website. Alternatively the website goes on Vercel and the VM runs only
the API.

```
              https://APP_DOMAIN                  https://API_DOMAIN
   phone ───►  website (Next.js) ───────────────►  API (FastAPI) ──► worker ──► Gemini / Fact Check / YouTube
               on this VM (web) or Vercel           │
                                                    └── SQLite + report images (Docker volume, nightly backup)
```

Everything is configured by one file, `.env`, from `.env.example`. Total cost: nothing, except an optional
domain name.

## 1. Choose names

You need two hostnames pointing at the VM: one for the API, one for the site.

- **Your own domain** (a `.in` or `.com` costs a few hundred rupees a year): `reelcheck.in` and
  `api.reelcheck.in`.
- **Free: [DuckDNS](https://www.duckdns.org)**: register `myreels.duckdns.org`. Sub-names resolve too, so use
  `myreels.duckdns.org` and `api.myreels.duckdns.org`.

If the site goes on Vercel, only the API name points at the VM. The site's name is its Vercel address
(`yourproject.vercel.app` or a custom one).

## 2. Create the VM (Oracle Cloud Always Free)

1. Sign up at [cloud.oracle.com](https://cloud.oracle.com). A card is required for verification, but Always
   Free resources are not charged. Check Oracle's current Always Free limits when you sign up, as they change.
2. **Compute → Instances → Create instance**:
   - Image: **Ubuntu 24.04** (or 22.04)
   - Shape: **Ampere (VM.Standard.A1.Flex)**, 2 OCPU and 12 GB RAM. ARM is fine: every image here is
     multi-architecture. If Oracle says "out of capacity", try another availability domain or retry later.
   - Add your SSH public key, and keep the public IP.
3. **Open the ports**. Instance → Subnet → Security list → *Add ingress rules*:
   - source `0.0.0.0/0`, TCP, destination port **80**
   - the same for TCP **443**
   - the same for UDP **443** (HTTP/3, optional)
4. **DNS**: create `A` records for both hostnames pointing to the VM's public IP. With DuckDNS, set the IP on
   its page.

> Oracle may reclaim *idle* Always Free instances (very low CPU, network and memory over 7 days). A
> lightly used checker can look idle. Upgrading the account to Pay As You Go keeps Always Free resources free
> and exempts them from reclamation. Check Oracle's current policy.

## 3. Set up the VM

```bash
ssh ubuntu@<VM IP>
curl -fsSL https://raw.githubusercontent.com/SrigadaAkshayKumar/reel-checker/main/deploy/setup-vm.sh -o setup-vm.sh
less setup-vm.sh                 # read it first
sudo bash setup-vm.sh
exit                             # log in again so the docker group applies
```

The script installs Docker and automatic security updates. It opens 80/443 in the VM's own firewall:
Oracle's Ubuntu images reject them even after the security list allows them, which is the classic
"site unreachable" trap. It adds swap on small VMs, clones this repo to `~/reel-checker`, creates `.env`
(mode 600), and schedules a nightly backup.

## 4. Configure

```bash
ssh ubuntu@<VM IP>
cd ~/reel-checker && nano .env
```

| Setting | Website on this VM | Website on Vercel |
|---|---|---|
| `API_DOMAIN` | `api.reelcheck.in` | `api.reelcheck.in` |
| `APP_DOMAIN` | `reelcheck.in` | `yourproject.vercel.app` |
| `ACME_EMAIL` | your email (certificate notices) | same |
| `CADDY_SITES` | `all` | `api` |
| `COMPOSE_PROFILES` | `web` | *(empty)* |
| `GEMINI_API_KEY`, `GOOGLE_API_KEY` | your keys | your keys |

Thresholds (`STRONG_SIMILARITY` and so on) go here too, from your `run.py eval` results. `PUBLIC_BASE_URL`,
`CORS_ORIGINS`, `TRUST_PROXY` and the worker mode are derived from these by `compose.yaml`.

## 5. Start

```bash
docker compose up -d --build     # first build: a few minutes
docker compose ps                # api healthy, worker and caddy up (and web, if used)
deploy/smoke-test.sh api.reelcheck.in reelcheck.in
```

The smoke test checks HTTPS, the security and CORS headers, and one real analysis through the worker
(this counts as one check of the daily allowance and may use one Gemini call). It also checks that the upload
was deleted, the share page and its preview tags, a backup, a restart, and that no IP addresses appear in
logs. Open `https://APP_DOMAIN` on your phone and check a reel.

## 6. Website on Vercel instead (optional)

1. [vercel.com](https://vercel.com) → *Add New → Project* → import this GitHub repo.
2. **Root Directory: `frontend`**. The framework is detected as Next.js.
3. Environment variables (Production):
   - `NEXT_PUBLIC_API_URL` = `https://api.reelcheck.in`
   - `NEXT_PUBLIC_SITE_URL` = `https://yourproject.vercel.app` (or your custom domain)
4. Deploy. On the VM, set `APP_DOMAIN` to that same Vercel address, `CADDY_SITES=api`, and leave
   `COMPOSE_PROFILES` empty. Then run `docker compose up -d` (this updates CORS and share links).

Vercel's free Hobby plan is for non-commercial use. A paid service later means Vercel Pro, or running the
site on the VM (above), which costs nothing.

## 7. Monitoring

- **Uptime**: [UptimeRobot](https://uptimerobot.com) free plan, two HTTP(S) monitors every 5 minutes:
  - `https://API_DOMAIN/api/health`, keyword `"ok":true`
  - `https://APP_DOMAIN/`

  Add your email or Telegram as the alert contact.
- **Logs**: `docker compose logs -f api worker` (errors, crashed jobs, stale-job recovery), and
  `docker compose logs caddy` (certificate problems). Logs rotate at 5 × 10 MB per service. Nothing logs
  requests or IP addresses, by design.
- **Quota**: `docker compose exec api python run.py quota` shows today's free-tier usage.
- **Quality**: `docker compose exec api python run.py review` lists flagged reports and reports users marked
  wrong (the first-month review from the plan).

## 8. Backups

`setup-vm.sh` adds a 03:30 cron job that runs `python run.py backup --keep 14` inside the api container. It
writes a consistent snapshot of the database and the report images to the Docker volume. Uploads are never
kept. **Copy them off the VM**; a backup on the same disk doesn't survive losing the VM. For example, from
your computer:

```bash
ssh ubuntu@<VM IP> 'cd reel-checker && docker compose cp api:/var/lib/reel-checker/backups ./backups'
scp -r ubuntu@<VM IP>:reel-checker/backups ./reel-checker-backups
```

Or schedule [rclone](https://rclone.org) on the VM to Google Drive or Oracle Object Storage (free tier).

**Restore** (it keeps the current report images beside the restored ones):

```bash
docker compose cp ./reel-checker-YYYYmmdd-HHMMSS.tar.gz api:/var/lib/reel-checker/restore.tar.gz   # if copied off
docker compose stop api worker
docker compose run --rm --no-deps api python run.py restore /var/lib/reel-checker/restore.tar.gz --yes
docker compose up -d
```

## 9. Updating

- **From GitHub**: *Actions → deploy → Run workflow*. It pulls `main` on the VM, rebuilds, restarts and runs
  the smoke test. One-time setup, under repository *Settings → Secrets and variables → Actions*:
  - `DEPLOY_HOST`: VM IP
  - `DEPLOY_USER`: `ubuntu`
  - `DEPLOY_SSH_KEY`: a private key you created for deploys; put its public half in the VM's
    `~/.ssh/authorized_keys`
  - `DEPLOY_KNOWN_HOSTS`: output of `ssh-keyscan -t ed25519 <VM IP>`
- **By hand**: `cd ~/reel-checker && git pull && docker compose up -d --build`.

Schema changes migrate themselves on start. Back up first anyway.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Browser can't connect at all | Security list (step 2.3) or VM firewall: rerun `setup-vm.sh` |
| Certificate errors / Caddy logs `challenge failed` | DNS not pointing at the VM yet, or port 80 closed: Let's Encrypt validates over port 80 |
| Site loads, uploads fail with a CORS error | `APP_DOMAIN` doesn't match the site's real address; fix `.env`, `docker compose up -d` |
| Every report says "searches could not run" | API keys missing in `.env`, or quota used up: `run.py quota` |
| `api` unhealthy | `docker compose logs api`: often a typo in `.env` |
| Upload refused: "Daily limit" | `RATE_LIMIT_PER_DAY` (default 10 per person per day) |

## Local rehearsal

The same stack runs on any machine with Docker, using `*.localhost` names and Caddy's own local CA:

```bash
printf 'APP_DOMAIN=app.localhost\nAPI_DOMAIN=api.localhost\nACME_EMAIL=me@example.org\nCADDY_GLOBAL=local_certs\nCADDY_SITES=all\nCOMPOSE_PROFILES=web\n' > .env
docker compose up -d --build && deploy/smoke-test.sh
```

CI runs exactly this on every push (the `docker` job).
