// Browser regression against the localhost MOCK preview only.
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { browser } from "./browser-cdp.mjs";

const base = process.env.APP_TEST_URL || "http://localhost:80";
if (!/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(base)) throw new Error("localhost MOCK only");
const b = await browser();
const cards = "[data-testid=assistant-library-results] [data-testid=search-asset-card]";
const input = "[data-testid=input-ask-archive]";
const setInput = async (selector, value) => b.evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.focus();Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}))})()`);
try {
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    window.sourceQA={searches:0,empty:sessionStorage.getItem('qaEmpty')==='1',metadata:sessionStorage.getItem('qaMetadata')==='1',fail:sessionStorage.getItem('qaFail')==='1',hold:sessionStorage.getItem('qaHold')==='1',release:null};
    const realFetch=fetch.bind(window);
    window.fetch=async(url,opts)=>{
      const path=String(url);
      if(/\\/api\\/search$/.test(path) && opts?.method==='POST') {
        sourceQA.searches++;
        return new Response(JSON.stringify({query:JSON.parse(opts.body).query,took_ms:1,results:[{media_id:'manual-001',filename:'manual.mov',start_time:7,end_time:12,score:1,match_type:'transcript',snippet:'manual result'}]}),{status:200,headers:{'Content-Type':'application/json'}});
      }
      if(/\\/api\\/ai\\/ask$/.test(path) && opts?.method==='POST') {
        await new Promise(resolve=>setTimeout(resolve,900));
        return realFetch(url,opts);
      }
      if(path.includes('/api/ai/conversations/conv-001/messages')) {
        if(sourceQA.hold) await new Promise(resolve=>{sourceQA.release=resolve});
        if(sourceQA.fail) return new Response(JSON.stringify({detail:'Unavailable'}),{status:503,headers:{'Content-Type':'application/json'}});
        const response=await realFetch(url,opts);
        if(sourceQA.empty || sourceQA.metadata) {
          const messages=await response.json();
          if(sourceQA.empty) messages.push({id:'empty-answer',conversation_id:'conv-001',role:'assistant',content:'No sources for this answer.',citations:[]});
          else messages.push({id:'metadata-answer',conversation_id:'conv-001',role:'assistant',content:'Original air date',citations:[{media_id:'asset-001',filename:'date.mov',start_time:0,end_time:0,snippet:'Original air date: May 3, 1992'}]});
          return new Response(JSON.stringify(messages),{status:200,headers:{'Content-Type':'application/json'}});
        }
        return response;
      }
      return realFetch(url,opts);
    };
  ` });
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await b.open("/library");
  await b.evaluate(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'obtv'})})`);
  await b.open("/library?folder=root&person=person-001&topic=housing&ask=1&conv=conv-001");
  await b.wait(`document.querySelectorAll('${cards}').length===1`);
  assert.equal(await b.evaluate("sourceQA.searches"), 0, "citations are not a redundant semantic search");
  assert.equal(await b.evaluate(`document.querySelector('${cards}').dataset.assetId`), "asset-001");
  assert.equal(await b.evaluate(`document.querySelector('${cards} [data-testid=link-search-timestamp]').getAttribute('href')`), "/library/asset-001?t=50");
  const { data: screenshot } = await b.send("Page.captureScreenshot", { format: "png" });
  await writeFile("/tmp/assistant-center-results.png", Buffer.from(screenshot, "base64"));
  await b.click(`${cards} [data-testid=checkbox-search-asset]`);
  assert.equal(await b.evaluate(`document.querySelector('${cards} [data-testid=checkbox-search-asset]').getAttribute('aria-checked')`), "true");

  // Clear restores the entire archive, not the previously filtered folder.
  await b.click("[data-testid=button-back-to-archive]");
  await b.wait(`!document.querySelector('[data-testid=assistant-library-results]') && !new URLSearchParams(location.search).has('folder')`);
  assert.ok(!new URLSearchParams(await b.evaluate("location.search")).has("person"));
  assert.ok(!new URLSearchParams(await b.evaluate("location.search")).has("topic"));
  assert.ok(await b.evaluate(`!!document.querySelector('[data-testid=panel-archive-chat]')`), "conversation remains open");
  await new Promise(r => setTimeout(r, 350));
  assert.equal(await b.evaluate(`!!document.querySelector('[data-testid=assistant-library-results]')`), false, "same answer must not reapply");

  // A new answer resumes automatic display.
  await setInput(input, "A follow-up about archive moments");
  await b.click("[data-testid=button-send-question]");
  await b.wait(`!!document.querySelector('[data-testid=status-asking]')`);
  assert.equal(await b.evaluate(`!!document.querySelector('[data-testid=assistant-library-results]')`), false, "cleared results remain hidden while routing is unknown");
  await b.wait(`document.querySelectorAll('${cards}').length===1`);
  assert.equal(await b.evaluate("sourceQA.searches"), 0);
  await b.click(`${cards} [data-testid=checkbox-search-asset]`);
  await setInput(input, "Another answer updates the same center panel");
  await b.click("[data-testid=button-send-question]");
  await b.wait(`!!document.querySelector('[data-testid=assistant-sources-loading]')`);
  assert.equal(await b.evaluate(`document.querySelector('${cards} [data-testid=checkbox-search-asset]').getAttribute('aria-checked')`), "true", "old cards and selections remain while asking");
  await b.wait(`document.querySelectorAll('${cards}').length===1 && document.querySelector('${cards} [data-testid=checkbox-search-asset]').getAttribute('aria-checked')==='false'`);
  assert.equal(await b.evaluate("sourceQA.searches"), 0);

  // Explicit search wins, without losing chat; clearing the search does not
  // immediately reapply the old answer.
  await setInput("[data-testid=input-library-search]", "manual query");
  await b.click("[data-testid=button-run-search]");
  await b.wait(`document.querySelector('[data-testid=search-asset-card]')?.dataset.assetId==='manual-001'`);
  assert.ok(await b.evaluate(`!!document.querySelector('[data-testid=panel-archive-chat]')`));
  await b.click("[data-testid=button-clear-search]");
  await b.wait(`!document.querySelector('[data-testid=search-asset-card]') && !document.querySelector('[data-testid=assistant-library-results]')`);

  // Switching history restores that thread's latest answer. New chat browses.
  await b.click("[data-testid=button-new-chat]");
  await b.wait(`!new URLSearchParams(location.search).has('conv') && !document.querySelector('[data-testid=assistant-library-results]')`);
  await b.click("[data-testid=button-toggle-history]");
  await b.click("[data-testid=row-conversation-conv-001]");
  await b.wait(`document.querySelectorAll('${cards}').length===1`);

  // Asset-level source displays the original-air-date metadata, never a fabricated moment.
  await b.evaluate("sessionStorage.setItem('qaMetadata','1')");
  await b.open("/library?ask=1&conv=conv-001");
  await b.wait(`document.querySelector('${cards} [data-testid=search-metadata-match] [data-testid=search-snippet]')?.textContent.includes('Original air date: May 3, 1992')`);
  assert.equal(await b.evaluate("sourceQA.searches"), 0);
  assert.equal(await b.evaluate(`document.querySelector('${cards} [data-testid=button-search-open]').getAttribute('href')`), "/library/asset-001");
  assert.equal(await b.evaluate(`document.querySelector('${cards} [data-testid=link-search-asset]').getAttribute('href')`), "/library/asset-001");
  assert.equal(await b.evaluate(`!!document.querySelector('${cards} [data-testid=link-search-timestamp], ${cards} [data-testid=search-best-match], ${cards} [data-testid=text-moment-count], ${cards} [data-testid=button-search-play]')`), false);
  assert.ok(!(await b.evaluate(`document.querySelector('${cards}').innerText`)).includes("Filename match"));
  await b.evaluate("sessionStorage.removeItem('qaMetadata')");

  // Latest answer with zero citations replaces old sources, not stale cards.
  await b.evaluate("sessionStorage.setItem('qaEmpty','1')");
  await b.open("/library?ask=1&conv=conv-001");
  await b.wait(`!!document.querySelector('[data-testid=search-empty]')`);
  assert.equal(await b.evaluate(`document.querySelectorAll('${cards}').length`), 0);
  await b.click("[data-testid=search-empty] button");
  await b.wait(`!document.querySelector('[data-testid=assistant-library-results]')`);

  // History load and failure are visible in the center, with retry.
  await b.evaluate("sessionStorage.removeItem('qaEmpty');sessionStorage.setItem('qaHold','1')");
  await b.open("/library?ask=1&conv=conv-001");
  await b.wait(`!!window.sourceQA.release && !!document.querySelector('[data-testid=assistant-sources-loading]')`);
  await b.evaluate("sourceQA.release();sessionStorage.removeItem('qaHold')");
  await b.wait(`document.querySelectorAll('${cards}').length===1`);
  await b.evaluate("sessionStorage.setItem('qaFail','1')");
  await b.open("/library?ask=1&conv=conv-001");
  await b.wait(`!!document.querySelector('[data-testid=assistant-sources-error]')`);
  await b.evaluate("sourceQA.fail=false;sessionStorage.removeItem('qaFail')");
  await b.click("[data-testid=assistant-sources-error] button");
  await b.wait(`document.querySelectorAll('${cards}').length===1`);
  console.log("PASS assistant sources, clearing, follow-ups, manual search, history, empty, loading and retry");
} finally {
  await b.close();
}