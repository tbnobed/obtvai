import assert from "node:assert/strict";
import {
  readScope, withScope, parseTime, formatTime, itemRangeError, cleanRules, rulesSummary, containsItem, toggleId,
} from "./editorial.ts";

// Scope: URL wins, remembered workspace is the fallback, ws=all escapes.
assert.deepEqual(readScope("", "w1"), { workspaceId: "w1", collectionId: null, explicit: false });
assert.deepEqual(readScope("ws=all", "w1"), { workspaceId: null, collectionId: null, explicit: true });
assert.deepEqual(readScope("ws=w2&col=c1", "w1"), { workspaceId: "w2", collectionId: "c1", explicit: true });
assert.deepEqual(readScope("col=c1", null), { workspaceId: null, collectionId: "c1", explicit: true });
assert.equal(withScope("folder=x&ws=w1&col=c", null, null), "folder=x&ws=all");
assert.equal(withScope("ws=all", "w1", "c1"), "ws=w1&col=c1");

// Timecodes
assert.equal(parseTime("90"), 90);
assert.equal(parseTime("1:30"), 90);
assert.equal(parseTime("1:01:30"), 3690);
assert.equal(parseTime("1:30.5"), 90.5);
assert.equal(parseTime(""), null);
assert.equal(parseTime("a:b"), null);
assert.equal(parseTime("1::2"), null);
assert.equal(formatTime(3690), "1:01:30");
assert.equal(formatTime(65), "1:05");

// Ranges
assert.equal(itemRangeError(null, null), null);
assert.ok(itemRangeError(5, null));
assert.ok(itemRangeError(5, 5));
assert.ok(itemRangeError(-1, 5));
assert.equal(itemRangeError(0, 5), null);

// Rules
assert.deepEqual(cleanRules({ text: "  praise ", status: "", air_year: 2019 }), { text: "praise", air_year: 2019 });
assert.equal(rulesSummary({ text: "praise", air_year: 2019 }), "“praise” in name/path · aired 2019");

assert.ok(containsItem([{ id: "1", media_id: "m", start: null, end: null, note: "" }], "m", null, null));
assert.ok(!containsItem([{ id: "1", media_id: "m", start: 1, end: 2, note: "" }], "m", null, null));
assert.deepEqual(toggleId(["a"], "a"), []);
assert.deepEqual(toggleId(["a"], "b"), ["a", "b"]);

console.log("editorial tests passed");
