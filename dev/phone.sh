#!/usr/bin/env bash
# Bring the phone app up from nothing, and say plainly what is wrong when it
# will not come up. Written because the failure that actually happens is not
# a code failure: a full disk silently kills the simulator, and the symptom
# is an app that "isn't working".
set -uo pipefail
cd "$(dirname "$0")/.."

DEVICE="${AI_ANKI_SIM_DEVICE:-iPhone 17 Pro}"
API=http://127.0.0.1:8080
METRO=http://127.0.0.1:8081

say() { printf "\033[1m%s\033[0m\n" "$*"; }
bad() { printf "\033[31m%s\033[0m\n" "$*"; }

# 1. Disk. CoreSimulator mounts disk images to boot; under a few GB free it
#    boots and then dies seconds later, with no useful error anywhere.
free_gb=$(df -g /System/Volumes/Data | awk 'NR==2 {print $4}')
if [ "$free_gb" -lt 10 ]; then
  bad "Only ${free_gb}GB free. The simulator needs room to boot and will die without it."
  bad "Reclaim caches that regenerate on their own:"
  echo "  npm cache clean --force"
  echo "  rm -rf ~/Library/Developer/Xcode/DerivedData/*"
  echo "  rm -rf ~/Library/Developer/Xcode/iOS\\ DeviceSupport/*"
  echo "  brew cleanup -s"
  exit 1
fi
say "Disk: ${free_gb}GB free."

# 2. The database, then the API that needs it.
if ! docker ps --format '{{.Names}}' | grep -qx pgdev; then
  say "Starting Postgres..."
  docker start pgdev >/dev/null 2>&1 || docker run -d --name pgdev \
    -e POSTGRES_PASSWORD=x -e POSTGRES_DB=aianki -p 55432:5432 postgres:17 >/dev/null
  sleep 3
fi
if ! curl -sf "$API/dev/token" >/dev/null; then
  bad "The API is not answering on $API."
  echo "  Start it from the editor's launch config (ai-anki), or:"
  echo "  AI_ANKI_DATABASE_URL=postgresql://postgres:x@127.0.0.1:55432/aianki .venv/bin/python dev/devserver.py"
  exit 1
fi
say "API: up."

# 3. The simulator, booted and verified still alive -- a boot that reports
#    success and dies is the failure this whole script exists to catch.
udid=$(xcrun simctl list devices available | grep "$DEVICE (" | head -1 | sed -E 's/.*\(([0-9A-F-]{36})\).*/\1/')
[ -z "$udid" ] && { bad "No simulator named '$DEVICE'."; exit 1; }
if ! xcrun simctl list devices | grep "$udid" | grep -q Booted; then
  say "Booting $DEVICE..."
  xcrun simctl boot "$udid" 2>/dev/null
  xcrun simctl bootstatus "$udid" >/dev/null 2>&1
fi
open -a Simulator
sleep 5
xcrun simctl list devices | grep "$udid" | grep -q Booted || {
  bad "The simulator booted and then shut down -- nearly always disk pressure."; exit 1; }
say "Simulator: booted."

# 4. Metro, and the app itself. Expo Go does not reopen the app after a
#    device restart; it must be handed the URL.
if ! curl -sf "$METRO/status" >/dev/null; then
  say "Starting Metro..."
  (cd mobile && npx expo start >/tmp/ai-anki-metro.log 2>&1 &)
  for _ in $(seq 1 30); do curl -sf "$METRO/status" >/dev/null && break; sleep 2; done
fi
curl -sf "$METRO/status" >/dev/null || { bad "Metro never came up. See /tmp/ai-anki-metro.log"; exit 1; }
say "Metro: up."

xcrun simctl openurl booted "exp://127.0.0.1:8081"
say "Opening ai-anki on the phone. First load takes ~15s."
