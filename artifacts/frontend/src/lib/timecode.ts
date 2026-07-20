export function formatTC(s: number, fps = 25, frames = true): string {
  if (!Number.isFinite(s) || s < 0) s = 0;
  const f = fps > 0 ? Math.round(fps) : 25;
  const totalFrames = Math.round(s * f);
  const fr = totalFrames % f;
  const totalSec = Math.floor(totalFrames / f);
  const m = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  const base = `${m}:${String(sec).padStart(2, "0")}`;
  return frames ? `${base}.${String(fr).padStart(2, "0")}` : base;
}

/**
 * Parse editor timecode input into seconds.
 * Accepts "mm:ss", "mm:ss.ff" (ff = frames), "h:mm:ss(.ff)", or bare seconds
 * under 60 ("42", "7.5"). Returns null when the text isn't a valid timecode.
 */
export function parseTC(text: string, fps = 25): number | null {
  const f = fps > 0 ? Math.round(fps) : 25;
  const t = text.trim();
  if (!t) return null;

  if (!t.includes(":")) {
    if (!/^\d{1,2}(\.\d+)?$/.test(t)) return null;
    const s = parseFloat(t);
    return Number.isFinite(s) && s < 60 ? s : null;
  }

  const m = /^(?:(\d+):)?(\d{1,3}):(\d{1,2})(?:\.(\d{1,2}))?$/.exec(t);
  if (!m) return null;
  const hours = m[1] ? parseInt(m[1], 10) : 0;
  const mins = parseInt(m[2], 10);
  const secs = parseInt(m[3], 10);
  const fr = m[4] ? parseInt(m[4], 10) : 0;
  if (secs > 59) return null;
  if (m[1] && mins > 59) return null;
  if (fr >= f) return null;
  return hours * 3600 + mins * 60 + secs + fr / f;
}
