#!/bin/bash
# No program/configuration replacement, SQL, backup, key rotation or restart.
set -Eeuo pipefail
PACKAGE_ROOT=$(cd -- "$(dirname -- "$0")" && pwd)
REPORT_AI_PACKAGE=${REPORT_AI_PACKAGE:-/opt/server-report-ai-update-20261108-133215}
WEB_CONTAINER=${WEB_CONTAINER:-ruoyi-web}
trap 'echo "ERROR: verification did not pass. Preserve the log; do not rerun database initialization." >&2' ERR
(cd "$PACKAGE_ROOT" && sha256sum -c SHA256SUMS >/dev/null)
[ -f "$REPORT_AI_PACKAGE/SHA256SUMS" ]
(cd "$REPORT_AI_PACKAGE" && sha256sum -c SHA256SUMS >/dev/null)
docker exec -i "$WEB_CONTAINER" /opt/carbon-report-venv/bin/python -c \
  "$(cat "$PACKAGE_ROOT/scripts/verify-report-ai-files.py")" < "$REPORT_AI_PACKAGE/SHA256SUMS"
WEB_CONTAINER="$WEB_CONTAINER" bash "$PACKAGE_ROOT/scripts/check-report-ai-health.sh"
echo 'AI delivery files and service checks passed. Sign in to verify AI connectivity and report generation with valid credentials.'
