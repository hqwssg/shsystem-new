#!/bin/sh
set -eu

SOFFICE_CMD=$(command -v libreoffice || command -v soffice || true)
test -n "$SOFFICE_CMD" || {
  echo 'ERROR: LibreOffice/soffice is required in the image. Install it before the offline update.' >&2
  exit 1
}

SOFFICE_REAL=$(readlink -f "$SOFFICE_CMD" 2>/dev/null || printf '%s\n' "$SOFFICE_CMD")
SOFFICE_DIR=$(dirname "$SOFFICE_REAL")
SOFFICE_MISSING=''
SOFFICE_CHECKED='|'
if command -v ldd >/dev/null 2>&1; then
  for candidate in \
    "$SOFFICE_REAL" "$SOFFICE_DIR/soffice.bin" "$SOFFICE_DIR/oosplash" \
    /opt/libreoffice*/program/soffice.bin /opt/libreoffice*/program/oosplash
  do
    test -f "$candidate" || continue
    case "$SOFFICE_CHECKED" in
      *"|$candidate|"*) continue ;;
    esac
    SOFFICE_CHECKED="${SOFFICE_CHECKED}${candidate}|"
    candidate_dir=$(dirname "$candidate")
    missing=$(LD_LIBRARY_PATH="${candidate_dir}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
      ldd "$candidate" 2>/dev/null | awk '/not found/ { print }' || true)
    if [ -n "$missing" ]; then
      SOFFICE_MISSING="${SOFFICE_MISSING}${candidate}:\n${missing}\n"
    fi
  done
fi

if [ -n "$SOFFICE_MISSING" ]; then
  printf 'ERROR: LibreOffice has unresolved shared libraries:\n%b' "$SOFFICE_MISSING" >&2
  echo 'Install the matching OS packages before updating (openEuler: nss nspr libXinerama; Debian/Ubuntu: libnss3 libnspr4 libxinerama1).' >&2
  exit 1
fi

if ! soffice_version=$("$SOFFICE_CMD" --headless --version 2>&1); then
  printf 'ERROR: LibreOffice cannot start:\n%s\n' "$soffice_version" >&2
  echo 'Resolve its shared-library dependencies before updating; do not bypass this preflight.' >&2
  exit 1
fi
printf '%s\n' "$soffice_version"
