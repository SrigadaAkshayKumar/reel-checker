#!/usr/bin/env bash
# End-to-end check of a running stack, through Caddy and HTTPS.
#   deploy/smoke-test.sh                      local test: api.localhost / app.localhost, Caddy local_certs
#   deploy/smoke-test.sh api.example.org reelcheck.example.org      a real deployment (public certificates)
# Run from the repo root (it calls `docker compose`). Needs curl, python3 and ffmpeg on the host.
# Uploads one synthetic test video: on a real deployment that uses one analysis of the daily allowance.
set -euo pipefail

API=${1:-api.localhost}
APP=${2:-app.localhost}
CURL=(curl -sS --fail-with-body --max-time 60)
if [[ $API == *.localhost ]]; then  # local test: resolve to this machine, accept Caddy's local CA
  CURL+=(-k --resolve "$API:443:127.0.0.1" --resolve "$APP:443:127.0.0.1")
fi
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
pass() { printf '  ok  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*" >&2; exit 1; }
json() { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }

echo "Smoke test: https://$API (API), https://$APP (site)"
for _ in $(seq 1 60); do "${CURL[@]}" -o /dev/null "https://$API/api/health" 2>/dev/null && break; sleep 2; done
health=$("${CURL[@]}" "https://$API/api/health") || fail "API health over HTTPS"
[[ $(echo "$health" | json "['ok']") == True ]] || fail "health: $health"
pass "API healthy over HTTPS: $health"

headers=$("${CURL[@]}" -D - -o /dev/null "https://$API/api/health")
grep -qi '^strict-transport-security:' <<<"$headers" || fail "missing HSTS header"
grep -qi '^server:' <<<"$headers" && fail "Server header should be stripped"
pass "security headers"

cors=$("${CURL[@]}" -D - -o /dev/null -X OPTIONS -H "Origin: https://$APP" -H "Access-Control-Request-Method: POST" \
  "https://$API/api/analyze")
grep -qi "^access-control-allow-origin: https://$APP" <<<"$cors" || fail "CORS does not allow https://$APP"
pass "CORS allows the site"

ffmpeg -v error -f lavfi -i "testsrc2=s=360x640:d=4:r=25" -f lavfi -i "sine=f=440:d=4" -shortest \
  -c:v libx264 -pix_fmt yuv420p -c:a aac "$TMP/smoke.mp4"
job=$("${CURL[@]}" -F "file=@$TMP/smoke.mp4" -F "caption=Smoke test $(date +%s%N)" "https://$API/api/analyze") \
  || fail "upload: $job"
id=$(echo "$job" | json "['job_id']")
pass "uploaded, job $id"

status=""
for _ in $(seq 1 90); do
  status=$("${CURL[@]}" "https://$API/api/jobs/$id" | json "['status']")
  [[ $status == done || $status == failed ]] && break
  sleep 2
done
[[ $status == done ]] || fail "job ended as '$status'"
report=$("${CURL[@]}" "https://$API/api/reports/$id")
verdict=$(echo "$report" | json "['verdict']")
pass "analysed by the worker: $verdict"

left=$(docker compose exec -T api sh -c 'ls -A /var/lib/reel-checker/uploads | wc -l')
[[ $left == 0 ]] || fail "$left upload(s) still on disk"
pass "upload deleted after analysis"

if "${CURL[@]}" -o /dev/null "https://$APP/privacy" 2>/dev/null; then
  page=$("${CURL[@]}" -A "WhatsApp/2.24" "https://$APP/r/$id")
  grep -q "og:title" <<<"$page" || fail "share page has no preview tags"
  pass "site serves the report with preview tags"
else
  echo "  --  site not on this host (Vercel?): skipped"
fi

docker compose exec -T api python run.py backup >/dev/null || fail "backup"
pass "backup written"

docker compose restart api worker >/dev/null
for _ in $(seq 1 60); do "${CURL[@]}" -o /dev/null "https://$API/api/health" 2>/dev/null && break; sleep 2; done
"${CURL[@]}" -o /dev/null "https://$API/api/reports/$id" || fail "report lost after restart"
pass "data survives a restart"

if docker compose logs --no-color 2>&1 | grep -E 'GET /|POST /' | grep -qE '([0-9]{1,3}\.){3}[0-9]{1,3}'; then
  fail "request logs contain IP addresses"
fi
pass "no client IPs in logs"
echo "All good."
