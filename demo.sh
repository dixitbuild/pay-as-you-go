#!/usr/bin/env bash
# Interactive demo. Start the server first:  uv run python manage.py runserver
# Run:  ./demo.sh          (press Enter between steps)
#       NOPAUSE=1 ./demo.sh (no pauses, for a dry run)
set -euo pipefail

B=${B:-http://127.0.0.1:8000}
J='Content-Type: application/json'
SUF=$RANDOM   # unique usernames so the demo can be re-run without resetting the DB

bold=$'\033[1m'; dim=$'\033[2m'; green=$'\033[32m'; reset=$'\033[0m'

pause() { [[ -n "${NOPAUSE:-}" ]] || read -r -p "${dim}[Enter to continue]${reset} " _; }
say()   { echo; echo "${bold}${green}## $*${reset}"; }
jget()  { python3 -c "import sys,json; print(json.load(sys.stdin)['$1'])"; }

# api METHOD PATH [TOKEN] [BODY]  -> prints the command, then pretty JSON
api() {
  local method=$1 path=$2 token=${3:-} body=${4:-}
  local args=(-s -X "$method" "$B$path" -H "$J")
  [[ -n "$token" ]] && args+=(-H "Authorization: Token $token")
  [[ -n "$body" ]] && args+=(-d "$body")
  echo "${dim}\$ $method $path ${body}${reset}" >&2
  curl "${args[@]}" | tee /tmp/demo_last.json | python3 -m json.tool
}

# Simulate time passing by moving started_at back (only affects the dev DB).
rewind() { uv run python manage.py shell --no-imports -c "
from sessions_app.models import Session; from datetime import timedelta
s = Session.objects.get(pk=$1); s.started_at -= timedelta(seconds=$2); s.save()" ; }

recharge() {  # recharge TOKEN AMOUNT  (start + successful callback)
  api POST /wallet/recharge/ "$1" "{\"amount\":\"$2\"}" >/dev/null
  local ref; ref=$(jget reference </tmp/demo_last.json)
  api POST /wallet/recharge/callback/ "" "{\"reference\":\"$ref\",\"status\":\"success\"}" >/dev/null
  echo "$ref"
}

new_session() {  # new_session UTOKEN PTOKEN PID -> session id, left in accepted state
  api POST /sessions/ "$1" >/dev/null; local id; id=$(jget id </tmp/demo_last.json)
  api POST "/sessions/$id/assign/" "$1" "{\"provider_id\":$3}" >/dev/null
  api POST "/sessions/$id/accept/" "$2" >/dev/null
  echo "$id"
}

say "1. Register a user and a provider"
api POST /auth/register/ "" "{\"username\":\"alice$SUF\",\"password\":\"S3cure-pass!\",\"role\":\"USER\"}"
UT=$(jget token </tmp/demo_last.json)
api POST /auth/register/ "" "{\"username\":\"dr_bob$SUF\",\"password\":\"S3cure-pass!\",\"role\":\"PROVIDER\"}"
PT=$(jget token </tmp/demo_last.json); PID=$(jget id </tmp/demo_last.json)
pause

say "2. Recharge Rs 500. Pending first: the wallet is NOT credited yet"
api GET /wallet/ "$UT"
api POST /wallet/recharge/ "$UT" '{"amount":"500.00"}'
REF=$(jget reference </tmp/demo_last.json)
api GET /wallet/ "$UT"
pause

say "3. Gateway callback, sent TWICE (idempotency): balance stays 500"
api POST /wallet/recharge/callback/ "" "{\"reference\":\"$REF\",\"status\":\"success\"}"
api POST /wallet/recharge/callback/ "" "{\"reference\":\"$REF\",\"status\":\"success\"}"
pause

say "4. Session lifecycle: create -> assign -> accept -> start"
api POST /sessions/ "$UT"; SID=$(jget id </tmp/demo_last.json)
api POST "/sessions/$SID/assign/" "$UT" "{\"provider_id\":$PID}"
echo "${dim}(provider tries to start someone else's session -> 403)${reset}"
api POST "/sessions/$SID/start/" "$PT"
api POST "/sessions/$SID/accept/" "$PT"
api POST "/sessions/$SID/start/" "$UT"
pause

say "5. Two minutes pass. Bill twice: only charged once"
rewind "$SID" 130
api POST "/sessions/$SID/bill/" "$UT"
api POST "/sessions/$SID/bill/" "$UT"
pause

say "6. End the session. Wallet = 500 - 2 x 50 = 400"
api POST "/sessions/$SID/end/" "$UT"
api GET /wallet/ "$UT"
pause

say "7. Error: ending a completed session (state machine)"
api POST "/sessions/$SID/end/" "$UT"
pause

say "8. Auto-end: a second user with Rs 260 runs out of balance"
api POST /auth/register/ "" "{\"username\":\"carol$SUF\",\"password\":\"S3cure-pass!\",\"role\":\"USER\"}"
CT=$(jget token </tmp/demo_last.json)
recharge "$CT" 240.00 >/dev/null
SID2=$(new_session "$CT" "$PT" "$PID")
echo "${dim}(Rs 240 is below the Rs 250 minimum -> start refused)${reset}"
api POST "/sessions/$SID2/start/" "$CT"
recharge "$CT" 20.00 >/dev/null
api POST "/sessions/$SID2/start/" "$CT" >/dev/null
rewind "$SID2" 320   # 5 full minutes -> Rs 250 charged, Rs 10 left
api POST "/sessions/$SID2/bill/" "$CT"
rewind "$SID2" 60    # 6th minute due, but only Rs 10 left
api POST "/sessions/$SID2/bill/" "$CT"
api GET /wallet/ "$CT"
echo "${bold}Status completed, ended_by system:insufficient_balance, wallet never negative.${reset}"
