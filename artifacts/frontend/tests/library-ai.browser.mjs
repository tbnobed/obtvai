// Live browser regression against the MOCK API only. Chromium must already
// expose CDP on port 9222. Never point APP_TEST_URL at production.
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { browser } from "./browser-cdp.mjs";

const base = process.env.APP_TEST_URL || "http://localhost:80";
if (!/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(base)) {
  throw new Error("Library AI browser test only permits a localhost MOCK preview");
}

const b = await browser();
const q = s => JSON.stringify(s);
const exists = s => `!!document.querySelector(${q(s)})`;
const text = s => b.evaluate(`document.querySelector(${q(s)})?.innerText`);
const wait = (s, timeout) => b.wait(exists(s), timeout);
const input = "[data-testid=input-ask-archive]";
const panel = "[data-testid=panel-archive-chat]";
const send = "[data-testid=button-send-question]";
const history = "[data-testid=button-toggle-history]";
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function ask(question) {
  await b.evaluate(`(()=>{const e=document.querySelector(${q(input)});e.focus();Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,${q(question)});e.dispatchEvent(new Event('input',{bubbles:true}))})()`);
  await b.wait(`!document.querySelector(${q(send)}).disabled`);
  await b.click(send);
}
async function snapshot(path) {
  const { data } = await b.send("Page.captureScreenshot", { format: "png" });
  await writeFile(path, Buffer.from(data, "base64"));
}

let createdId, retryId, legacyId;
try {
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await b.open("/library");
  assert.equal(await b.evaluate(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'obtv'})}).then(r=>r.status)`), 200, "MOCK fixture login");
  await b.open("/library");
  await wait("[data-testid=button-toggle-ask-archive]");
  await b.click("[data-testid=button-toggle-ask-archive]");
  await wait(panel);
  assert.match(await b.evaluate("location.search"), /ask=1/);
  assert.match(await text(panel), /Find the moment, not just the file/);
  console.log("PASS library entry opens docked assistant");

  const question = `Browser archive check ${Date.now()}`;
  await ask(question);
  await wait("[data-testid=status-asking]");
  assert.equal(await b.evaluate(`document.querySelector(${q(send)}).disabled`), true);
  assert.equal(await b.evaluate(`document.querySelector(${q("[data-testid=button-new-chat]")}).disabled`), true);
  await b.click(history);
  await wait("[data-testid=list-conversations]");
  assert.equal(await b.evaluate(`document.querySelector('[data-testid=row-conversation-conv-001]').getAttribute('aria-disabled')`), "true");
  await b.click("[data-testid=row-conversation-conv-001]");
  assert.equal(await b.evaluate("new URLSearchParams(location.search).get('conv')"), null, "history cannot switch during request");
  await b.click(history);
  await b.wait(`!!document.querySelector('[data-testid=text-assistant-message-1]') && !document.querySelector('[data-testid=status-asking]')`);
  createdId = await b.evaluate("new URLSearchParams(location.search).get('conv')");
  assert.ok(createdId?.startsWith("conv-"), "answer must persist its conversation id in the URL");
  assert.match(await text("[data-testid=text-assistant-message-1]"), /Sarah Chen/);
  await wait("[data-testid=card-citation-asset-001]");
  await b.wait(exists("[data-testid=img-citation-fallback]"));
  const media = await b.evaluate(`fetch('/api/media/asset-001').then(r=>r.json()).then(m=>({filename:m.filename,thumbnail_url:m.thumbnail_url}))`);
  assert.equal(await b.evaluate(`document.querySelector('[data-testid=card-citation-asset-001] [title]').title`), media.filename);
  assert.equal(await b.evaluate(`document.querySelector('[data-testid=link-moment-asset-001-1]').getAttribute('href')`), "/library/asset-001?t=50");
  assert.equal(await b.evaluate(`document.querySelector('[data-testid=link-citation-thumb-asset-001]').getAttribute('href')`), "/library/asset-001?t=50");
  assert.equal(await b.evaluate(exists("[data-testid=img-citation-fallback]")), !media.thumbnail_url, "missing thumbnail falls back to film icon");
  console.log("PASS real MOCK answer, citation asset, moment links, thumbnail fallback and pending guards");

  await snapshot("/tmp/library-ai-desktop.png");
  await b.open(`/library?ask=1&conv=${encodeURIComponent(createdId)}`);
  await b.wait(`document.querySelector('[data-testid=text-assistant-message-1]')?.innerText.includes(${q(question)})`);
  assert.equal(await b.evaluate("document.querySelectorAll('[data-testid^=text-assistant-message-]').length"), 1);
  await b.click("[data-testid=button-close-chat]");
  await b.wait(`!document.querySelector(${q(panel)})`);
  assert.equal(await b.evaluate("new URLSearchParams(location.search).get('conv')"), createdId);
  await b.click("[data-testid=button-toggle-ask-archive]");
  await b.wait(`document.querySelector('[data-testid=text-assistant-message-1]')?.innerText.includes(${q(question)})`);
  await b.click(history);
  await wait(`[data-testid=row-conversation-${createdId}]`);
  await b.click("[data-testid=row-conversation-conv-001]");
  await b.wait(`new URLSearchParams(location.search).get('conv')==='conv-001'`);
  await b.wait(`document.querySelector('[data-testid=text-assistant-message-1]')?.innerText.includes('cloud infrastructure')`);
  await b.click(history);
  await b.click(`[data-testid=row-conversation-${createdId}]`);
  await b.wait(`document.querySelector('[data-testid=text-assistant-message-1]')?.innerText.includes(${q(question)})`);
  console.log("PASS reload, close/reopen and history switching");

  // Failure is confined to browser fetch: the real MOCK API is left untouched.
  await b.evaluate(`(()=>{const real=fetch.bind(window);window.fetch=(url,opts)=>window.aiFailOnce && String(url).includes('/ai/ask') && (window.aiFailOnce=false,true) ? Promise.resolve(new Response(JSON.stringify({detail:'Temporary mock outage'}),{status:503,headers:{'Content-Type':'application/json'}})) : real(url,opts);window.aiFailOnce=true})()`);
  await b.click("[data-testid=button-new-chat]");
  await b.wait("new URLSearchParams(location.search).get('conv')===null");
  await ask("Retry this archive question");
  await wait("[data-testid=status-ask-error]");
  assert.equal(await b.evaluate("document.querySelectorAll('[data-testid^=text-assistant-message-]').length"), 0);
  await b.click("[data-testid=button-retry-ask]");
  await b.wait(`document.querySelector('[data-testid=text-assistant-message-1]')?.innerText.includes('Retry this archive question')`);
  retryId = await b.evaluate("new URLSearchParams(location.search).get('conv')");
  assert.ok(retryId && retryId !== createdId);
  console.log("PASS request failure, visible retry and no orphan answer");

  // A citation whose underlying asset is gone must not navigate to a dead player.
  const deletedScript = await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    (()=>{const originalFetch=window.fetch.bind(window);
    window.fetch=(url,opts)=>String(url).includes('/media/asset-001')
      ? Promise.resolve(new Response(JSON.stringify({detail:'Not found'}),{status:404,headers:{'Content-Type':'application/json'}}))
      : originalFetch(url,opts);
    })();
  ` });
  await b.open("/library?ask=1&conv=conv-001");
  await wait("[data-testid=card-citation-asset-001]");
  await b.wait(`document.querySelector('[data-testid=card-citation-asset-001]')?.innerText.includes('No longer in the library')`);
  assert.equal(await b.evaluate(exists("[data-testid=link-moment-asset-001-1]")), false);
  await b.send("Page.removeScriptToEvaluateOnNewDocument", { identifier: deletedScript.identifier });
  console.log("PASS deleted/unavailable cited asset degrades without dead links");

  // Legacy deep-link hands the question off once, then clears q from the URL.
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    (()=>{const originalFetch=window.fetch.bind(window);
    window.fetch=(url,opts)=>{
      if(String(url).includes('/ai/ask') && opts?.method?.toUpperCase()==='POST')
        sessionStorage.setItem('legacyAskCount',String(1+Number(sessionStorage.getItem('legacyAskCount')||0)));
      return originalFetch(url,opts);
    };
    })();
  ` });
  await b.open("/ai?q=Legacy%20archive%20question");
  await b.wait("location.pathname==='/library' && !new URLSearchParams(location.search).has('q')");
  await b.wait(`document.querySelector('[data-testid=text-assistant-message-1]')?.innerText.includes('Legacy archive question')`);
  assert.equal(await b.evaluate("sessionStorage.getItem('legacyAskCount')"), "1");
  legacyId = await b.evaluate("new URLSearchParams(location.search).get('conv')");
  await b.open("/library?ask=1");
  await sleep(1100);
  assert.equal(await b.evaluate("sessionStorage.getItem('legacyAskCount')"), "1", "redirect should not submit again");
  console.log("PASS legacy /ai?q redirects and asks only once");

  // A late response from a previously selected history thread cannot replace
  // the current thread's answer (no fabricated API data required).
  const heldScript = await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    (()=>{const real=fetch.bind(window);
      window.fetch=(url,opts)=>{
        if(String(url).includes('/ai/conversations/conv-001/messages'))
          return new Promise(resolve=>{window.qaReleaseOldHistory=()=>resolve(real(url,opts));});
        return real(url,opts);
      };
    })();
  ` });
  await b.open("/library?ask=1&conv=conv-001");
  await b.wait("!!window.qaReleaseOldHistory");
  await b.click(history);
  await wait(`[data-testid=row-conversation-${createdId}]`);
  await b.click(`[data-testid=row-conversation-${createdId}]`);
  await b.wait(`document.querySelector('[data-testid=text-assistant-message-1]')?.innerText.includes(${q(question)})`);
  await b.evaluate("window.qaReleaseOldHistory()");
  await sleep(400);
  assert.equal(await b.evaluate("new URLSearchParams(location.search).get('conv')"), createdId);
  assert.match(await text("[data-testid=text-assistant-message-1]"), new RegExp(question));
  await b.send("Page.removeScriptToEvaluateOnNewDocument", { identifier: heldScript.identifier });
  console.log("PASS late history response cannot replace selected conversation");

  await b.open(`/library?ask=1&conv=${encodeURIComponent(createdId)}`);
  await b.wait(`document.querySelector('[data-testid=text-assistant-message-1]')?.innerText.includes(${q(question)})`);
  await b.click(history);
  await wait(`[data-testid=row-conversation-${createdId}]`);
  await b.click(`[data-testid=button-delete-conversation-${createdId}]`);
  await b.wait(`!document.querySelector(${q(`[data-testid=row-conversation-${createdId}]`)})`);
  assert.equal(await b.evaluate("new URLSearchParams(location.search).get('conv')"), null);
  assert.equal(await b.evaluate(`fetch('/api/ai/conversations/${createdId}/messages').then(r=>r.status)`), 404);
  console.log("PASS deleting active thread clears URL, history and server messages");

  // Tablet 780px: md sidebar is visible; the assistant must own hit-testing over it.
  await b.send("Emulation.setDeviceMetricsOverride", { width: 780, height: 1024, deviceScaleFactor: 1, mobile: false });
  await b.open(`/library?ask=1&conv=${encodeURIComponent(retryId)}`);
  await b.wait(`document.querySelector('[data-testid=text-assistant-message-1]')?.innerText.includes('Retry this archive question')`);
  assert.equal(await b.evaluate(`document.querySelector(${q("[data-testid=aside-archive-chat]")}).getAttribute('role')`), "dialog");
  assert.ok(await b.evaluate(`(()=>{const p=document.querySelector(${q(panel)});return [[8,300],[120,500],[250,900],[770,20]].every(([x,y])=>p.contains(document.elementFromPoint(x,y)))})()`), "tablet assistant wins hit testing over the app sidebar");
  assert.equal(await b.evaluate(`document.activeElement?.matches(${q(input)})`), true, "tablet dialog focuses the prompt");
  const beforeTablet = await b.evaluate("location.pathname");
  await b.evaluate(`(()=>{const e=document.querySelector(${q(input)});const r=e.getBoundingClientRect();document.elementFromPoint(8,r.y+r.height/2)?.click()})()`);
  assert.equal(await b.evaluate("location.pathname"), beforeTablet, "left-edge click must not navigate via the sidebar");
  await b.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await b.wait(`!document.querySelector(${q(panel)})`);
  assert.equal(await b.evaluate("new URLSearchParams(location.search).get('ask')"), null);
  console.log("PASS tablet 780 dialog stacking, focus and Escape");

  await b.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await b.open(`/library?ask=1&conv=${encodeURIComponent(retryId)}`);
  await b.wait(`document.querySelector('[data-testid=text-assistant-message-1]')?.innerText.includes('Retry this archive question')`);
  assert.ok(await b.evaluate(`(()=>{const r=document.querySelector(${q(panel)}).getBoundingClientRect();return r.width>=389 && r.left>=0 && r.right<=390})()`), "mobile assistant covers available viewport");
  await wait("[data-testid=link-moment-asset-001-1]");
  assert.equal(await b.evaluate("document.querySelector('[data-testid=card-citation-asset-001]')?.getBoundingClientRect().right <= 390"), true);
  assert.equal(await b.evaluate(exists("[data-testid=img-citation-fallback]")), true);
  assert.ok(await b.evaluate(`(()=>{const e=document.querySelector(${q(input)}),r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))})()`), "mobile prompt is actually clickable");
  await snapshot("/tmp/library-ai-mobile.png");
  console.log("PASS mobile dock, citation bounds; screenshots saved");
} finally {
  // Remove only conversations created by this test; never modify seeded history.
  if (createdId || retryId || legacyId) {
    await b.evaluate(`Promise.all(${JSON.stringify([createdId, retryId, legacyId].filter(Boolean))}.map(id=>fetch('/api/ai/conversations/'+encodeURIComponent(id),{method:'DELETE'}).then(r=>r.status)))`);
  }
  await b.close();
}