// Toolbar + hidden-scrollbar regression against the localhost MOCK preview only.
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { browser } from "./browser-cdp.mjs";

const base = process.env.APP_TEST_URL || "http://localhost:80";
if (!/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(base)) throw new Error("localhost MOCK only");
const b = await browser();
const q = s => JSON.stringify(s);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const snap = async p => { const { data } = await b.send("Page.captureScreenshot", { format: "png" }); await writeFile(p, Buffer.from(data, "base64")); };
const exists = s => b.evaluate(`!!document.querySelector(${q(s)})`);
const menuOpens = async (trigger, item) => {
  await b.click(trigger);
  await b.wait(`!!document.querySelector(${q(item)})`);
};
const esc = () => b.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
try {
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await b.open("/library");
  await b.evaluate(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'obtv'})})`);
  await b.open("/library?ask=1");
  await b.wait(`!!document.querySelector('[data-testid=library-toolbar]') && !!document.querySelector('[data-testid=panel-archive-chat]')`);
  const sc = await b.evaluate(`(()=>{const e=document.querySelector('[data-testid=library-scroll]');const cs=getComputedStyle(e);return {w:e.offsetWidth-e.clientWidth,sw:cs.scrollbarWidth,oy:cs.overflowY}})()`);
  assert.equal(sc.w, 0, "no visible scrollbar gutter"); assert.equal(sc.oy, "auto");
  const scrolled = await b.evaluate(`(()=>{const e=document.querySelector('[data-testid=library-scroll]');if(e.scrollHeight<=e.clientHeight)return 'short';e.scrollTop=200;return e.scrollTop>0})()`);
  assert.ok(scrolled === true || scrolled === "short", "library still scrolls");
  const oneRow = await b.evaluate(`(()=>{const t=document.querySelector('[data-testid=library-toolbar]');const r=t.getBoundingClientRect();return r.height<130 && t.scrollWidth<=t.clientWidth+1})()`);
  assert.ok(oneRow, "toolbar fits beside assistant without overflow");
  console.log("PASS hidden scrollbar, scrolling preserved, compact toolbar with assistant open");
  for (const [item, title] of [["menu-upload-file","Upload Media"],["menu-import-link","Import from Link"],["menu-ingest-file","Ingest Media"]]) {
    await menuOpens("[data-testid=button-add-media]", `[data-testid=${item}]`);
    await b.click(`[data-testid=${item}]`);
    await b.wait(`[...document.querySelectorAll('[role=dialog]')].some(d=>d.innerText.includes(${q(title)}))`);
    await esc(); await sleep(250);
  }
  console.log("PASS Add media menu opens upload, import link and ingest dialogs");
  await menuOpens("[data-testid=button-library-filters]", "[data-testid=select-status]");
  for (const s of ["select-sort","select-status","select-media-type"]) assert.ok(await exists(`[data-testid=${s}]`));
  await esc(); await sleep(200);
  await menuOpens("[data-testid=button-library-view]", "[data-testid=button-view-list]");
  await b.click("[data-testid=button-view-list]");
  assert.equal(await b.evaluate("localStorage.getItem('library-view')"), "list");
  await b.click("[data-testid=button-view-grid]");
  await b.wait(`!!document.querySelector('[data-testid=button-card-size-large]')`);
  await b.click("[data-testid=button-card-size-large]");
  assert.equal(await b.evaluate("localStorage.getItem('library-card-size')"), "large");
  await b.click("[data-testid=button-card-size-medium]");
  await esc(); await sleep(200);
  assert.ok(await exists("[data-testid=button-select-page]"));
  console.log("PASS filters, view/card-size popovers and select page present");
  await b.open("/library");
  await b.wait(`!!document.querySelector('[data-testid=library-toolbar]')`); await sleep(800);
  await snap("/tmp/library-polish-desktop.png");
  await b.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await b.open("/library");
  await b.wait(`!!document.querySelector('[data-testid=library-toolbar]')`); await sleep(800);
  assert.ok(await b.evaluate(`document.documentElement.scrollWidth<=391`), "no horizontal overflow on mobile");
  await snap("/tmp/library-polish-mobile.png");
  console.log("PASS mobile layout; screenshots saved");
} finally { await b.close(); }
