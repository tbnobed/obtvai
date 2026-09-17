import assert from "node:assert/strict";
import test from "node:test";
import {
  createTextRegion,
  replaceTextRegion,
  restoreTextRegion,
} from "./voice-text-region";

test("replaces the selected range while retaining both surrounding sides", () => {
  const region = createTextRegion("say old words", 4, 7);
  const result = replaceTextRegion("say old words", region, "new");

  assert.deepEqual(result, {
    value: "say new words",
    start: 4,
    end: 7,
    inserted: "new",
  });
});

test("cumulative updates replace the owned transcript rather than append", () => {
  const region = createTextRegion("prefix", 6, 6);
  const first = replaceTextRegion("prefix", region, "one");
  region.ownedEnd = first!.end;
  const second = replaceTextRegion(first!.value, region, "one two");

  assert.equal(first?.value, "prefix one");
  assert.equal(second?.value, "prefix one two");
});

test("maxLength includes the unchanged prefix and suffix, including zero", () => {
  const region = createTextRegion("ab", 1, 1);
  assert.equal(replaceTextRegion("ab", region, "voice", 0)?.value, "ab");
  assert.equal(replaceTextRegion("ab", region, "voice", 5)?.value, "a vob");
});

test("restoration is refused after an unowned edit", () => {
  const region = createTextRegion("before", 6, 6);
  const result = replaceTextRegion("before", region, "draft")!;

  assert.equal(restoreTextRegion(result.value, region, result.value), "before");
  assert.equal(restoreTextRegion("user edited", region, result.value), null);
});

test("empty transcripts do not leave boundary whitespace behind", () => {
  const region = createTextRegion("say old words", 4, 7);
  assert.equal(replaceTextRegion("say old words", region, "   ")?.value, "say  words");
});