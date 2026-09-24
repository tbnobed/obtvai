#!/usr/bin/env bash
# Offline Compose/shell contract check; does not touch Docker daemon or SMB.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
for cmd in docker jq; do
  command -v "$cmd" >/dev/null || { echo "Missing $cmd" >&2; exit 1; }
done
bash -n scripts/archive-artifacts-preflight.sh scripts/archive-artifacts-migrate.sh
base=$(docker compose -f docker-compose.yml config --format json)
archive=$(docker compose -f docker-compose.yml -f archive-artifacts.compose.yml config --format json)
for service in api worker-gpu worker-gpu-2 worker-cpu worker-graphics; do
  jq -e --arg service "$service" '
    [.services[$service].volumes[] | select(.target == "/artifacts")] |
    length == 1 and .[0].type == "volume"' <<< "$base" >/dev/null
  jq -e --arg service "$service" '
    [.services[$service].volumes[] | select(.target == "/artifacts")] |
    length == 1 and .[0].type == "volume"' <<< "$archive" >/dev/null
  for name in audio thumbnails reels renders dubs voices graphics; do
    jq -e --arg service "$service" --arg name "$name" '
      [.services[$service].volumes[] | select(.target == ("/artifacts/" + $name))] |
      length == 1 and .[0].type == "bind" and
      .[0].source == ("/mnt/curator-ipv/OBTV-AI/" + $name)' <<< "$archive" >/dev/null
  done
  jq -e --arg service "$service" '
    [.services[$service].volumes[] | select(.target == "/artifacts/proxies")] |
    length == 0' <<< "$archive" >/dev/null
  jq -e --arg service "$service" '
    .services[$service].environment.CURATOR_ARCHIVE_MODE != null and
    (.services[$service].environment.CURATOR_ARCHIVE_ROOTS | length > 0)' <<< "$base" >/dev/null
done
jq -e '
  ([.services.watcher.volumes[] | select(.target == "/artifacts")] | length == 0) and
  (.services.watcher.environment.WATCHER_EXCLUDE_ROOTS | length > 0)
' <<< "$archive" >/dev/null
for service in postgres qdrant redis worker-bagel; do
  jq -e --arg service "$service" '.services[$service].volumes' <<< "$base" > /dev/null
  diff -u \
    <(jq -S --arg service "$service" '.services[$service].volumes' <<< "$base") \
    <(jq -S --arg service "$service" '.services[$service].volumes' <<< "$archive")
done
[[ $(grep -c 'for name in "${dirs\[@\]}"' scripts/archive-artifacts-migrate.sh) -ge 2 ]]
grep -Fq 'dirs=(audio thumbnails reels renders dubs voices graphics)' scripts/archive-artifacts-migrate.sh
grep -Fq 'EXCLUDED: proxies/' scripts/archive-artifacts-migrate.sh
echo 'Archive overlay and script syntax OK (no server or SMB changes).'