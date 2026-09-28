import assert from "node:assert/strict";
import { browser } from "./browser-cdp.mjs";

if (process.env.APP_TEST_URL && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(process.env.APP_TEST_URL)) throw Error("Mock localhost only");
const b = await browser();
try {
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    const originalFetch = window.fetch.bind(window);
    window.reportMutations = 0;
    window.fetch = async (url, options) => {
      if (String(url).includes('/api/media/reports/dismiss-test')) {
        if (options?.method && options.method !== 'GET') window.reportMutations++;
        const status = localStorage.getItem('test-report-status') || 'success';
        if (status === 'unavailable') return new Response('{}', {status: 503});
        return new Response(JSON.stringify({id:'dismiss-test',status,total_assets:1,processed_assets:1,
          progress:100,failed_assets:0,publish_status:'success',download_url:'/api/media/reports/dismiss-test/download'}),
          {headers:{'Content-Type':'application/json'}});
      }
      return originalFetch(url, options);
    };
  ` });
  await b.open("/library");
  await b.evaluate(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'obtv'})})`);
  for (const status of ["success", "running", "error", "unavailable"]) {
    await b.evaluate(`localStorage.setItem('active-media-report-id','dismiss-test');localStorage.setItem('test-report-status',${JSON.stringify(status)})`);
    await b.open("/library");
    await b.wait(`!!document.querySelector('[data-testid=button-dismiss-media-report]')`);
    await b.click("[data-testid=button-dismiss-media-report]");
    await b.wait(`!document.querySelector('[data-testid=button-dismiss-media-report]')`);
    assert.equal(await b.evaluate(`localStorage.getItem('active-media-report-id')`), null);
    assert.equal(await b.evaluate("window.reportMutations"), 0, "dismiss must not cancel or delete");
    await b.open("/library");
    await b.wait(`!!document.querySelector('[data-testid=input-library-search]')`);
    assert.equal(await b.evaluate(`!!document.querySelector('[data-testid=media-report-banner]')`), false);
  }
  console.log("Report dismissal: success, running, error, unavailable and reload passed");
} finally {
  await b.evaluate(`localStorage.removeItem('test-report-status');localStorage.removeItem('active-media-report-id')`);
  await b.close();
}