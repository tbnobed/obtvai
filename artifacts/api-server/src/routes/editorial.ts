/** Persistent preview organization. Production uses PostgreSQL via FastAPI. */
import { Router, type Request } from "express";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

type Asset = {id:string; filename:string; thumbnail_url?:string|null; original_path?:string|null; curator_folder_path?:string|null;
  curator_original_air_date?:string|null; status:string; topics?:string[]|null; duration_seconds?:number|null};
type Rules = {text?:string|null; air_year?:number|null; status?:string|null; media_type?:string|null; topic?:string|null};
type Item = {id:string;media_id:string;start:number|null;end:number|null;note:string};
type RecordData = {id:string; name:string; description:string; rules:Rules; created_by:string|null; updated_at?:string;
  media_ids?:string[]; workspace_id?:string|null;kind?:"manual"|"smart";visibility?:"personal"|"team";items?:Item[]};
type Me = {workspace_id:string|null;workspace_ids:string[];favorite_media_ids:string[];saved_project_ids:string[];recent_media_ids:string[]};
type State = {workspaces:RecordData[];collections:RecordData[];desks:Record<string,Me>};
const storage = path.resolve(process.cwd(), ".local/editorial-preview.json");
const emptyMe = ():Me => ({workspace_id:null,workspace_ids:[],favorite_media_ids:[],saved_project_ids:[],recent_media_ids:[]});
const initial:State = {workspaces:["Praise","Stakelbeck"].map(name=>({
  id:name.toLowerCase(),name,description:"Shared editorial workspace",rules:{text:name},media_ids:[],created_by:null,
})),collections:[],desks:{}};
let state:State = fs.existsSync(storage) ? JSON.parse(fs.readFileSync(storage,"utf8")) : initial;
function persist(next:State) {
  fs.mkdirSync(path.dirname(storage),{recursive:true});
  fs.writeFileSync(storage+".tmp",JSON.stringify(next));
  fs.renameSync(storage+".tmp",storage);
  state=next;
}
function actor(req:Request) {return (req as Request & {user:{id:string;role:string}}).user;}
function visible(r:RecordData, uid:string) {return r.visibility==="team" || r.created_by===uid;}
function fault(status:number, detail:string):never {throw Object.assign(new Error(detail),{status,detail});}
function workspace(id:string) {const r=state.workspaces.find(r=>r.id===id);if(!r)fault(404,"Workspace not found");return r;}
function collection(id:string,uid:string) {const r=state.collections.find(r=>r.id===id&&visible(r,uid));if(!r)fault(404,"Collection not found");return r;}
function matches(a:Asset,r:Rules,empty:boolean) {
  const active=Object.values(r).some(v=>v!=null&&v!==""&&v!=="all");
  if(!active)return empty;
  if(r.text && ![a.filename,a.original_path,a.curator_folder_path].some(s=>s?.toLowerCase().includes(r.text!.trim().toLowerCase())))return false;
  if(r.air_year && (!a.curator_original_air_date || new Date(a.curator_original_air_date).getUTCFullYear()!==r.air_year))return false;
  if(r.status && a.status!==r.status)return false;
  if(r.topic && !a.topics?.includes(r.topic))return false;
  const image=/\.(jpg|jpeg|png|gif|webp|bmp|tif|tiff|heic|heif|avif|svg|exr|dpx)$/i.test(a.filename);
  if(r.media_type==="images"&&!image || r.media_type==="hide_images"&&image)return false;
  return true;
}
export function resolveEditorialScope(req:Request, assets:Asset[], params:Record<string,unknown>) {
  const wid=typeof params.workspace_id==="string"?params.workspace_id:null;
  const cid=typeof params.collection_id==="string"?params.collection_id:null;
  let w=wid?workspace(wid):null;
  const c=cid?collection(cid,actor(req).id):null;
  if(c?.workspace_id) {
    if(w && w.id!==c.workspace_id)fault(422,"Collection belongs to a different workspace");
    w=workspace(c.workspace_id);
  }
  if(!w&&!c)return {media_ids:null as string[]|null,items:[] as Item[]};
  if(c?.kind==="manual") {
    const items=(c.items??[]).filter(i=>assets.some(a=>a.id===i.media_id));
    return {media_ids:[...new Set(items.map(i=>i.media_id))],items};
  }
  return {media_ids:assets.filter(a=>(!w||w.media_ids?.includes(a.id)||matches(a,w.rules,false))&&(!c||matches(a,c.rules,true))).map(a=>a.id),items:[] as Item[]};
}
const strings=(value:unknown,max:number):string[]=>{
  if(!Array.isArray(value)||value.length>max||value.some(v=>typeof v!=="string"||!v))fault(422,"Invalid ID list");
  return [...new Set(value as string[])];
};
function validateRules(value:unknown):Rules {
  if(!value||typeof value!=="object"||Array.isArray(value))fault(422,"Invalid smart rules");
  const r=value as Rules;
  if(Object.keys(r).some(k=>!["text","air_year","status","media_type","topic"].includes(k)))fault(422,"Unknown rule");
  for(const k of ["text","status","topic"] as const)if(r[k]!=null&&(typeof r[k]!=="string"||r[k]!.length>200))fault(422,"Invalid rule text");
  if(r.air_year!=null&&(!Number.isInteger(r.air_year)||r.air_year<1900||r.air_year>2200))fault(422,"Invalid original air year");
  if(r.media_type!=null&&!["all","hide_images","images"].includes(r.media_type))fault(422,"Invalid media type");
  return r;
}
export function createEditorialRouter(assets:()=>Asset[],projects:()=>{id:string;name?:string}[]) {
  const r=Router();
  const validAssets=(ids:string[])=>{if(ids.some(id=>!assets().some(a=>a.id===id)))fault(422,"Asset no longer exists");};
  r.get("/editorial/desk",(req,res)=>{
    const {id:uid}=actor(req), params=req.query;
    const section=String(params.section??"");
    if(!["favorites","projects","collections","recent"].includes(section))fault(422,"Invalid section");
    const offset=Number(params.offset??0),limit=Number(params.limit??50),year=params.air_year?Number(params.air_year):undefined;
    if(!Number.isInteger(offset)||offset<0||!Number.isInteger(limit)||limit<1||limit>50)fault(422,"Invalid page");
    if(year!==undefined&&(!Number.isInteger(year)||year<1900||year>2200))fault(422,"Invalid original air year");
    const sort=String(params.sort??"recent"), visibility=String(params.visibility??"all");
    if(!["recent","title","air_date"].includes(sort)||!["all","personal","team"].includes(visibility))fault(422,"Invalid sort or visibility");
    const q=String(params.q??"").trim().toLowerCase(), wid=String(params.workspace_id??"");
    if(q.length>200||String(params.topic??"").length>200)fault(422,"Filter too long");
    const w=wid?workspace(wid):null;
    const me=state.desks[uid]??emptyMe();
    type Row={id:string;title:string;air_date?:string|null; updated_at?:string; description?:string};
    let rows:Row[];
    if(section==="collections") {
      rows=state.collections.filter(c=>visible(c,uid)&&(!wid||c.workspace_id===wid)&&
        (visibility==="all"||c.visibility===visibility&&(visibility!=="personal"||c.created_by===uid)))
        .map(c=>({id:c.id,title:c.name,description:c.description,updated_at:c.updated_at,workspace_id:c.workspace_id,
          visibility:c.visibility,kind:c.kind,created_by:c.created_by}));
      if(sort==="recent")rows.sort((a,b)=>(b.updated_at??"").localeCompare(a.updated_at??"")||a.id.localeCompare(b.id));
    } else {
      const ids=section==="recent"?me.recent_media_ids:[...(section==="projects"?me.saved_project_ids:me.favorite_media_ids)].reverse();
      if(section==="projects") {
        const byId=new Map(projects().map(p=>[p.id,p]));
        rows=ids.flatMap(id=>{const p=byId.get(id);return p?[{id,title:p.name??id}]:[];});
      } else {
        const byId=new Map(assets().map(a=>[a.id,a]));
        rows=ids.flatMap(id=>{
          const a=byId.get(id);
          if(!a||w&&!w.media_ids?.includes(id)&&!matches(a,w.rules,false)||
            !matches(a,{air_year:year,topic:params.topic?String(params.topic):undefined},true))return [];
          return [{id,title:a.filename,thumbnail_url:a.thumbnail_url,duration_seconds:a.duration_seconds,air_date:a.curator_original_air_date}];
        });
      }
    }
    rows=rows.filter(r=>r.title.toLowerCase().includes(q)||(r.description??"").toLowerCase().includes(q));
    if(sort==="title")rows.sort((a,b)=>a.title.toLowerCase().localeCompare(b.title.toLowerCase())||a.id.localeCompare(b.id));
    if(sort==="air_date"&&section!=="projects"&&section!=="collections")rows.sort((a,b)=>(b.air_date??"").localeCompare(a.air_date??"")||a.id.localeCompare(b.id));
    res.json({items:rows.slice(offset,offset+limit).map(({updated_at,description,...r})=>r),total:rows.length,offset,limit});
  });
  r.post("/editorial/favorites",(req,res)=>{
    const uid=actor(req).id,ids=strings(req.body.ids,2000),op=req.body.operation;
    if(!["add","remove"].includes(op))fault(422,"Invalid operation");
    if(op==="add")validAssets(ids);
    const next=structuredClone(state), me=next.desks[uid]??emptyMe();
    me.favorite_media_ids=me.favorite_media_ids.filter(id=>!ids.includes(id));
    if(op==="add")me.favorite_media_ids.push(...ids);
    if(me.favorite_media_ids.length>2000)fault(422,"Maximum 2,000 favorites per account");
    next.desks[uid]=me;persist(next);res.json(me);
  });
  r.post("/editorial/collections/:id/items",(req,res)=>{
    const user=actor(req);if(user.role==="viewer")fault(403,"View-only account");
    const old=collection(String(req.params.id),user.id);
    if(old.kind!=="manual")fault(422,"Add selections to a manual collection");
    const ids=strings(req.body.media_ids,2000);validAssets(ids);
    const items=[...(old.items??[])],whole=new Set(items.filter(i=>i.start===null).map(i=>i.media_id));
    items.push(...ids.filter(id=>!whole.has(id)).map(media_id=>({id:crypto.randomUUID(),media_id,start:null,end:null,note:""})));
    if(items.length>2000)fault(422,"Maximum 2,000 selections per collection");
    const value={...old,items,updated_at:new Date().toISOString()},next=structuredClone(state);
    next.collections=next.collections.map(c=>c.id===old.id?value:c);persist(next);res.json(value);
  });
  r.get("/editorial/state",(req,res)=>{
    const uid=actor(req).id;
    res.json({workspaces:state.workspaces,collections:req.query.include_collections==="false"?[]:state.collections.filter(c=>visible(c,uid)),me:state.desks[uid]??emptyMe()});
  });
  r.get("/editorial/collections/:id",(req,res)=>res.json(collection(String(req.params.id),actor(req).id)));
  r.get("/editorial/me",(req,res)=>res.json(state.desks[actor(req).id]??emptyMe()));
  r.patch("/editorial/me",(req,res)=>{
    const uid=actor(req).id;const next=structuredClone(state);const me=next.desks[uid]??emptyMe();
    if(Object.keys(req.body).some(k=>!["workspace_id","workspace_ids","favorite_media_ids","saved_project_ids"].includes(k)))fault(422,"Unknown preference");
    if("workspace_id" in req.body) {if(req.body.workspace_id!==null)workspace(req.body.workspace_id);me.workspace_id=req.body.workspace_id;}
    for(const key of ["workspace_ids","favorite_media_ids","saved_project_ids"] as const) {
      if(!(key in req.body))continue;
      const ids=strings(req.body[key],key==="workspace_ids"?200:2000);
      if(key==="workspace_ids")ids.forEach(workspace);
      if(key==="favorite_media_ids")validAssets(ids);
      if(key==="saved_project_ids"&&ids.some(id=>!projects().some(p=>p.id===id)))fault(422,"Project no longer exists");
      me[key]=ids;
    }
    next.desks[uid]=me;persist(next);res.json(me);
  });
  r.post("/editorial/recent",(req,res)=>{
    validAssets(strings([req.body.media_id],1));
    const uid=actor(req).id;const next=structuredClone(state);const me=next.desks[uid]??emptyMe();
    me.recent_media_ids=[req.body.media_id,...me.recent_media_ids.filter(id=>id!==req.body.media_id)].slice(0,30);
    next.desks[uid]=me;persist(next);res.sendStatus(204);
  });
  r.get("/editorial/scope",(req,res)=>res.json(resolveEditorialScope(req,assets(),req.query)));
  for(const type of ["workspaces","collections"] as const) {
    const save=(req:Request,edit:boolean)=>{
      const user=actor(req);if(user.role==="viewer")fault(403,"View-only account");
      const id=String(req.params.id??"");
      const old=edit?(type==="workspaces"?workspace(id):collection(id,user.id)):null;
      const allowed=type==="workspaces"?["name","description","rules","media_ids"]:["name","description","rules","workspace_id","kind","visibility","items"];
      if(Object.keys(req.body).some(k=>!allowed.includes(k)))fault(422,"Unknown field");
      const value:RecordData={id:crypto.randomUUID(),created_by:user.id,name:"",description:"",rules:{},
        ...(type==="workspaces"?{media_ids:[]}:{workspace_id:null,kind:"manual",visibility:"personal",items:[]}),
        ...old,...req.body};
      if(typeof value.name!=="string"||!value.name.trim()||value.name.length>120)fault(422,"Name is required (maximum 120 characters)");
      value.name=value.name.trim();
      value.updated_at=new Date().toISOString();
      if(typeof value.description!=="string"||value.description.length>2000)fault(422,"Invalid description");
      value.rules=validateRules(value.rules);
      if(type==="workspaces"){value.media_ids=strings(value.media_ids,20000);validAssets(value.media_ids);}
      else {
        if(!["manual","smart"].includes(value.kind??"")||!["personal","team"].includes(value.visibility??""))fault(422,"Invalid collection kind or visibility");
        if(value.workspace_id)workspace(value.workspace_id);
        if(old&&old.visibility!==value.visibility&&old.created_by!==user.id)fault(403,"Only the creator can change visibility");
        if(!Array.isArray(value.items)||value.items.length>2000)fault(422,"Invalid selections");
        const seen=new Set<string>();
        value.items=value.items.map(i=>{
          if(!i||typeof i.id!=="string"||!i.id||seen.has(i.id)||typeof i.media_id!=="string")fault(422,"Invalid or duplicate selection");
          seen.add(i.id);validAssets([i.media_id]);
          const start=i.start??null,end=i.end??null;
          if((start===null)!==(end===null)||start!==null&&(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end!<=start))fault(422,"Invalid timecode range");
          const duration=assets().find(a=>a.id===i.media_id)?.duration_seconds;
          if(end!=null&&duration!=null&&end>duration)fault(422,"Selection exceeds asset duration");
          if(i.note!=null&&(typeof i.note!=="string"||i.note.length>2000))fault(422,"Invalid note");
          return {id:i.id,media_id:i.media_id,start,end,note:i.note??""};
        });
      }
      const next=structuredClone(state);
      next[type]=old?next[type].map(r=>r.id===old.id?value:r):[...next[type],value];
      persist(next);return value;
    };
    r.post(`/editorial/${type}`,(req,res)=>res.json(save(req,false)));
    r.patch(`/editorial/${type}/:id`,(req,res)=>res.json(save(req,true)));
    r.delete(`/editorial/${type}/:id`,(req,res)=>{
      const user=actor(req);const id=String(req.params.id);
      const old=type==="workspaces"?workspace(id):collection(id,user.id);
      if(user.role==="viewer"||old.created_by!==user.id&&user.role!=="admin")fault(403,"Only the creator or administrator can delete");
      const next=structuredClone(state);next[type]=next[type].filter(r=>r.id!==id);
      if(type==="workspaces") {
        next.collections.forEach(c=>{if(c.workspace_id===id)c.workspace_id=null;});
        Object.values(next.desks).forEach(d=>{if(d.workspace_id===id)d.workspace_id=null;d.workspace_ids=d.workspace_ids.filter(x=>x!==id);});
      }
      persist(next);res.sendStatus(204);
    });
  }
  return r;
}
