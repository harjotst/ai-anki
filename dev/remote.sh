#!/usr/bin/env bash
# The phone app, driven from a Mac that is not on the same Wi-Fi.
#
# phone.sh is the simulator path: everything is loopback, so nothing has to
# agree about addresses. A real phone on a tailnet has no loopback in common
# with the Mac, and the two failures that produces are both silent -- an API
# bound to 127.0.0.1 that simply refuses, and a Metro that advertises a
# hostname the phone cannot route to. This script exists to make both of them
# impossible rather than to save typing.
set -uo pipefail
cd "$(dirname "$0")/.."

TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
API=http://127.0.0.1:8080
METRO=http://127.0.0.1:8081

say() { printf "\033[1m%s\033[0m\n" "$*"; }
bad() { printf "\033[31m%s\033[0m\n" "$*"; }

# 1. The tailnet address. Deliberately IPv4 only: mobile/src/lib/session.ts
#    derives the API host with hostUri.split(":")[0], which turns an IPv6
#    literal into the garbage host "fd7a" and a phone that cannot reach
#    anything. `tailscale ip -4` is what keeps that from ever being chosen.
[ -x "$TS" ] || { bad "Tailscale is not installed. brew install --cask tailscale-app"; exit 1; }
ip=$("$TS" ip -4 2>/dev/null | head -1)
if [ -z "$ip" ]; then
  bad "Tailscale is installed but not connected. Open it and sign in."
  exit 1
fi
say "Tailnet address: $ip"

# 2. The API, on all interfaces. The command phone.sh prints binds loopback,
#    which is correct for the simulator and refuses every connection from a
#    real phone. Nothing about that failure says "wrong bind" -- the app just
#    shows errors on every tab -- so it is checked here instead.
status=$(curl -s -o /dev/null -w "%{http_code}" "$API/api/decks" || echo 000)
if [ "$status" = "000" ]; then
  bad "The API is not answering on $API."
  echo "  Start it bound to every interface, not just loopback:"
  echo "    set -a; source .env; set +a"
  echo "    .venv/bin/uvicorn app.asgi:app --host 0.0.0.0 --port 8080"
  echo "  (the ai-anki-supabase launch config already passes --host 0.0.0.0)"
  exit 1
fi
if ! curl -s -o /dev/null --connect-timeout 3 "http://$ip:8080/api/decks"; then
  bad "The API answers on loopback but not on $ip -- it is bound to 127.0.0.1."
  echo "  Restart it with --host 0.0.0.0."
  exit 1
fi
say "API: reachable at http://$ip:8080 (HTTP $status without a token is expected)."

# 3. Metro, advertising the tailnet address rather than whichever LAN address
#    it would guess. REACT_NATIVE_PACKAGER_HOSTNAME has to be set on the
#    command: @expo/env treats it as a local key and ignores committed .env
#    files for it, so putting it in mobile/.env looks right and does nothing.
if curl -sf "$METRO/status" >/dev/null; then
  advertised=$(curl -s -H 'expo-platform: ios' -H 'Accept: application/expo+json,application/json' \
    "$METRO" | sed -n 's/.*"hostUri":"\([^"]*\)".*/\1/p' | head -1)
  case "$advertised" in
    "$ip:"*) say "Metro: already up, advertising $advertised." ;;
    *) bad "Metro is up but advertising '$advertised', not $ip. Stop it and rerun this."
       echo "  pkill -f 'expo start'"
       exit 1 ;;
  esac
else
  say "Starting Metro pinned to $ip..."
  (cd mobile && REACT_NATIVE_PACKAGER_HOSTNAME="$ip" npx expo start >/tmp/ai-anki-metro.log 2>&1 &)
  for _ in $(seq 1 30); do curl -sf "$METRO/status" >/dev/null && break; sleep 2; done
  curl -sf "$METRO/status" >/dev/null || { bad "Metro never came up. See /tmp/ai-anki-metro.log"; exit 1; }
  say "Metro: up."
fi

cat <<EOF

$(say "On the phone: Expo Go -> Enter URL manually")

    exp://$ip:8081

Type it rather than scanning: a backgrounded expo start prints no QR code, and
the URL it logs says localhost, which is the Mac and not the phone.

First load over cellular is 30-60s, against the ~15s you get on the LAN.

Two things that will look like bugs:
  - Google sign-in fails until exp://$ip:8081/--/auth-callback is on the
    redirect allow-list in Supabase (Authentication -> URL Configuration).
    Email and password work regardless.
  - The Mac must stay awake. caffeinate does not stop lid-close sleep;
    sudo pmset -a disablesleep 1 does, and remember to set it back to 0.

Ports 8080 and 8081 are open on every network this Mac joins, not only the
tailnet -- Tailscale adds an interface, it does not firewall the others. Never
point a public tunnel at them, and never at dev/devserver.py, which hands a
valid session to anyone who asks for /dev/token.
EOF
