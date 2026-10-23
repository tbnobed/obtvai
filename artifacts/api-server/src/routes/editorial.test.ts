import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import express from "express";

// Isolate persistence and fixtures; never use the live preview's users or files.
const cwd = process.cwd(), temp = fs.mkdtempSync(path.join(os.tmpdir(), "desk-scale-"));
process.chdir(temp);
const { createEditorialRouter } = await import("./editorial");
const assets = Array.from({ length: 600 }, (_, i) => ({
  id: `asset-${i}`, filename: `Show ${String(i).padStart(4, "0")}.mp4`, status: "ready",
  curator_original_air_date: i % 2 ? "2025-01-01" : "2026-01-01", topics: ["Faith"],
}));
const projects = Array.from({ length: 600 }, (_, i) => ({ id: `p-${i}`, name: `Project ${String(i).padStart(4, "0")}` }));
const app = express();
app.use(express.json({limit:"2mb"}));
app.use((req, _res, next) => {
  Object.assign(req, {user:{id:req.headers["x-test-user"]??"editor",role:"user"}}); next();
});
app.use(createEditorialRouter(() => assets, () => projects));
app.use((err: any, _req: any, res: any, _next: any) => res.status(err.status??500).json({detail:err.message}));
const server = app.listen(0, "127.0.0.1");
await new Promise<void>(resolve => server.on("listening",resolve));
const address = server.address() as {port:number};
async function call(route:string, method="GET", body?:unknown, expected=200, user="editor"):Promise<any> {
  const response = await fetch(`http://127.0.0.1:${address.port}/editorial${route}`, {
    method, headers:{"Content-Type":"application/json","x-test-user":user},body:body===undefined?undefined:JSON.stringify(body),
  });
  const data=await response.json();assert.equal(response.status,expected,JSON.stringify(data));return data;
}
try {
  await call("/me","PATCH",{favorite_media_ids:assets.map(a=>a.id),saved_project_ids:projects.map(p=>p.id)});
  const first=await call("/desk?section=favorites&limit=50");
  assert.equal(first.total,600);assert.equal(first.items.length,50);assert.equal(first.items[0].id,"asset-599");
  const second=await call("/desk?section=favorites&offset=50&limit=50");
  assert.equal(second.items[0].id,"asset-549");
  assert.equal(new Set([...first.items,...second.items].map(i=>i.id)).size,100);
  assert.equal((await call("/desk?section=favorites&air_year=2026")).total,300);
  assert.equal((await call("/desk?section=favorites&q=Show%200001")).total,1);
  assert.equal((await call("/desk?section=favorites&topic=missing")).total,0);
  assert.equal((await call("/desk?section=favorites&sort=title&limit=1")).items[0].id,"asset-0");
  assert.equal((await call("/desk?section=projects&limit=25&offset=575")).items.length,25);
  assert.equal((await call("/desk?section=projects&q=Project%200599")).total,1);
  assert.equal((await call("/desk?section=favorites","GET",undefined,200,"another")).total,0);
  await call("/desk?section=favorites&limit=51","GET",undefined,422);
  const w=await call("/workspaces","POST",{name:"Scope",media_ids:["asset-1"],rules:{}});
  assert.equal((await call(`/desk?section=favorites&workspace_id=${w.id}`)).total,1);
  const selections=assets.slice(0,60).map(a=>({id:a.id,media_id:a.id}));
  let last:any;
  for(let i=0;i<61;i++)last=await call("/collections","POST",{
    name:`Collection ${String(i).padStart(3,"0")}`,visibility:i%2?"team":"personal",items:selections,workspace_id:w.id,
  });
  const collections=await call("/desk?section=collections&limit=25");
  assert.equal(collections.total,61);assert.equal(collections.items.length,25);
  assert(collections.items.every((c:any)=>!("items" in c)));
  assert(JSON.stringify(collections).length<12000);
  assert.equal((await call("/desk?section=collections&offset=50&limit=25")).items.length,11);
  assert.equal((await call("/desk?section=collections&visibility=personal")).total,31);
  assert.equal((await call("/desk?section=collections&visibility=team")).total,30);
  assert.equal((await call("/desk?section=collections","GET",undefined,200,"another")).total,30);
  await call(`/collections/${last.id}`,"GET",undefined,404,"another");
  assert.equal((await call("/state?include_collections=false")).collections.length,0);
  assert.equal((await call(`/collections/${last.id}`)).items.length,60);
  const appended=await call(`/collections/${last.id}/items`,"POST",{media_ids:["asset-0","asset-100"]});
  assert.equal(appended.items.length,61);
  await call("/favorites","POST",{ids:first.items.map((a:any)=>a.id),operation:"remove"});
  assert.equal((await call("/desk?section=favorites")).total,550);
  await call("/favorites","POST",{ids:["asset-599"],operation:"add"});
  assert.equal((await call("/desk?section=favorites&limit=1")).items[0].id,"asset-599");
  console.log("PASS: 600 favorites, 600 saved projects, 61 collections; pagination, filters, privacy, compact state, bulk actions");
} finally {
  server.closeAllConnections();
  await new Promise<void>(resolve=>server.close(()=>resolve()));
  process.chdir(cwd);
  fs.rmSync(temp,{recursive:true,force:true});
}
