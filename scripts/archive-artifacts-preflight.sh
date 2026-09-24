#!/usr/bin/env bash
# Host-side, opt-in archive storage validation. Run as root on the Docker host.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
target=${ARCHIVE_ARTIFACTS_PATH:-/mnt/curator-ipv/OBTV-AI}

die() { printf 'Archive preflight FAILED: %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "Run as host root (sudo); this SMB mount is writable by uid 0 only."
for cmd in docker jq findmnt realpath stat mktemp; do
  command -v "$cmd" >/dev/null || die "Missing required command: $cmd"
done
[[ $target = /* && -d $target && ! -L $target ]] || die "ARCHIVE_ARTIFACTS_PATH must be an existing absolute directory, not a symlink: $target"
target=$(realpath -e -- "$target")
[[ $target != / ]] || die "Refusing filesystem root."
[[ $(stat -c %u -- "$target") == 0 ]] || die "Target is not owned by host uid 0: $target"
[[ $(findmnt -T "$target" -n -o FSTYPE) == cifs ]] || die "Target is not on a mounted CIFS filesystem: $target (do not copy to local disk on a missing SMB mount)."
[[ $target != "$(findmnt -T "$target" -n -o TARGET)" ]] || die "Use the dedicated OBTV-AI subdirectory, not the share root."

# Inspect the effective base config rather than sourcing .env (which may contain
# secrets). Refuse any overlap with the watched media roots or Curator inbox.
sources=$(docker compose -f docker-compose.yml config --format json |
  jq -r '.services.watcher.volumes[] | select(.target == "/media" or .target == "/media2" or .target == "/curator" or .target == "/curator-inbox") | .source') ||
  die "Cannot resolve watcher discovery roots from Docker Compose."
while IFS= read -r source; do
  [[ -z $source ]] && continue
  source=$(realpath -m -- "$source")
  if [[ $target == "$source" || $target == "$source/"* || $source == "$target/"* ]]; then
    die "Archive path overlaps watcher source $source. Move the output OUTSIDE media discovery."
  fi
done <<< "$sources"

# Never auto-create paths under the share. Operator must prepare EXACTLY the
# designated seven directories before dry-run; Docker bind mounts must not
# accidentally create missing local directories if SMB disconnects.
probe=
renamed=
trap '[[ -z $probe ]] || rm -f -- "$probe"; [[ -z $renamed ]] || rm -f -- "$renamed"' EXIT
for name in audio thumbnails reels renders dubs voices graphics; do
  dir="$target/$name"
  [[ -d $dir && ! -L $dir && $(realpath -e -- "$dir") == "$dir" ]] ||
    die "Missing or symlinked archive directory: $dir. Operator: sudo mkdir -p -- '$dir' (ONLY if SMB is mounted)."
  [[ $(findmnt -T "$dir" -n -o FSTYPE) == cifs ]] ||
    die "Directory is not on CIFS: $dir"
  probe=$(mktemp "$dir/.obtv-archive-write-test.XXXXXXXX") ||
    die "Host root cannot write to $dir"
  printf 'obtv-archive-write-test\n' > "$probe" || die "Cannot write to $dir"
  [[ $(cat "$probe") == 'obtv-archive-write-test' ]] || die "Cannot read from $dir"
  renamed="${probe}.renamed"
  mv -- "$probe" "$renamed" || die "Cannot rename in $dir"
  probe=
  rm -- "$renamed" || die "Cannot delete disposable probe in $dir"
  renamed=
done
printf 'Archive preflight OK: %s (seven CIFS output dirs uid-0 read/write/rename/delete verified; outside watcher discovery)\n' "$target"