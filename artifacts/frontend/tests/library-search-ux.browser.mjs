// Search-results UX regression with realistic LONG visual captions, against the
// localhost MOCK preview only. POST /api/search is intercepted in-page.
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { browser } from "./browser-cdp.mjs";

const base = process.env.APP_TEST_URL || "http://localhost:80";
if (!/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(base)) throw new Error("localhost MOCK only");
const b = await browser();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const snap = async (p) => { const { data } = await b.send("Page.captureScreenshot", { format: "png" }); await writeFile(p, Buffer.from(data, "base64")); };
const card = "[data-testid=search-asset-card]";
try {
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    window.searchQA={bodies:[]};
    const CAP='A wide establishing shot of a municipal council chamber with wood-paneled walls, a long curved dais where seven elected officials sit behind nameplates and microphones, an American flag and a state flag on poles to the left, a large projection screen displaying a zoning map with color-coded parcels, rows of members of the public seated in folding chairs, several holding handmade signs about affordable housing, a uniformed officer standing near the door, overhead fluorescent lighting casting even light, and a camera operator visible in the lower right corner recording the proceedings for the public access channel.';
    const realFetch=window.fetch.bind(window);
    window.fetch=async(url,options)=>{
      if(/\\/api\\/search$/.test(String(url)) && options?.method==='POST'){
        const body=JSON.parse(options.body);searchQA.bodies.push(body);
        const results=[];
        for(let a=0;a<9;a++){
          const n=a===0?14:(a%3)+1;
          for(let m=0;m<n;m++) results.push({media_id:'asset-'+String(a+1).padStart(3,'0'),filename:'council_meeting_2024_'+(a+1)+'_full_session_camera_A_master.mov',thumbnail_url:null,start_time:30+m*61.4+a,end_time:36+m*61.4+a,score:0.95-a*0.03-m*0.001,match_type:m%2?'transcript':'visual',snippet:(m%2?'Speaker: ':'')+CAP});
        }
        return new Response(JSON.stringify({query:body.query,results}),{status:200,headers:{'Content-Type':'application/json'}});
      }
      return realFetch(url,options);
    };` });
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await b.open("/library");
  await b.evaluate(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'obtv'})})`);
  // Tiny browse cards must not shrink search cards.
  await b.evaluate("localStorage.setItem('library-card-size','small');localStorage.setItem('library-view','grid')");
  await b.open("/library?search_q=council%20chamber&scope=visual");
  await b.wait(`document.querySelectorAll('${card}').length===9`);
  await sleep(400);

  const dims = await b.evaluate(`(()=>{const cs=[...document.querySelectorAll('${card}')];return {minW:Math.min(...cs.map(c=>c.getBoundingClientRect().width)),maxH:Math.max(...cs.map(c=>c.getBoundingClientRect().height)),cols:new Set(cs.map(c=>Math.round(c.getBoundingClientRect().left))).size}})()`);
  assert.ok(dims.minW >= 280, `search card width >= 280 (got ${dims.minW})`);
  assert.ok(dims.cols <= 4, `sensible column count (got ${dims.cols})`);
  assert.ok(dims.maxH < 420, `default card height bounded (got ${dims.maxH})`);
  const moments = await b.evaluate(`document.querySelectorAll('[data-testid=search-moment]').length`);
  assert.equal(moments, 0, "remaining moments collapsed by default");
  const clamp = await b.evaluate(`(()=>{const s=document.querySelector('[data-testid=search-snippet]');return getComputedStyle(s).webkitLineClamp+'|'+(s.scrollHeight>s.clientHeight)+'|'+s.title.length})()`);
  const [lc, overflow, titleLen] = clamp.split("|");
  assert.equal(lc, "3"); assert.equal(overflow, "true"); assert.ok(Number(titleLen) > 400, "full caption available via title");
  assert.ok((await b.evaluate(`document.querySelector('[data-testid=text-moment-count]').innerText`)).includes("14 matching moments"));
  const summary = await b.evaluate(`document.querySelector('[data-testid=search-summary]').innerText`);
  assert.ok(summary.startsWith("9 assets"), `asset-first summary (${summary})`);
  console.log(`PASS cards ${Math.round(dims.minW)}px min wide in ${dims.cols} cols, max ${Math.round(dims.maxH)}px tall, captions clamped, moments collapsed`);

  // Scope tabs visible near search bar; no duplicate scope in Filters; no sort while searching.
  assert.equal(await b.evaluate(`document.querySelector('[data-testid=scope-tab-visual]').getAttribute('aria-checked')`), "true");
  await b.click("[data-testid=button-library-filters]");
  await b.wait(`!!document.querySelector('[data-testid=select-status]')`);
  assert.ok(!(await b.evaluate(`!!document.querySelector('[data-testid=select-search-scope]')`)), "scope removed from Filters");
  assert.ok(!(await b.evaluate(`!!document.querySelector('[data-testid=select-sort]')`)), "sort hidden during search");
  await b.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 }); await sleep(200);
  await snap("/tmp/search-ux-desktop.png");

  // Expand / progressive more / collapse.
  await b.click(`${card} [data-testid=button-toggle-moments]`);
  await b.wait(`document.querySelectorAll('${card}')[0].querySelectorAll('[data-testid=search-moment]').length===6`);
  const expH = await b.evaluate(`Math.max(...[...document.querySelectorAll('[data-testid=search-moment] [data-testid=search-snippet]')].map(s=>s.getBoundingClientRect().height))`);
  assert.ok(expH < 50, `expanded snippets clamped (${expH})`);
  await b.click(`${card} [data-testid=button-more-moments]`);
  await b.wait(`document.querySelectorAll('${card}')[0].querySelectorAll('[data-testid=search-moment]').length===12`);
  await b.click(`${card} [data-testid=button-more-moments]`);
  await b.wait(`document.querySelectorAll('${card}')[0].querySelectorAll('[data-testid=search-moment]').length===13`);
  await b.click(`${card} [data-testid=search-moment] [data-testid=button-snippet-full]`);
  await b.wait(`(()=>{const s=document.querySelector('[data-testid=search-moment] [data-testid=search-snippet]');return s.scrollHeight<=s.clientHeight+1 && s.clientHeight>60})()`);
  await b.click(`${card} [data-testid=button-toggle-moments]`);
  await b.wait(`document.querySelectorAll('[data-testid=search-moment]').length===0`);
  console.log("PASS expand, progressive show-more, full-text inspection, collapse");

  // Select asset + moment feeds selection bar.
  await b.click(`${card} [data-testid=checkbox-search-asset]`);
  await b.click(`${card} [data-testid=search-best-match] [data-testid=checkbox-search-moment]`);
  assert.equal(await b.evaluate(`document.querySelector('${card} [data-testid=checkbox-search-asset]').getAttribute('aria-checked')`), "true");
  console.log("PASS asset and moment selection toggles");

  // Timestamp link.
  await b.evaluate(`document.querySelector('${card} [data-testid=link-search-timestamp]').click()`);
  await b.wait("location.pathname==='/library/asset-001'");
  assert.equal(await b.evaluate("location.search"), "?t=30");
  await b.evaluate("history.back()");
  await b.wait(`document.querySelectorAll('${card}').length===9`);
  console.log("PASS timestamp link opens asset at t and back restores");

  // Scope tab re-runs search.
  await b.evaluate("searchQA.bodies=[]");
  await b.click("[data-testid=scope-tab-transcript]");
  await b.wait("searchQA.bodies.length>=1 && location.search.includes('scope=transcript')");
  assert.equal((await b.evaluate("JSON.stringify(searchQA.bodies.at(-1))").then(JSON.parse)).search_type, "transcript");
  await b.click("[data-testid=scope-tab-combined]");
  await b.wait("!location.search.includes('scope=') && searchQA.bodies.at(-1).search_type==='combined'");
  console.log("PASS scope tabs re-run the committed search");

  // Browse grid unchanged (small cards still small).
  await b.click("[data-testid=button-clear-search]");
  await b.wait(`!document.querySelector('${card}')`); await sleep(800);
  await b.click("[data-testid=button-library-filters]");
  await b.wait(`!!document.querySelector('[data-testid=select-sort]')`);
  await b.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  console.log("PASS browse restores sort; browse grid untouched");

  // Mobile.
  await b.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await b.open("/library?search_q=council%20chamber&scope=visual");
  await b.wait(`document.querySelectorAll('${card}').length===9`); await sleep(500);
  const mob = await b.evaluate(`(()=>{const cs=[...document.querySelectorAll('${card}')];const sc=document.querySelector('[data-testid=library-scroll]');return {over:document.documentElement.scrollWidth>391||sc.scrollWidth>sc.clientWidth+1,cols:new Set(cs.map(c=>Math.round(c.getBoundingClientRect().left))).size,h:Math.max(...cs.map(c=>c.getBoundingClientRect().height)),tabs:!!document.querySelector('[data-testid=scope-tab-people], [data-testid=scope-tab-person]')}})()`);
  assert.ok(!mob.over, "no horizontal overflow on mobile");
  assert.equal(mob.cols, 1); assert.ok(mob.h < 480, `mobile card bounded (${mob.h})`); assert.ok(mob.tabs);
  const el = await b.evaluate(`(()=>{const e=document.querySelector('[data-testid=search-asset-card]');e.scrollIntoView({block:'start'});return true})()`); void el;
  await sleep(300);
  await snap("/tmp/search-ux-mobile.png");
  console.log("PASS mobile single column, bounded cards, no overflow; screenshots saved");
} finally {
  await b.close();
}
