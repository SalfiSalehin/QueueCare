#!/usr/bin/env bash
# Fills every CHANGE_ME in .env.production with a fresh random value. Idempotent only in the sense that it refuses to
# run when no placeholders remain (so it can never silently rotate live secrets). Requires: openssl.
set -euo pipefail
cd "$(dirname "$0")/.."
f=".env.production"
[ -f "$f" ] || { echo "Create it first: cp .env.production.example $f" >&2; exit 1; }
grep -q CHANGE_ME "$f" || { echo "No CHANGE_ME placeholders left in $f; refusing to rotate secrets." >&2; exit 1; }

owner=$(openssl rand -hex 24); app=$(openssl rand -hex 24); redis=$(openssl rand -hex 24)
jwt=$(openssl rand -hex 48);   csrf=$(openssl rand -hex 48)
sed -i.bak \
  -e "s/CHANGE_ME_OWNER_PASSWORD/$owner/g" -e "s/CHANGE_ME_APP_PASSWORD/$app/g" \
  -e "s/CHANGE_ME_REDIS_PASSWORD/$redis/g" -e "s/CHANGE_ME_64_BYTE_RANDOM_SECRET/$jwt/g" \
  -e "s/CHANGE_ME_CSRF_SECRET/$csrf/g" "$f"
rm -f "$f.bak"
chmod 600 "$f"
echo "Secrets written to $f (mode 600). Back it up in a password manager; it is NOT in git."
