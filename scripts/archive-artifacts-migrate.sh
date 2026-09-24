#!/usr/bin/env bash
# Stage only designated derived-output directories to SMB. Never copy proxies.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
mode=dry-run
case ${1:-} in
  '') ;;
  --apply) mode=apply ;;
  *) printf 'Usage: sudo %s [--apply]\n' "$0" >&2; exit 2 ;;
esac
[[ $# -le 1 ]] || { printf 'Usage: sudo %s [--apply]\n' "$0" >&2; exit 2; }

for cmd in docker jq rsync realpath; do
  command -v "$cmd" >/dev/null || { printf 'Missing required command: %s\n' "$cmd" >&2; exit 1; }
done
"$repo/scripts/archive-artifacts-preflight.sh"
target=$(realpath -e -- "${ARCHIVE_ARTIFACTS_PATH:-/mnt/curator-ipv/OBTV-AI}")

# Resolve the actual Compose project/volume name; never assume a project prefix.
volume=$(docker compose -f docker-compose.yml config --format json | jq -er '.volumes.artifacts_data.name') ||
  { echo 'Cannot resolve artifacts_data volume name.' >&2; exit 1; }
source=$(docker volume inspect --format '{{.Mountpoint}}' "$volume") ||
  { echo "Volume $volume missing; refusing to initialize an empty archive." >&2; exit 1; }
[[ -d $source ]] || { echo "Volume mountpoint is not a directory: $source" >&2; exit 1; }
source=$(realpath -e -- "$source")
[[ $source != "$target" && $source != "$target/"* && $target != "$source/"* ]] ||
  { echo "Source and target overlap; aborting." >&2; exit 1; }

dirs=(audio thumbnails reels renders dubs voices graphics)
printf 'Copy plan (%s; no overwrites/deletions): %s/{%s}/ -> %s/{%s}/\n' \
  "$mode" "$source" "$(IFS=,; echo "${dirs[*]}")" "$target" "$(IFS=,; echo "${dirs[*]}")"
echo 'EXCLUDED: proxies/ (all proxy media), every other root file and directory. The original local artifacts_data volume is left untouched.'

# --existing reports content/symlink differences already present on SMB.
# Refuse conflicts instead of overwriting any preexisting archive material.
for name in "${dirs[@]}"; do
  if [[ ! -d $source/$name ]]; then
    printf 'SKIP %s/ (absent in source volume; archive output directory remains ready)\n' "$name"
    continue
  fi
  conflicts=$(rsync -rlcn --existing --out-format='%n' "$source/$name/" "$target/$name/") ||
    { echo "Failed to compare existing $name target files." >&2; exit 1; }
  [[ -z $conflicts ]] ||
    { printf 'Conflicts in %s/; no copy performed:\n%s\n' "$name" "$conflicts" >&2; exit 1; }
done

if [[ $mode == dry-run ]]; then
  for name in "${dirs[@]}"; do
    [[ ! -d $source/$name ]] && continue
    printf 'DRY RUN %s/\n' "$name"
    rsync -rlt --ignore-existing --dry-run --itemize-changes --stats "$source/$name/" "$target/$name/"
  done
  echo 'DRY RUN ONLY. Stop api and all four media workers, then --apply. Confirm archive playback is enabled before opting in.'
  exit 0
fi

# Workers MUST be stopped by the operator before --apply; reject running
# containers rather than copying changing files and reporting a false success.
active=$(docker compose -f docker-compose.yml ps --status running --services |
  grep -E '^(api|worker-gpu|worker-gpu-2|worker-cpu|worker-graphics)$' || true)
[[ -z $active ]] ||
  { printf 'Stop these writers before --apply: %s\n' "$active" >&2; exit 1; }

# No --delete, no --inplace; existing target files are never overwritten.
# CIFS uid mapping may reject chown/chmod, so preserve file bytes, symlink
# targets, directory layout and mtime rather than POSIX ownership/mode.
for name in "${dirs[@]}"; do
  [[ ! -d $source/$name ]] && continue
  rsync -rlt --ignore-existing --stats "$source/$name/" "$target/$name/"
  remaining=$(rsync -rlcn --out-format='%n' "$source/$name/" "$target/$name/") ||
    { echo "Post-copy checksum comparison failed in $name." >&2; exit 1; }
  [[ -z $remaining ]] ||
    { printf 'Archive verification failed in %s/ (missing/different files); do NOT enable overlay:\n%s\n' "$name" "$remaining" >&2; exit 1; }
done
echo 'Seven derived-output directories checked by content (when source exists). Original artifacts_data volume and proxies/ remain local and untouched.'