#!/usr/bin/env bash
# Simulate time passing on a session (dev database only).
# Usage: ./rewind.sh <session_id> <seconds>     e.g. ./rewind.sh 1 130
set -euo pipefail
uv run python manage.py shell --no-imports -c "
from sessions_app.models import Session; from datetime import timedelta
s = Session.objects.get(pk=$1)
if s.started_at is None: raise SystemExit('Session $1 has not started yet (status: %s). Start it first.' % s.status)
s.started_at -= timedelta(seconds=$2); s.save()
print('session', s.pk, 'started_at moved back', $2, 'seconds')"
