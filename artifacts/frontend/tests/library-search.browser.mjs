// Unified library search against the localhost MOCK preview only. POST /api/search
// is intercepted in-page so request bodies (query, scope, filters) are asserted.
import assert from "node:assert/strict";
import { browser } from "./browser-cdp.mjs";

const base = process.env.APP_TEST_URL || "http://localhost:80";
if (!/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(base)) throw new Error("localhost MOCK only");
const b = await browser();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const input = "[data-testid=input-library-search]";
const path = () => b.evaluate("location.pathname+location.search");
const bodies = () => b.evaluate("JSON.stringify(searchQA.bodies)").then(JSON.parse);
const type = (v) => b.evaluate(`(()=>{const i=document.querySelector('${input}');i.focus();Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(i,${JSON.stringify(v)});i.dispatchEvent(new Event('input',{bubbles:true}))})()`);
const enter = () => b.evaluate(`document.querySelector('${input}').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))`);
try {
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    window.searchQA={bodies:[],fail:false,delayFirst:false};
    const realFetch=window.fetch.bind(window);
    window.fetch=async(url,options)=>{
      if(/\\/api\\/search$/.test(String(url)) && options?.method==='POST'){
        const body=JSON.parse(options.body);searchQA.bodies.push(body);
        if(searchQA.fail)return new Response('{"detail":"down"}',{status:500,headers:{'Content-Type':'application/json'}});
        const slow=searchQA.delayFirst&&searchQA.bodies.length===1;
        const tag=body.query;
        const results=[
          {media_id:'asset-002',filename:'b-'+tag+'.mov',thumbnail_url:null,start_time:42.5,end_time:48,score:0.91,match_type:'transcript',snippet:'said '+tag},
          {media_id:'asset-001',filename:'a-'+tag+'.mov',thumbnail_url:null,start_time:0,end_time:0,score:0.8,match_type:'filename',snippet:null},
          {media_id:'asset-002',filename:'b-'+tag+'.mov',thumbnail_url:null,start_time:12,end_time:15,score:0.7,match_type:'visual',snippet:'crowd'},
        ];
        if(slow)await new Promise(r=>setTimeout(r,1500));
        return new Response(JSON.stringify({query:tag,results}),{status:200,headers:{'Content-Type':'application/json'}});
      }
      return realFetch(url,options);
    };` });
  await b.open("/library");
  await b.evaluate(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'obtv'})})`);

  // Legacy redirect.
  await b.open("/search?q=city%20hall&scope=visual");
  await b.wait(`location.pathname==='/library' && document.querySelectorAll('[data-testid=search-asset-card]').length===2`);
  assert.equal(await path(), "/library?search_q=city+hall&scope=visual");
  let last = (await bodies()).at(-1);
  assert.deepEqual([last.query, last.search_type, last.limit], ["city hall", "visual", 500]);
  assert.ok(!(await b.evaluate("[...document.querySelectorAll('nav a')].some(a=>a.getAttribute('href')==='/search')")), "Search nav removed");
  console.log("PASS old /search redirect, scope preserved, nav entry removed");

  // Direct deep URL with folder/person/assistant params; filters sent to backend.
  await b.evaluate("searchQA.bodies=[]");
  await b.open("/library?folder=root&person=person-001&topic=housing&ask=1&q=who&search_q=mayor");
  await b.wait("searchQA.bodies.length>=1 && document.querySelectorAll('[data-testid=search-asset-card]').length===2");
  last = (await bodies()).at(-1);
  assert.equal(last.query, "mayor"); assert.equal(last.search_type, "combined");
  assert.equal(last.folder, "root"); assert.equal(last.person, "person-001"); assert.equal(last.topic, "housing");
  { const p = await path(); assert.ok(p.includes("ask=1") && p.includes("search_q=mayor") && p.includes("folder=root"), "assistant + search params coexist"); }
  // Rank preserved: best-ranked asset first with its moments in rank order.
  const order = await b.evaluate("[...document.querySelectorAll('[data-testid=search-asset-card]')].map(c=>c.dataset.assetId).join(',')");
  assert.equal(order, "asset-002,asset-001");
  console.log("PASS deep URL, exact filter names sent, ask+search params coexist, rank grouping");

  // Typing does not search; Enter commits once.
  await b.open("/library");
  await b.evaluate("searchQA.bodies=[]");
  await type("hou"); await type("housing vote"); await sleep(900);
  assert.equal((await bodies()).length, 0, "no per-keystroke searches");
  await enter();
  await b.wait("searchQA.bodies.length===1 && document.querySelectorAll('[data-testid=search-asset-card]').length===2");
  assert.equal(await path(), "/library?search_q=housing+vote");
  // Draft differs: applied query stays visible.
  await type("housing votes");
  await b.wait("!!document.querySelector('[data-testid=text-draft-pending]')");
  assert.ok((await b.evaluate("document.querySelector('[data-testid=text-applied-search]').innerText")).includes("housing vote"));
  await type("housing vote");
  console.log("PASS explicit submission only, applied query shown while draft differs");

  // Timestamp link navigation, then back returns to the results.
  await b.evaluate("document.querySelector('[data-testid=link-search-timestamp]').click()");
  await b.wait("location.pathname==='/library/asset-002'");
  assert.equal(await b.evaluate("location.search"), "?t=42");
  await b.evaluate("history.back()");
  await b.wait("location.search==='?search_q=housing+vote' && document.querySelectorAll('[data-testid=search-asset-card]').length===2");
  console.log("PASS timestamp opens asset at t, back restores search");

  // Back/forward across two committed searches.
  await type("crowd night"); await enter();
  await b.wait("location.search==='?search_q=crowd+night' && document.querySelector('[data-testid=search-asset-card] a')?.innerText.includes('crowd night')");
  await b.evaluate("history.back()");
  await b.wait(`location.search==='?search_q=housing+vote' && document.querySelector('${input}').value==='housing vote' && document.querySelector('[data-testid=search-asset-card] a')?.innerText.includes('housing vote')`);
  await b.evaluate("history.forward()");
  await b.wait("document.querySelector('[data-testid=search-asset-card] a')?.innerText.includes('crowd night')");
  console.log("PASS back/forward re-runs committed searches");

  // Error + retry.
  await b.evaluate("searchQA.fail=true");
  await type("broken query"); await enter();
  await b.wait("!!document.querySelector('[data-testid=search-error]')");
  await b.evaluate("searchQA.fail=false");
  await b.click("[data-testid=button-search-retry]");
  await b.wait("document.querySelectorAll('[data-testid=search-asset-card]').length===2");
  console.log("PASS error shows retry and recovers");

  // Clear returns to browse immediately.
  await b.click("[data-testid=button-clear-search]");
  await b.wait("location.search==='' && !document.querySelector('[data-testid=search-asset-card]')");
  assert.equal(await b.evaluate(`document.querySelector('${input}').value`), "");
  console.log("PASS clear returns to ordinary paged browsing");
} finally {
  await b.close();
}
