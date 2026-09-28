// Sidebar independence and persistence against the localhost MOCK preview only.
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { browser } from "./browser-cdp.mjs";

const base = process.env.APP_TEST_URL || "http://localhost:80";
if (!/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(base)) throw new Error("localhost MOCK only");
const b = await browser();
const nav = "#app-navigation";
const folders = "#library-folders";
const hideNav = "[data-testid=button-hide-navigation]";
const showNav = "[data-testid=button-show-navigation]";
const hideFolders = "[data-testid=button-hide-folders]";
const showFolders = "[data-testid=button-show-folders]";
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const visible = s => b.evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(s)});return !!e && !!e.getClientRects().length && getComputedStyle(e).visibility!=='hidden'})()`);
const width = () => b.evaluate("Math.round(document.querySelector('[data-testid=library-scroll]').getBoundingClientRect().width)");
const snapshot = async path => {
  const { data } = await b.send("Page.captureScreenshot", { format: "png" });
  await writeFile(path, Buffer.from(data, "base64"));
};
const checkButton = async (selector, expanded, controls) => {
  assert.equal(await b.evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});return e?.getAttribute('aria-expanded')})()`), String(expanded));
  assert.equal(await b.evaluate(`document.querySelector(${JSON.stringify(selector)})?.getAttribute('aria-controls')`), controls);
  assert.equal(await visible(selector), true, `${selector} reachable`);
};

try {
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await b.open("/library");
  assert.equal(await b.evaluate(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'obtv'})}).then(r=>r.status)`), 200, "MOCK login");
  await b.evaluate("localStorage.removeItem('app-navigation-visible');localStorage.removeItem('library-folders-visible')");
  await b.open("/library");
  await b.wait("!!document.querySelector('[data-testid=library-toolbar]') && !!document.querySelector('#library-folders')");
  await checkButton(hideNav, true, "app-navigation");
  await checkButton(hideFolders, true, "library-folders");
  const bothShown = await width();

  await b.click(hideNav);
  await b.wait("!!document.querySelector('[data-testid=button-show-navigation]')");
  assert.equal(await visible(nav), false);
  assert.equal(await visible(folders), true);
  await checkButton(showNav, false, "app-navigation");
  const navHidden = await width();
  assert.ok(navHidden >= bothShown + 240, "hiding navigation reclaims its width");
  await b.click(showNav);
  await b.wait("!!document.querySelector('[data-testid=button-hide-navigation]')");
  assert.equal(await visible(nav), true);

  await b.click(hideFolders);
  await b.wait("!!document.querySelector('[data-testid=button-show-folders]')");
  assert.equal(await visible(folders), false);
  await checkButton(showFolders, false, "library-folders");
  assert.equal(await visible(nav), true);
  assert.ok(await width() >= bothShown + 225, "hiding folders reclaims its width");
  await b.click(hideNav);
  await b.wait("!!document.querySelector('[data-testid=button-show-navigation]')");
  assert.ok(await width() >= bothShown + 465, "hiding both reclaims both widths");
  await sleep(300);
  await snapshot("/tmp/library-both-sidebars-hidden.png");

  await b.open("/");
  await b.wait("!!document.querySelector('[data-testid=button-show-navigation]')");
  await b.open("/library");
  await b.wait("!!document.querySelector('[data-testid=button-show-folders]')");
  assert.equal(await visible(nav), false, "navigation preference persists across pages");
  assert.equal(await visible(folders), false, "folder preference persists across reload");
  await b.click(showFolders);
  await b.wait("!!document.querySelector('#library-folders')");
  await sleep(300);
  await snapshot("/tmp/library-folders-shown-navigation-hidden.png");
  await b.wait("!![...document.querySelectorAll('#library-folders [class*=group]')].find(e=>e.textContent.includes('Interviews'))");
  await b.evaluate("([...document.querySelectorAll('#library-folders [class*=group]')].find(e=>e.textContent.includes('Interviews'))).click()");
  await b.wait("new URLSearchParams(location.search).get('folder')==='folder-001'");
  await b.click(hideFolders);
  await b.click(showFolders);
  assert.equal(await b.evaluate("new URLSearchParams(location.search).get('folder')"), "folder-001", "active folder filter preserved");
  assert.ok(await b.evaluate("!![...document.querySelectorAll('#library-folders [class*=group]')].find(e=>e.textContent.includes('Interviews') && e.classList.contains('bg-secondary'))"), "active folder remains selected");
  await b.open("/library?folder=folder-001");
  await b.wait("!!document.querySelector('#library-folders')");
  assert.equal(await b.evaluate("localStorage.getItem('library-folders-visible')"), "true");
  await b.click(showNav);
  await b.wait("!!document.querySelector('[data-testid=button-hide-navigation]')");
  assert.equal(await b.evaluate("localStorage.getItem('app-navigation-visible')"), "true");

  await b.click(hideNav);
  await b.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await b.open("/library?folder=folder-001");
  await b.wait("!!document.querySelector('[data-testid=button-mobile-navigation]')");
  assert.equal(await visible(nav), false);
  await b.click("[data-testid=button-mobile-navigation]");
  await b.wait("getComputedStyle(document.querySelector('#app-navigation')).visibility==='visible'");
  assert.equal(await visible(nav), true, "mobile menu works despite hidden desktop preference");
  // Visibility becomes visible at transition start; wait until the close control
  // has actually translated into the viewport before dispatching a pointer click.
  await b.wait(`(()=>{const e=document.querySelector('[aria-label="Close navigation"]');const r=e.getBoundingClientRect();return new DOMMatrix(getComputedStyle(document.querySelector('#app-navigation')).transform).m41===0 && document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===e})()`);
  await sleep(400);
  const point = await b.evaluate(`(()=>{const r=document.querySelector('[aria-label="Close navigation"]').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  await b.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ ...point, id: 1 }] });
  await b.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await b.wait("getComputedStyle(document.querySelector('#app-navigation')).visibility==='hidden'");
  assert.equal(await visible(nav), false, "mobile menu closes");
  assert.equal(await b.evaluate("localStorage.getItem('app-navigation-visible')"), "false", "mobile menu does not change desktop preference");
  console.log("PASS independent sidebar toggles, widths, persistence, folder selection and mobile drawer; screenshots saved");
} finally {
  await b.close();
}