"""Reuse IPV Curator WebProxy renders instead of re-encoding a local proxy.

Curator lays proxies out as:
  <CURATOR_PROXY_ROOT>/.../<YYYY>/<MM>/<DD>/<SourceBasename>-<HHMMSS>/<CuratorId>_video.mp4

The folder name is the original source filename (sanitized) plus a creation
timestamp; the files inside use Curator's internal id. Matching therefore
keys on the *folder* name with the trailing timestamp stripped, normalized
so punctuation differences don't matter.

The tree is date-partitioned by proxy-creation date (not source date), so a
one-pass walk builds an index {normalized_source_stem: video_path} which is
cached on disk (CURATOR_INDEX_TTL seconds, default 15 min) to keep petabyte
scale trees from being re-walked on every ingest.
"""
import json
import os
import re
import subprocess
import time

CURATOR_PROXY_ROOT = os.getenv("CURATOR_PROXY_ROOT", "/curator")
INDEX_PATH = os.path.join(os.getenv("ARTIFACTS_ROOT", "/artifacts"), "curator_proxy_index.json")
INDEX_TTL = int(os.getenv("CURATOR_INDEX_TTL", "900"))

# Trailing "-142509" / "_142509" timestamp Curator appends to the folder name
_TS_SUFFIX = re.compile(r"[-_]\d{6}$")


def _norm(name: str) -> str:
    """Normalize a name so 'BT 2026-06-23' and 'BT_20260623' style punctuation
    differences in sanitization don't break matching."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _build_index(root: str) -> dict:
    index: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        vids = sorted(f for f in filenames if f.lower().endswith("_video.mp4"))
        if not vids:
            continue
        dirnames[:] = []  # leaf proxy folder — don't descend further
        key = _norm(_TS_SUFFIX.sub("", os.path.basename(dirpath)))
        if key and key not in index:
            index[key] = os.path.join(dirpath, vids[0])
    return index


def _load_index() -> dict:
    if not os.path.isdir(CURATOR_PROXY_ROOT):
        return {}
    try:
        st = os.stat(INDEX_PATH)
        if time.time() - st.st_mtime < INDEX_TTL:
            with open(INDEX_PATH) as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    index = _build_index(CURATOR_PROXY_ROOT)
    tmp = INDEX_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(index, f)
        os.replace(tmp, INDEX_PATH)
    except OSError:
        pass
    return index


def _browser_playable(path: str) -> bool:
    """Only reuse the proxy if the browser can actually play it (H.264 + AAC)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "stream=codec_type,codec_name",
             "-of", "json", path],
            capture_output=True, text=True, timeout=30,
        )
        streams = json.loads(out.stdout or "{}").get("streams", [])
    except Exception:
        return False
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if not video or video[0].get("codec_name") != "h264":
        return False
    return all(a.get("codec_name") == "aac" for a in audio)


def find_curator_proxy(src_path: str) -> str | None:
    """Return the path to a matching, browser-playable Curator proxy, or None."""
    index = _load_index()
    if not index:
        return None
    stem = os.path.splitext(os.path.basename(src_path))[0]
    cand = index.get(_norm(stem))
    if cand and os.path.exists(cand) and _browser_playable(cand):
        return cand
    return None


if __name__ == "__main__":
    # Dry-run tester: python tasks/curator.py [source-file ...]
    # With no args: builds the index and prints its size + a few sample keys.
    # With source paths: shows the match (or why there is none) per file.
    import sys

    if not os.path.isdir(CURATOR_PROXY_ROOT):
        print(f"NOT MOUNTED: {CURATOR_PROXY_ROOT} is not a directory — "
              f"set CURATOR_PROXY_PATH in .env and recreate the container")
        sys.exit(1)

    print(f"Scanning {CURATOR_PROXY_ROOT} ...")
    t0 = time.time()
    idx = _build_index(CURATOR_PROXY_ROOT)
    print(f"Indexed {len(idx)} proxies in {time.time() - t0:.1f}s")
    for k in list(idx)[:10]:
        print(f"  {k}  ->  {idx[k]}")

    for arg in sys.argv[1:]:
        stem = os.path.splitext(os.path.basename(arg))[0]
        key = _norm(stem)
        cand = idx.get(key)
        if not cand:
            print(f"NO MATCH  {arg}  (key: {key})")
        elif not _browser_playable(cand):
            print(f"MATCH BUT NOT PLAYABLE (needs H.264+AAC)  {arg}  ->  {cand}")
        else:
            print(f"MATCH  {arg}  ->  {cand}")
