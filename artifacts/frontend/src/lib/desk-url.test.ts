import assert from "node:assert/strict";
import { readPage, patchSearch, recoverPage, offsetFor } from "./desk-url.ts";

assert.equal(readPage(null), 1);
assert.equal(readPage("0"), 1);
assert.equal(readPage("abc"), 1);
assert.equal(readPage("4"), 4);

// Filter change resets page
assert.equal(patchSearch("q=a&page=3", { q: "b" }), "q=b");
// Clearing removes key
assert.equal(patchSearch("q=a&sort=title", { q: "" }), "sort=title");
// Page change keeps filters
assert.equal(patchSearch("q=a", { page: "2" }), "q=a&page=2");
// page=1 dropped
assert.equal(patchSearch("q=a&page=2", { page: "1" }), "q=a");
// View toggle can preserve page explicitly
assert.equal(patchSearch("page=3", { view: "list", page: "3" }), "page=3&view=list");

// Out-of-range recovery after removal
assert.equal(recoverPage(3, 0, 101, 50), null); // page 3 still valid (101 rows)
assert.equal(recoverPage(3, 0, 100, 50), 2);
assert.equal(recoverPage(5, 0, 0, 50), 1);
assert.equal(recoverPage(1, 0, 0, 50), null);
assert.equal(recoverPage(2, 10, 60, 50), null);

assert.equal(offsetFor(1, 50), 0);
assert.equal(offsetFor(3, 25), 50);

console.log("desk-url tests passed");
