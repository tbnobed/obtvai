import assert from "node:assert/strict";
import {
  buildSearchBody, groupSearchResults, legacySearchRedirect, readLibrarySearch, withLibrarySearch,
} from "./library-search.ts";

const r = (media_id: string, match_type: string, start: number, score: number) => ({
  media_id, filename: `${media_id}.mov`, thumbnail_url: null, start_time: start, end_time: start + 4, score, match_type, snippet: null,
});

// Grouping keeps backend rank: first hit decides asset order, moments stay in rank order.
const groups = groupSearchResults([
  r("b", "transcript", 40, 0.91), r("a", "filename", 0, 0.88), r("b", "visual", 12, 0.7), r("a", "person", 5, 0.6),
]);
assert.deepEqual(groups.map((g) => g.media_id), ["b", "a"]);
assert.deepEqual(groups[0].moments.map((m) => m.start_time), [40, 12]);
assert.equal(groups[1].filenameMatch, true);
assert.equal(groups[1].moments.length, 1);
assert.equal(groups[1].rank, 1);

// URL: search_q/scope distinct from assistant q; other params preserved.
assert.equal(withLibrarySearch("ask=1&q=hi&folder=f1", "mayor vote", "transcript"), "ask=1&q=hi&folder=f1&search_q=mayor+vote&scope=transcript");
assert.equal(withLibrarySearch("search_q=x&scope=visual&conv=c", "", "visual"), "conv=c");
assert.equal(withLibrarySearch("", "x", "combined"), "search_q=x");
assert.deepEqual(readLibrarySearch("search_q=%20crowd%20&scope=bogus"), { query: "crowd", scope: "combined" });
assert.equal(legacySearchRedirect("q=city%20hall&scope=visual"), "/library?search_q=city+hall&scope=visual");
assert.equal(legacySearchRedirect(""), "/library");

// Filters map to exact backend names; "all" media type omitted.
assert.deepEqual(buildSearchBody(" q ", "person", { media_type: "all", status: "ready", folder: "root", person: "p1", topic: "" }),
  { query: "q", search_type: "person", limit: 500, status: "ready", folder: "root", person: "p1" });
assert.equal(buildSearchBody("q", "combined", { media_type: "images" }).media_type, "images");
console.log("library-search: all assertions passed");
