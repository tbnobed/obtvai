// Real Chromium checks against the development preview only. No auth bypass.
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const base="http://127.0.0.1:80";
const profile=await fs.mkdtemp(path.join(os.tmpdir(),"obtv-theme-browser-"));
const browser=spawn("chromium",["--headless","--no-sandbox","--disable-dev-shm-usage",
  "--remote-debugging-port=9229",`--user-data-dir=${profile}`,"about:blank"],{stdio:"ignore"});
let socket;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
try {
  let target;
  for(let i=0;i<100;i++){
    try {const r=await fetch("http://127.0.0.1:9229/json/new?about:blank",{method:"PUT"});target=await r.json();break;}catch{await delay(100);}
  }
  assert(target,"Chromium did not start");
  socket=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(resolve=>socket.addEventListener("open",resolve,{once:true}));
  let id=0;const pending=new Map(), errors=[];
  socket.addEventListener("message",event=>{
    const message=JSON.parse(event.data);
    if(message.id){const p=pending.get(message.id);pending.delete(message.id);
      if(message.error)p.reject(new Error(JSON.stringify(message.error)));else p.resolve(message.result);}
    if(message.method==="Runtime.exceptionThrown")errors.push(message.params.exceptionDetails.text+": "+(message.params.exceptionDetails.exception?.description??""));
  });
  const call=(method,params={})=>new Promise((resolve,reject)=>{
    const request=++id;pending.set(request,{resolve,reject});socket.send(JSON.stringify({id:request,method,params}));
  });
  const evaluate=async expression=>{
    const result=await call("Runtime.evaluate",{expression,awaitPromise:true,returnByValue:true});
    if(result.exceptionDetails)throw new Error(result.exceptionDetails.exception?.description??result.exceptionDetails.text);
    return result.result.value;
  };
  const click=async selector=>{
    const rect=await evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)})?.getBoundingClientRect();return r?{x:r.x+r.width/2,y:r.y+r.height/2}:null})()`);
    assert(rect,`Missing ${selector}`);
    await call("Input.dispatchMouseEvent",{type:"mousePressed",...rect,button:"left",clickCount:1});
    await call("Input.dispatchMouseEvent",{type:"mouseReleased",...rect,button:"left",clickCount:1});
    await delay(300);
  };
  const go=async route=>{
    await call("Page.navigate",{url:base+route});
    for(let i=0;i<100;i++){
      await delay(100);
      try {if(await evaluate(`document.readyState==="complete" && document.querySelector("#root")?.textContent.length>20`))break;}catch{}
    }
    await delay(500);
  };
  await call("Runtime.enable");await call("Page.enable");
  await call("Page.bringToFront");
  await call("Emulation.setDeviceMetricsOverride",{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await go("/");
  const storageKey=process.env.THEME_STORAGE_KEY||"obtv-theme";
  await evaluate(`localStorage.setItem(${JSON.stringify(storageKey)},"light")`);
  await go("/");
  assert.equal(await evaluate(`document.documentElement.classList.contains("light")`),true,"Light preference was not applied");
  await fs.writeFile("/tmp/obtv-login-light.png",Buffer.from((await call("Page.captureScreenshot",{format:"png"})).data,"base64"));
  // Credentials are the existing public mock fixtures, never production credentials.
  const login=await evaluate(`(async()=>{const fixture=await fetch("/api/healthz");if(!fixture.ok)throw Error("Preview unavailable");const r=await fetch("/api/auth/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:"admin",password:"obtv"})});return r.status;})()`);
  assert.equal(login,200,"Preview login failed");
  await go("/desk");
  await evaluate(`document.querySelector('[data-testid="button-theme-dark"]').click()`);
  await delay(150);
  assert.equal(await evaluate(`localStorage.getItem(${JSON.stringify(storageKey)})`),"dark","Theme button persistence");
  await evaluate(`document.querySelector('[data-testid="button-theme-light"]').click()`);
  await delay(150);
  assert(!(await evaluate(`!!document.querySelector('[data-testid="input-password"]')`)),"Still at login");
  const fixture=await evaluate(`fetch("/api/media/asset-001").then(r=>r.json()).then(a=>a.filename)`);
  assert.equal(fixture,"interview_sarah_chen.mp4","Not the mock development preview");
  const routes=["/","/desk","/desk/favorites","/desk/projects","/desk/collections","/library","/library/asset-001",
    "/studio","/people","/insights","/ratings","/socials","/jobs","/ai","/search","/training","/curator","/users","/audit","/campaigns","/nonexistent-theme-check"];
  const details=await evaluate(`(async()=>{const paths=[];for(const [endpoint,prefix] of [["projects","/studio/"],["people","/people/"],["campaigns","/campaigns/"]]){const r=await fetch("/api/"+endpoint);if(!r.ok)continue;const d=await r.json();const first=(Array.isArray(d)?d:d.items??d.projects??d.people??d.campaigns??[])[0];if(first?.id)paths.push(prefix+first.id);}return paths;})()`);
  routes.push(...details);
  const report=[];
  for(const route of routes){
    await go(route);
    const state=await evaluate(`({route:location.pathname,light:document.documentElement.classList.contains("light"),background:getComputedStyle(document.body).backgroundColor,color:getComputedStyle(document.body).color,text:document.body.innerText.slice(0,160),overflow:document.documentElement.scrollWidth>innerWidth+2})`);
    assert(state.light,`Lost light mode at ${route}`);
    assert(!["rgb(0, 0, 0)","rgb(9, 9, 11)"].includes(state.background),`Dark body at ${route}`);
    report.push(state);
    if(["/desk","/library","/ratings"].includes(route))await fs.writeFile(`/tmp/obtv-${route.slice(1)}-light.png`,Buffer.from((await call("Page.captureScreenshot",{format:"png"})).data,"base64"));
  }
  for(const [route,selector,name] of [
    ["/ratings",'[data-testid="button-import"]',"import-dialog"],
    ["/library",'[data-testid="button-library-filters"]',"filters-popover"],
  ]){
    await go(route);await click(selector);
    const dialog=await evaluate(`(()=>{const d=document.querySelector('[role="dialog"],[role="menu"]');return d?{bg:getComputedStyle(d).backgroundColor,text:d.innerText.slice(0,100)}:null})()`);
    assert(dialog,`Missing open ${name}`);
    assert(!["rgb(0, 0, 0)","rgb(14, 14, 17)"].includes(dialog.bg),`Dark ${name}`);
    await fs.writeFile(`/tmp/obtv-${name}-light.png`,Buffer.from((await call("Page.captureScreenshot",{format:"png"})).data,"base64"));
  }
  await go("/desk");
  await call("Emulation.setDeviceMetricsOverride",{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await delay(300);
  await fs.writeFile("/tmp/obtv-desk-light-mobile.png",Buffer.from((await call("Page.captureScreenshot",{format:"png"})).data,"base64"));
  assert.equal(await evaluate(`document.documentElement.scrollWidth<=innerWidth+2`),true,"Mobile desk overflow");
  await evaluate(`localStorage.setItem(${JSON.stringify(storageKey)},"dark")`);
  await go("/desk");
  assert.equal(await evaluate(`document.documentElement.classList.contains("dark")`),true,"Dark mode reload");
  await call("Emulation.setEmulatedMedia",{features:[{name:"prefers-color-scheme",value:"light"}]});
  await evaluate(`document.querySelector('[data-testid="button-theme-system"]').click()`);
  await delay(300);
  assert.equal(await evaluate(`document.documentElement.classList.contains("light")`),true,"System light mode");
  await call("Emulation.setEmulatedMedia",{features:[{name:"prefers-color-scheme",value:"dark"}]});
  for(let i=0;i<40;i++){
    if(await evaluate(`document.documentElement.classList.contains("dark")`))break;
    await delay(100);
  }
  const systemState=await evaluate(`({dark:document.documentElement.classList.contains("dark"),pref:localStorage.getItem(${JSON.stringify(storageKey)}),media:matchMedia("(prefers-color-scheme: dark)").matches,html:document.documentElement.className})`);
  assert.equal(systemState.dark,true,`System change tracking ${JSON.stringify(systemState)}`);
  assert.deepEqual(errors,[],"Browser runtime exceptions");
  await fs.writeFile("/tmp/obtv-theme-browser-report.json",JSON.stringify(report,null,2));
  console.log(`PASS ${routes.length} authenticated routes; light/dark persistence; system changes; mobile desk; no runtime exceptions`);
}finally{
  socket?.close();browser.kill("SIGTERM");
  await delay(300);await fs.rm(profile,{recursive:true,force:true});
}
