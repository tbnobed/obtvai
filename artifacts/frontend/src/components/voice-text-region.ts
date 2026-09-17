/**
 * The immutable part of a dictation insertion. Keeping this separate from the
 * DOM makes the replacement rules easy to exercise without a browser.
 */
export interface TextRegion {
  start: number;
  end: number;
  /** The end of the latest provisional transcript in the current value. */
  ownedEnd?: number;
  initialValue: string;
  prefix: string;
  suffix: string;
}

export interface RegionReplacement {
  value: string;
  start: number;
  end: number;
  inserted: string;
}

const isWhitespace = (character: string | undefined) =>
  !character || /\s/.test(character);

export function createTextRegion(
  value: string,
  selectionStart: number | null,
  selectionEnd: number | null,
): TextRegion {
  const start = Math.max(0, Math.min(selectionStart ?? value.length, value.length));
  const end = Math.max(start, Math.min(selectionEnd ?? start, value.length));

  return {
    start,
    end,
    initialValue: value,
    prefix: !isWhitespace(value[start - 1]) ? " " : "",
    suffix: !isWhitespace(value[end]) ? " " : "",
  };
}

/**
 * Replace only the owned range. `maxLength` intentionally treats zero as a
 * real limit; `undefined` is the only unlimited value.
 */
export function replaceTextRegion(
  currentValue: string,
  region: TextRegion,
  transcript: string,
  maxLength?: number,
): RegionReplacement | null {
  const ownedEnd = region.ownedEnd ?? region.end;
  const suffixLength = region.initialValue.length - region.end;
  if (
    currentValue.length < ownedEnd ||
    currentValue.slice(0, region.start) !== region.initialValue.slice(0, region.start) ||
    currentValue.slice(currentValue.length - suffixLength) !==
      region.initialValue.slice(region.end)
  ) {
    return null;
  }

  const trimmedTranscript = transcript.trim();
  let inserted = trimmedTranscript
    ? `${region.prefix}${trimmedTranscript}${region.suffix}`
    : "";
  const outsideLength = currentValue.length - (ownedEnd - region.start);

  if (maxLength !== undefined && Number.isFinite(maxLength)) {
    const available = Math.max(0, Math.floor(maxLength) - outsideLength);
    inserted = inserted.slice(0, available);
  }

  const value =
    currentValue.slice(0, region.start) +
    inserted +
    currentValue.slice(ownedEnd);

  return {
    value,
    start: region.start,
    end: region.start + inserted.length,
    inserted,
  };
}

export function restoreTextRegion(
  currentValue: string,
  region: TextRegion,
  expectedValue: string,
): string | null {
  return currentValue === expectedValue ? region.initialValue : null;
}