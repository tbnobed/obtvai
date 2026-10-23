import assert from "node:assert/strict";
const base = process.env.EDITORIAL_TEST_URL || "http://localhost:8080/api";
const url = new URL(base);
assert(["localhost", "127.0.0.1"].includes(url.hostname) || url.hostname.endsWith(".replit.dev"), "Preview only");
async function login(username) {
  const r = await fetch(`${base}/auth/login`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username,password:"obtv"})});
  assert.equal(r.status,200);
  return r.headers.get("set-cookie").split(";")[0];
}
async function request(cookie, method, endpoint, body, expected=200) {
  const r=await fetch(base+endpoint,{method,headers:{cookie,"Content-Type":"application/json"},body:body===undefined?undefined:JSON.stringify(body)});
  assert.equal(r.status,expected,`${method} ${endpoint}: ${await r.clone().text()}`);
  return r.status===204?null:r.json();
}
const editor=await login("editor"), admin=await login("admin"),viewer=await login("viewer");
const fixture=await request(editor,"GET","/media/asset-001");
assert.equal(fixture.filename,"interview_sarah_chen.mp4","Not the mock preview; refusing mutation");
const original=(await request(editor,"GET","/editorial/state")).me;
const viewerOriginal=(await request(viewer,"GET","/editorial/state")).me;
const workspaces=[], collections=[];
const prefix=`QA-${Date.now()}`;
try {
  let w=await request(editor,"POST","/editorial/workspaces",{name:prefix,rules:{text:"interview_sarah"},media_ids:[]});
  workspaces.push(w.id);
  assert.deepEqual((await request(editor,"GET",`/editorial/scope?workspace_id=${w.id}`)).media_ids,["asset-001"]);
  assert.equal((await request(editor,"GET",`/media?workspace_id=${w.id}&limit=1`)).total,1);
  const empty=await request(editor,"POST","/editorial/workspaces",{name:prefix+" empty",rules:{},media_ids:[]});
  workspaces.push(empty.id);
  assert.deepEqual((await request(editor,"GET",`/editorial/scope?workspace_id=${empty.id}`)).media_ids,[]);
  assert.equal((await request(editor,"GET",`/media?workspace_id=${empty.id}`)).total,0);
  assert.deepEqual((await request(editor,"POST","/search",{query:"interview",workspace_id:empty.id})).results,[]);
  await request(editor,"PATCH",`/editorial/workspaces/${w.id}`,{name:prefix+" renamed"});
  await request(editor,"PATCH","/editorial/me",{workspace_id:w.id,workspace_ids:[w.id],favorite_media_ids:["asset-001"]});
  const newSession=await login("editor");
  assert.equal((await request(newSession,"GET","/editorial/state")).me.workspace_id,w.id);
  await request(editor,"POST","/editorial/recent",{media_id:"asset-001"},204);
  assert.equal((await request(editor,"GET","/editorial/state")).me.recent_media_ids[0],"asset-001");
  let c=await request(editor,"POST","/editorial/collections",{name:prefix+" private",workspace_id:w.id,visibility:"personal",kind:"manual",items:[{id:"item-1",media_id:"asset-001",start:1,end:5,note:"Opening"}]});
  collections.push(c.id);
  assert(!(await request(admin,"GET","/editorial/state")).collections.some(x=>x.id===c.id));
  await request(admin,"GET",`/editorial/scope?collection_id=${c.id}`,undefined,404);
  await request(admin,"PATCH",`/editorial/collections/${c.id}`,{name:"No"},404);
  c=await request(editor,"PATCH",`/editorial/collections/${c.id}`,{visibility:"team"});
  assert((await request(admin,"GET","/editorial/state")).collections.some(x=>x.id===c.id));
  await request(admin,"PATCH",`/editorial/collections/${c.id}`,{description:"Shared edit"});
  await request(editor,"PATCH",`/editorial/collections/${c.id}`,{items:[{id:"bad",media_id:"asset-001",start:5,end:2}]},422);
  await request(editor,"PATCH",`/editorial/collections/${c.id}`,{items:[]});
  assert.deepEqual((await request(editor,"GET",`/editorial/scope?collection_id=${c.id}`)).media_ids,[]);
  const smart=await request(editor,"POST","/editorial/collections",{name:prefix+" smart",workspace_id:w.id,kind:"smart",rules:{status:fixture.status},visibility:"team"});
  collections.push(smart.id);
  assert.deepEqual((await request(editor,"GET",`/editorial/scope?collection_id=${smart.id}`)).media_ids,["asset-001"]);
  await request(viewer,"POST","/editorial/workspaces",{name:"Forbidden"},403);
  await request(viewer,"PATCH","/editorial/me",{favorite_media_ids:["asset-001"]});
  await request(viewer,"POST","/editorial/recent",{media_id:"asset-001"},204);
  await request(editor,"DELETE",`/editorial/workspaces/${w.id}`,undefined,204);
  workspaces.splice(workspaces.indexOf(w.id),1);
  const after=await request(editor,"GET","/editorial/state");
  assert.equal(after.me.workspace_id,null);
  assert.equal(after.collections.find(x=>x.id===c.id).workspace_id,null);
  assert.equal((await request(editor,"GET","/media/asset-001")).id,"asset-001");
  console.log("PASS: persistent sessions, workspace CRUD, smart/manual scopes, empty-search isolation, private/team collections, timecode validation, favorites, recents, viewer permissions, non-destructive workspace deletion.");
} finally {
  for(const id of collections)await request(editor,"DELETE",`/editorial/collections/${id}`,undefined,204);
  for(const id of workspaces)await request(editor,"DELETE",`/editorial/workspaces/${id}`,undefined,204);
  for(const [cookie,me] of [[editor,original],[viewer,viewerOriginal]]) {
    const {recent_media_ids,...patch}=me;
    await request(cookie,"PATCH","/editorial/me",patch);
  }
}
