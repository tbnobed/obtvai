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


_VIDEO_EXTS = (".mxf", ".mov", ".mp4", ".mkv", ".avi", ".ts", ".m2ts", ".wmv", ".flv", ".webm")


def is_curator_video(path: str) -> bool:
    """True when the ingested file IS a Curator web proxy itself."""
    return os.path.basename(path).lower().endswith("_video.mp4")


def has_audio_stream(path: str) -> bool:
    """True if the file contains at least one audio stream."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_name", "-of", "json", path],
            capture_output=True, text=True, timeout=30,
        )
        return bool(json.loads(out.stdout or "{}").get("streams"))
    except Exception:
        return False


def find_curator_audio(video_path: str) -> list[str]:
    """Sidecar audio renders next to a Curator _video.mp4.

    Curator renders WebProxy video and audio as SEPARATE files in the same
    folder (<id>_video.mp4 + <id>_audio0.mp4 [, _audio1...]), so the video
    file alone is silent."""
    d = os.path.dirname(video_path)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    auds = sorted(n for n in names if re.search(r"_audio\d*\.(mp4|m4a|aac)$", n.lower()))
    return [os.path.join(d, n) for n in auds]


def find_sidecar_source_path(video_path: str) -> str | None:
    """Best-effort: pull the hi-res original path out of Curator's sidecar
    metadata XMLs (…_metadata_complete.xml / …_index.xml) that sit next to
    the proxy. Schema-agnostic: scans every element text/attribute for a
    path-like string ending in a video extension that isn't the proxy itself.
    """
    import xml.etree.ElementTree as ET

    folder = os.path.dirname(video_path)
    try:
        xmls = sorted(
            f for f in os.listdir(folder) if f.lower().endswith(".xml")
        )
    except OSError:
        return None
    # Small metadata files first — the big index.xml is the last resort
    xmls.sort(key=lambda f: os.path.getsize(os.path.join(folder, f)))

    # Curator folder name = <source stem>-HHMMSS; the hi-res path should
    # contain that stem. Used to rank ambiguous candidates.
    folder_stem = re.sub(r"-\d{6}$", "", os.path.basename(folder))
    stem_key = _norm(folder_stem)

    def _clean(value: str) -> str | None:
        v = (value or "").strip()
        if v.lower().startswith("file://"):
            from urllib.parse import unquote, urlparse
            parsed = urlparse(v)
            v = unquote(parsed.path or "")
            if parsed.netloc:  # file://server/share/... → UNC
                v = f"\\\\{parsed.netloc}{v.replace('/', chr(92))}"
        if len(v) < 5 or len(v) > 1000:
            return None
        low = v.lower()
        if low.startswith(("http://", "https://")):
            return None
        if not low.endswith(_VIDEO_EXTS):
            return None
        if "_video.mp4" in low or re.search(r"_audio\d*\.", low):
            return None  # the proxy files themselves
        if ("/" not in v) and ("\\" not in v):
            return None  # bare filename, not a path
        return v

    candidates: list[str] = []
    for name in xmls:
        try:
            tree = ET.parse(os.path.join(folder, name))
        except (ET.ParseError, OSError):
            continue
        for el in tree.iter():
            for value in [el.text or "", *el.attrib.values()]:
                v = _clean(value)
                if v and v not in candidates:
                    candidates.append(v)
        if candidates:
            break  # smallest sidecar with candidates wins

    if candidates:
        # Prefer a path whose basename matches the proxy folder's source stem.
        for cand in candidates:
            base = os.path.splitext(os.path.basename(cand.replace("\\", "/")))[0]
            if _norm(base) == stem_key or stem_key in _norm(base):
                return cand
        return candidates[0]

    # Curator's on-disk sidecars usually carry NO hi-res path (it lives in
    # Curator's DB). Fallback: reconstruct from the proxy folder name, which
    # IS the source basename: <CURATOR_SOURCE_ROOT><stem><CURATOR_SOURCE_EXT>.
    src_root = os.getenv("CURATOR_SOURCE_ROOT", "").strip()
    if src_root and folder_stem:
        ext = os.getenv("CURATOR_SOURCE_EXT", ".mxf").strip() or ".mxf"
        if not ext.startswith("."):
            ext = "." + ext
        sep = "\\" if ("\\" in src_root or re.match(r"^[A-Za-z]:", src_root)) else "/"
        return src_root.rstrip("/\\") + sep + folder_stem + ext
    return None


def find_curator_proxy(src_path: str) -> str | None:
    """Return the path to a matching, browser-playable Curator proxy, or None."""
    # If the ingested source IS a Curator proxy (direct-ingest mode), use it as
    # its own proxy — zero re-encoding.
    if is_curator_video(src_path) and os.path.exists(src_path) and _browser_playable(src_path):
        return src_path
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
        hires_src = cand or (arg if is_curator_video(arg) else None)
        if hires_src:
            hires = find_sidecar_source_path(hires_src)
            print(f"  SIDECAR HI-RES: {hires or 'not found in sidecar XML'}")
