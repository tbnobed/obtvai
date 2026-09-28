// Browser regression against the running localhost MOCK preview only.
import assert from "node:assert/strict";
import { browser } from "./browser-cdp.mjs";

const base = process.env.APP_TEST_URL || "http://localhost:80";
if (!/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(base)) throw new Error("localhost MOCK only");
const b = await browser();
const cards = "[data-testid=assistant-library-results] [data-testid=search-asset-card]";
const setInput = async (value) => b.evaluate(`(()=>{const e=document.querySelector('[data-testid=input-ask-archive]');e.focus();Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}))})()`);
try {
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    const seed = [
      {id:'airdate-user',conversation_id:'conv-001',role:'user',content:'Find original airdate',citations:null},
      {id:'airdate-answer',conversation_id:'conv-001',role:'assistant',content:'Original airdate found',citations:[{media_id:'asset-001',filename:'airdate.mov',start_time:0,end_time:0,snippet:'Original air date: May 3, 1992'}]}
    ];
    window.conversationQA = { asks:0, searches:0, pending:false };
    const realFetch=fetch.bind(window);
    window.fetch=async(url,opts)=>{
      const path=String(url);
      if(/\\/api\\/search$/.test(path) && opts?.method==='POST') window.conversationQA.searches++;
      if(path.includes('/api/ai/conversations/conv-001/messages')) {
        return new Response(JSON.stringify([...seed,...JSON.parse(sessionStorage.getItem('conversationQaMessages')||'[]')]),{status:200,headers:{'Content-Type':'application/json'}});
      }
      if(/\\/api\\/ai\\/ask$/.test(path) && opts?.method==='POST') {
        const q=JSON.parse(opts.body).question;
        const next=++window.conversationQA.asks;
        window.conversationQA.pending=true;
        await new Promise(resolve=>setTimeout(resolve,700));
        const citations=q.includes('scope') ? null : q.includes('nonexistent') ? [] : [{media_id:'asset-002',filename:'new.mov',start_time:35,end_time:45,snippet:'New search match'}];
        const answer=q.includes('scope') ? 'Airdate means original broadcast date.' : q.includes('nonexistent') ? 'No matches.' : 'Found a new search result.';
        const saved=JSON.parse(sessionStorage.getItem('conversationQaMessages')||'[]');
        saved.push({id:'user-'+next,conversation_id:'conv-001',role:'user',content:q,citations:null},
          {id:'answer-'+next,conversation_id:'conv-001',role:'assistant',content:answer,citations});
        sessionStorage.setItem('conversationQaMessages',JSON.stringify(saved));
        window.conversationQA.pending=false;
        return new Response(JSON.stringify({answer,conversation_id:'conv-001',citations}),{status:200,headers:{'Content-Type':'application/json'}});
      }
      return realFetch(url,opts);
    };
  ` });
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await b.open("/library");
  await b.evaluate(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'obtv'})})`);
  await b.open("/library?ask=1&conv=conv-001");
  await b.wait(`document.querySelector('${cards}')?.dataset.assetId==='asset-001'`);
  await b.click(`${cards} [data-testid=checkbox-search-asset]`);
  const checked = `${cards} [data-testid=checkbox-search-asset]`;
  assert.equal(await b.evaluate(`document.querySelector('${checked}').getAttribute('aria-checked')`), "true");

  await setInput("What does airdate mean in this scope?");
  await b.click("[data-testid=button-send-question]");
  await b.wait("conversationQA.pending && !!document.querySelector('[data-testid=assistant-sources-loading]')");
  assert.equal(await b.evaluate(`document.querySelector('${cards}')?.dataset.assetId`), "asset-001", "unknown routing must not replace cards during thinking");
  assert.equal(await b.evaluate(`document.querySelector('${checked}').getAttribute('aria-checked')`), "true");
  assert.ok((await b.evaluate("document.querySelector('[data-testid=status-asking]').textContent")).includes("Thinking"));
  await b.wait(`!conversationQA.pending && !!document.querySelector('[data-testid=text-assistant-message-3]')`);
  assert.equal(await b.evaluate(`document.querySelector('${cards}')?.dataset.assetId`), "asset-001");
  assert.equal(await b.evaluate(`document.querySelector('${checked}').getAttribute('aria-checked')`), "true");
  assert.equal(await b.evaluate("conversationQA.searches"), 0);

  await b.open("/library?ask=1&conv=conv-001");
  await b.wait(`document.querySelector('${cards}')?.dataset.assetId==='asset-001'`);
  assert.ok((await b.evaluate("document.body.innerText")).includes("Airdate means original broadcast date."));
  await b.click("[data-testid=button-back-to-archive]");
  await b.wait("!document.querySelector('[data-testid=assistant-library-results]')");
  await setInput("Explain the airdate scope again");
  await b.click("[data-testid=button-send-question]");
  await b.wait("conversationQA.pending");
  assert.equal(await b.evaluate("!!document.querySelector('[data-testid=assistant-library-results]')"), false);
  await b.wait("!conversationQA.pending && !!document.querySelector('[data-testid=text-assistant-message-5]')");
  assert.equal(await b.evaluate("!!document.querySelector('[data-testid=assistant-library-results]')"), false, "conversation must not undo clear");
  await setInput("Find the new footage");
  await b.click("[data-testid=button-send-question]");
  await b.wait("conversationQA.pending");
  assert.equal(await b.evaluate("!!document.querySelector('[data-testid=assistant-library-results]')"), false);
  await b.wait(`document.querySelector('${cards}')?.dataset.assetId==='asset-002'`);
  assert.equal(await b.evaluate(`document.querySelector('${checked}').getAttribute('aria-checked')`), "false");
  await setInput("Find something nonexistent");
  await b.click("[data-testid=button-send-question]");
  await b.wait("conversationQA.pending");
  assert.equal(await b.evaluate(`document.querySelector('${cards}')?.dataset.assetId`), "asset-002");
  await b.wait("!!document.querySelector('[data-testid=search-empty]')");
  assert.equal(await b.evaluate(`document.querySelectorAll('${cards}').length`), 0, "empty search must replace cards");
  assert.equal(await b.evaluate("conversationQA.searches"), 0);
  console.log("PASS airdate search, scope conversation, reload, clear, fresh and empty searches");
} finally {
  await b.close();
}