// Integration test against the MOCK preview, not production. Actual Web Audio
// capture/encoding is exercised using a generated microphone signal; only the
// speech HTTP response is mocked. Start Chromium on port 9222 before running.
import assert from "node:assert/strict";
import { browser } from "./browser-cdp.mjs";

const b = await browser();
const start = "[data-testid=voice-start]";
const stop = "[data-testid=voice-stop]";
const cancel = "[data-testid=voice-cancel]";
const input = "[data-testid=input-search]";
const value = () => b.evaluate(`document.querySelector('${input}').value`);
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
try {
  await b.open("/search");
  assert.equal(await b.evaluate(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'obtv'})}).then(r=>r.status)`), 200);
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    window.voiceQA={calls:[],active:0,maxActive:0,stopped:0,mode:'ok',partial:'Hello',final:'Hello world.',sends:0};
    const realFetch=window.fetch.bind(window);
    window.fetch=async(url,options)=>{
      if(!String(url).includes('/speech/transcribe')){
        if(options?.method==='POST' && /\\/ai\\/ask|\\/search(?:\\?|$)/.test(String(url)))voiceQA.sends++;
        return realFetch(url,options);
      }
      const wav=await options.body.arrayBuffer(),view=new DataView(wav);
      const call={partial:new URL(url,location.href).searchParams.get('partial')==='true',bytes:wav.byteLength,rate:view.getUint32(24,true),header:String.fromCharCode(...new Uint8Array(wav,0,4))};
      voiceQA.calls.push(call);voiceQA.active++;voiceQA.maxActive=Math.max(voiceQA.active,voiceQA.maxActive);
      const answer=()=>{voiceQA.active--;return new Response(JSON.stringify({text:call.partial?voiceQA.partial:voiceQA.final,language:'en',duration_seconds:(wav.byteLength-44)/32000}),{status:200,headers:{'Content-Type':'application/json'}})};
      if(voiceQA.mode==='error'){voiceQA.active--;return new Response(JSON.stringify({detail:'Transcription unavailable'}),{status:503,headers:{'Content-Type':'application/json'}})}
      if(voiceQA.mode==='hold')return new Promise(r=>call.release=()=>r(answer()));
      return answer();
    };
    Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:async()=>{
      const context=new AudioContext(),oscillator=context.createOscillator(),gain=context.createGain(),destination=context.createMediaStreamDestination();
      oscillator.frequency.value=220;gain.gain.value=0.15;oscillator.connect(gain);gain.connect(destination);oscillator.start();await context.resume();
      for(const track of destination.stream.getTracks()){const original=track.stop.bind(track);track.stop=()=>{voiceQA.stopped++;original();oscillator.stop();void context.close()};}
      if(voiceQA.mode==='permission')return new Promise(r=>voiceQA.grant=()=>r(destination.stream));
      return destination.stream;
    }}});
  ` });
  await b.open("/search");
  await b.wait(`!!document.querySelector('${start}')`);
  // Existing controlled text is retained; interim and final REPLACE one region.
  await b.evaluate(`(()=>{const i=document.querySelector('${input}');i.focus();Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(i,'Find: ');i.dispatchEvent(new Event('input',{bubbles:true}));i.setSelectionRange(6,6)})()`);
  await b.click(start);
  await b.wait(`!!document.querySelector('${stop}') && document.querySelector('${input}').value==='Find: Hello'`);
  await b.evaluate("voiceQA.partial='Hello world'");
  await b.wait(`document.querySelector('${input}').value==='Find: Hello world'`);
  assert.ok(await b.evaluate(`!!document.querySelector('${stop}')`), "Text must appear before Stop");
  await b.click(stop);
  await b.wait(`!!document.querySelector('${start}')`);
  assert.equal(await value(), "Find: Hello world.");
  assert.equal(await b.evaluate("voiceQA.sends"), 0, "No search/AI auto-submit");
  assert.ok(await b.evaluate("voiceQA.calls.every(c=>c.header==='RIFF' && c.rate===16000 && c.bytes<=8*1024*1024)"));
  console.log("PASS live controlled text, final refinement, WAV format, no automatic submission");

  // Backpressure: do not queue every captured chunk behind a slow inference.
  await b.evaluate("voiceQA.calls=[];voiceQA.mode='hold';voiceQA.partial='Again';voiceQA.final='Again.'");
  await b.click(start);
  await b.wait("voiceQA.calls.length===1");
  await delay(4300);
  assert.equal(await b.evaluate("voiceQA.calls.length"), 1);
  await b.click(stop);
  await b.evaluate("voiceQA.calls[0].release()");
  await b.wait("voiceQA.calls.length===2");
  assert.equal(await b.evaluate("voiceQA.calls[1].partial"), false, "Stop prioritizes final, not stale partials");
  await b.evaluate("voiceQA.calls[1].release()");
  await b.wait(`!!document.querySelector('${start}')`);
  assert.equal(await b.evaluate("voiceQA.maxActive"), 1);
  assert.equal(await value(), "Find: Hello world. Again.");
  console.log("PASS repeated dictation, one-in-flight backpressure, final flush");

  // A response arriving after Cancel may not insert text.
  const baseline = await value();
  await b.evaluate("voiceQA.calls=[]");
  await b.click(start);
  await b.wait("voiceQA.calls.length===1");
  await b.click(cancel);
  await b.evaluate("voiceQA.calls[0].release()");
  await delay(150);
  assert.equal(await value(), baseline);
  console.log("PASS late result ignored after cancellation");

  // Direct typing takes ownership; live updates must not overwrite the edit.
  await b.evaluate("voiceQA.mode='ok';voiceQA.partial='Editable'");
  await b.click(start);
  await b.wait(`document.querySelector('${input}').value.includes('Editable')`);
  await b.evaluate(`(()=>{const i=document.querySelector('${input}');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(i,'User correction');i.dispatchEvent(new Event('input',{bubbles:true}))})()`);
  await b.wait(`!!document.querySelector('${start}')`);
  assert.equal(await value(), "User correction");
  console.log("PASS manual edits preserve user text and stop dictation");

  await b.evaluate("voiceQA.partial='Cancel this phrase'");
  await b.click(start);
  await b.wait(`document.querySelector('${input}').value.includes('Cancel this phrase')`);
  await b.click(cancel);
  assert.equal(await value(), "User correction");
  console.log("PASS explicit Cancel restores text before dictation");

  await b.evaluate("voiceQA.partial='Keep these words'");
  await b.click(start);
  await b.wait(`document.querySelector('${input}').value.includes('Keep these words')`);
  const beforeError = await value();
  await b.evaluate("voiceQA.mode='error'");
  await b.click(stop);
  await b.wait(`!!document.querySelector('${start}')`);
  assert.equal(await value(), beforeError);
  console.log("PASS service failure retains already recognized text");

  // Permission arriving after Cancel still closes its returned microphone.
  await b.evaluate("voiceQA.mode='permission';voiceQA.grant=null");
  await b.click(start);
  await b.wait("!!voiceQA.grant");
  const stopped = await b.evaluate("voiceQA.stopped");
  await b.click(cancel);
  await b.evaluate("voiceQA.grant()");
  await b.wait(`voiceQA.stopped>${stopped}`);
  assert.equal(await value(), beforeError);
  console.log("PASS cancellation while permission is pending");

  // Navigating away while permission is pending must clean up its late stream.
  await b.evaluate("voiceQA.grant=null");
  await b.click(start);
  await b.wait("!!voiceQA.grant");
  const beforeUnmount = await b.evaluate("voiceQA.stopped");
  await b.evaluate("document.querySelector('a[href=\"/ai\"]').click()");
  await b.wait("location.pathname==='/ai'");
  await b.evaluate("voiceQA.grant()");
  await b.wait(`voiceQA.stopped>${beforeUnmount}`);
  console.log("PASS navigation cleans up late microphone permission");

  // Live controls remain outside the text area at mobile widths.
  await b.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await b.evaluate("voiceQA.mode='ok';voiceQA.partial='Show interviews about community projects';voiceQA.final=voiceQA.partial");
  await b.click(start);
  await b.wait("!![...document.querySelectorAll('input')].find(i=>i.value.includes('Show interviews'))");
  assert.equal(await b.evaluate("document.documentElement.scrollWidth"), 390);
  assert.ok(await b.evaluate(`(()=>{const i=[...document.querySelectorAll('input')].find(i=>i.value.includes('Show interviews')),button=document.querySelector('${stop}');return button.getBoundingClientRect().top>=i.getBoundingClientRect().bottom})()`));
  const { data } = await b.send("Page.captureScreenshot", { format: "png" });
  const { writeFile } = await import("node:fs/promises");
  await writeFile("/tmp/live-voice-mobile.png", Buffer.from(data, "base64"));
  await b.click(stop);
  await b.wait(`!!document.querySelector('${start}')`);
  assert.equal(await b.evaluate("voiceQA.sends"), 0);
  console.log("PASS mobile live-text layout and AI prompt without auto-send");
} finally {
  await b.close();
}