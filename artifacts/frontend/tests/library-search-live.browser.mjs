// Runs against the actual MOCK preview API, without intercepting fetch.
// Does not claim to validate the production vector/model service.
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { browser } from "./browser-cdp.mjs";

const b = await browser();
try {
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await b.open("/library");
  assert.equal(await b.evaluate(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'obtv'})}).then(r=>r.status)`), 200);
  await b.open("/library?search_q=interview&scope=filename");
  await b.wait(`document.querySelectorAll('[data-testid=search-asset-card]').length>0`);
  assert.match(await b.evaluate("document.querySelector('[data-testid=search-asset-card]').textContent"), /interview/i);
  assert.equal(await b.evaluate("document.querySelectorAll('[data-testid=link-search-timestamp]').length"), 0);
  const result = await b.evaluate(`fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:'interview',search_type:'combined',limit:500})}).then(r=>r.json())`);
  assert.ok(result.results.some(r => r.match_type === "filename"));
  const empty = await b.evaluate(`fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:'interview',search_type:'combined',media_ids:[],limit:500})}).then(r=>r.json())`);
  assert.equal(empty.results.length, 0);
  await b.open("/library?search_q=interview");
  await b.wait(`document.querySelectorAll('[data-testid=search-asset-card]').length>0`);
  await writeFile("/tmp/library-unified-search.png", Buffer.from((await b.send("Page.captureScreenshot", {format:"png"})).data, "base64"));
  console.log("PASS real mock endpoint integration: filenames, combined scope, empty-ID restriction, library render");
} finally {
  await b.close();
}