/* OBTV AI — Premiere Pro UXP panel. Delivers Studio cuts into the open project.
 *
 * Flow: sign in (bearer token) -> pick a Studio project -> fetch the cut's
 * xmeml export (same exporter as the web app, incl. EXPORT_PATH_MAP hi-res
 * relinking and Curator source paths) -> write it to the plugin temp folder
 * -> import it into the active project -> best-effort Scale-to-Frame-Size on
 * the imported footage and a report of anything still offline.
 */
const ppro = require("premierepro");
const uxpfs = require("uxp").storage.localFileSystem;

const $ = (id) => document.getElementById(id);

const state = {
  server: localStorage.getItem("obtv_server") || "",
  token: localStorage.getItem("obtv_token") || "",
  user: localStorage.getItem("obtv_user") || "",
};

function setStatus(msg, cls) {
  const el = $("status");
  el.textContent = msg || "";
  el.className = cls || "";
}

async function api(method, path, body) {
  const base = state.server.replace(/\/+$/, "");
  const headers = { Accept: "application/json" };
  if (body != null) headers["Content-Type"] = "application/json";
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const res = await fetch(base + path, {
    method,
    headers,
    body: body != null ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON */ }
  if (!res.ok) throw new Error((data && data.detail) || text || `HTTP ${res.status}`);
  return data;
}

function showView() {
  const authed = !!state.token;
  $("login-view").className = authed ? "hidden" : "";
  $("main-view").className = authed ? "" : "hidden";
  if (authed) $("who").textContent = `${state.user} @ ${state.server}`;
}

function fail(e) {
  let msg = String((e && e.message) || e);
  if (/Not authenticated/i.test(msg)) {
    state.token = "";
    localStorage.removeItem("obtv_token");
    showView();
    msg = "Session expired — sign in again.";
  }
  setStatus(msg, "err");
}

async function loadProjects() {
  try {
    setStatus("Loading projects…");
    const projects = await api("GET", "/api/projects");
    const sel = $("project");
    sel.innerHTML = "";
    for (const p of projects || []) {
      const o = document.createElement("option");
      o.value = p.id;
      o.textContent = p.name;
      sel.appendChild(o);
    }
    setStatus(projects && projects.length ? "" : "No Studio projects found.");
  } catch (e) { fail(e); }
}

/* Write the XML to the plugin temp folder and return its native path. */
async function writeTempXml(filename, content) {
  const tmp = await uxpfs.getTemporaryFolder();
  const safe = (filename || "obtv_cut.xml").replace(/[^\w.-]+/g, "_");
  const file = await tmp.createFile(safe, { overwrite: true });
  await file.write(content);
  return file.nativePath;
}

/* Recursively collect non-sequence footage items under a project item. */
async function collectFootage(item, acc) {
  let children = [];
  try { children = await item.getItems(); } catch { return; }
  for (const child of children || []) {
    let isBin = false;
    try { isBin = (await child.getItems()) !== undefined && child.constructor?.name === "FolderItem"; } catch {}
    if (isBin) {
      await collectFootage(child, acc);
      continue;
    }
    let isSeq = false;
    try {
      if (typeof child.isSequence === "function") isSeq = await child.isSequence();
    } catch {}
    if (!isSeq) acc.push(child);
  }
}

async function deliver() {
  const projectId = $("project").value;
  if (!projectId) return setStatus("Pick a project first.", "err");
  const btn = $("btn-deliver");
  btn.disabled = true;
  try {
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error("No project open in Premiere.");

    setStatus("Exporting cut…");
    const out = await api("POST", `/api/projects/${projectId}/cut/export`, { format: "xmeml" });
    const xmlPath = await writeTempXml(out.filename, out.content);

    setStatus("Importing into Premiere…");
    const root = await project.getRootItem();
    // Bin named after the cut so we only touch what we bring in.
    const binName = (out.filename || "OBTV cut").replace(/\.xml$/i, "");
    let bin = null;
    try {
      const rootFolder = ppro.FolderItem.cast ? ppro.FolderItem.cast(root) : root;
      await project.executeTransaction((tx) => {
        tx.addAction(rootFolder.createBinAction(binName, true));
      });
      for (const it of await root.getItems()) {
        if (it.name === binName) { bin = it; break; }
      }
    } catch { /* fall back to importing at root */ }

    const ok = await project.importFiles([xmlPath], true, bin || undefined);
    if (!ok) throw new Error("Premiere refused the XML import.");

    // Post-import fix-ups: Scale-to-Frame-Size (the one thing FCP7 XML can't
    // express) and an offline count. Both best-effort — API surface varies
    // across Premiere versions.
    const items = [];
    await collectFootage(bin || root, items);
    let scaled = 0, offline = 0;
    for (const it of items) {
      try { if (await it.isOffline?.()) { offline++; continue; } } catch {}
      if ($("opt-scale").checked) {
        try {
          if (typeof it.setScaleToFrameSize === "function") { await it.setScaleToFrameSize(); scaled++; }
          else if (ppro.ProjectItemUtils?.setScaleToFrameSize) { await ppro.ProjectItemUtils.setScaleToFrameSize(it); scaled++; }
        } catch {}
      }
    }

    let msg = `Imported "${binName}": ${items.length} item(s)`;
    if (scaled) msg += `, scale-to-frame on ${scaled}`;
    if (offline) msg += `, ${offline} OFFLINE — check your media mounts`;
    setStatus(msg + ".", offline ? "err" : "ok");
  } catch (e) {
    fail(e);
  } finally {
    btn.disabled = false;
  }
}

$("btn-login").onclick = async () => {
  state.server = $("server").value.trim();
  if (state.server && !/^https?:\/\//i.test(state.server)) state.server = "http://" + state.server;
  const username = $("username").value.trim();
  const password = $("password").value;
  if (!state.server || !username || !password) return setStatus("Fill in all fields.", "err");
  try {
    setStatus("Signing in…");
    const u = await api("POST", "/api/auth/login", { username, password, return_token: true });
    state.token = u.token;
    state.user = u.username;
    localStorage.setItem("obtv_server", state.server);
    localStorage.setItem("obtv_token", state.token);
    localStorage.setItem("obtv_user", state.user);
    setStatus("");
    showView();
    loadProjects();
  } catch (e) {
    setStatus(String((e && e.message) || e), "err");
  }
};

$("btn-logout").onclick = () => {
  api("POST", "/api/auth/logout").catch(() => {});
  state.token = "";
  localStorage.removeItem("obtv_token");
  showView();
  setStatus("");
};

$("btn-refresh").onclick = loadProjects;
$("btn-deliver").onclick = deliver;

$("server").value = state.server;
showView();
if (state.token) loadProjects();
