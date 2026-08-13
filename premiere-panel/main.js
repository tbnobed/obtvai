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

const _DONOR_NAME = "OBTV HOUSE";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* If the donor sequence is missing, create it from the .sqpreset shipped in
   the plugin's presets/ folder. Returns the new Sequence or null. */
async function createDonorFromBundledPreset(project) {
  try {
    const fs = require("uxp").storage.localFileSystem;
    const pluginFolder = await fs.getPluginFolder();
    const presetsFolder = await pluginFolder.getEntry("presets");
    const entries = await presetsFolder.getEntries();
    const preset = entries.find((e) => /\.sqpreset$/i.test(e.name));
    if (!preset || !preset.nativePath) return null;
    let seq = null;
    if (typeof project.createSequenceWithPresetPath === "function") {
      seq = await project.createSequenceWithPresetPath(_DONOR_NAME, preset.nativePath);
    } else if (typeof project.createSequence === "function") {
      seq = await project.createSequence(_DONOR_NAME, preset.nativePath);
    }
    return seq || null;
  } catch {
    return null; // no presets folder / no preset bundled — fall back to manual
  }
}

/* Debug log: collected in memory, echoed to the UDT console, and written to
   a file the user can open. */
const DBG = [];
function dbg(...args) {
  const line = args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" ");
  DBG.push(line);
  try { console.log("[OBTV]", line); } catch {}
}
async function flushDebug() {
  try {
    const fs = require("uxp").storage.localFileSystem;
    const folder = await fs.getTemporaryFolder();
    const f = await folder.createEntry("obtv-debug.log", { overwrite: true });
    await f.write(DBG.join("\n"));
    return f.nativePath;
  } catch (e) { return "(could not write log: " + String((e && e.message) || e) + ")"; }
}

async function deliver() {
  const projectId = $("project").value;
  if (!projectId) return setStatus("Pick a project first.", "err");
  const btn = $("btn-deliver");
  btn.disabled = true;
  let step = "start";
  try {
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error("No project open in Premiere.");

    setStatus("Exporting cut…");
    step = "export";
    const out = await api("POST", `/api/projects/${projectId}/cut/export`, { format: "xmeml" });
    step = "writeTempXml";
    const xmlPath = await writeTempXml(out.filename, out.content);

    setStatus("Importing into Premiere…");
    // Snapshot sequences so we can spot the one the import creates.
    let seqIdsBefore = new Set();
    try {
      for (const s of (await project.getSequences()) || []) seqIdsBefore.add(String(s.guid || s.id || s.name));
    } catch {}
    step = "getRootItem";
    const root = await project.getRootItem();
    // Bin named after the cut so we only touch what we bring in.
    const binName = (out.filename || "OBTV cut").replace(/\.xml$/i, "");
    let bin = null;
    try {
      step = "createBin";
      await project.executeTransaction((tx) => {
        tx.addAction(root.createBinAction(binName, true));
      });
      for (const it of await root.getItems()) {
        if (it.name === binName) { bin = it; break; }
      }
    } catch { bin = null; /* fall back to importing at root */ }

    // NOTE: a two-phase import (pre-import media, flag scale-to-frame, then
    // import the XML) was tried and reverted: importFiles on omdci URLs
    // double-ingests the media and crashes Premiere, and this build throws
    // "The script object is no longer valid" from createSetScaleToFrameSizeAction
    // even on freshly imported masters. Scaling correctness comes from the
    // export declaring the proxy's TRUE raster + Default Media Scaling.
    const wantScale = $("opt-scale").checked;

    // UXP's native bindings are strict about parameter types — pass every
    // argument explicitly (no undefined) and always a real FolderItem target.
    step = "importFiles";
    let ok = false;
    try {
      ok = await project.importFiles([xmlPath], true, bin || root, false);
    } catch (e1) {
      // Older builds take (paths, suppressUI, targetBin) or just (paths).
      try { ok = await project.importFiles([xmlPath], true, bin || root); }
      catch (e2) { ok = await project.importFiles([xmlPath]); }
    }
    if (!ok) throw new Error("Premiere refused the XML import.");
    step = "post-import";

    // Scale-to-Frame-Size: the native flag on the ClipProjectItem. This is the
    // ONLY correct mechanism — never bake a Motion > Scale %.
    // Held ProjectItem handles go invalid ("script object is no longer valid")
    // when the just-finished import settles in the background. So: wait for it
    // to settle, then re-fetch items fresh on every pass and retry stale ones.
    step = "scale-project-items";
    let scaled = 0, offline = 0, scaleErr = "", total = 0;
    {
      const snap = [];
      await collectFootage(bin || root, snap);
      total = snap.length;
    }
    dbg("wantScale=" + wantScale, "footage items=" + total);
    // Best-effort: flag the imported project items scale-to-frame. NOTE this
    // only affects clips added to a sequence AFTER the flag is set — it does
    // NOT retro-scale the clips the XML import already placed. The reliable
    // way to make placed clips fill the frame is Premiere's Preferences >
    // Media > "Default Media Scaling: Scale to Frame Size", which scales clips
    // as they're added to the sequence during import. We surface that hint.
    if (wantScale && total) {
      await sleep(900); // let the import settle
      const fresh = [];
      await collectFootage(bin || root, fresh);
      for (let idx = 0; idx < fresh.length; idx++) {
        const raw = fresh[idx];
        let clip = raw;
        try { if (ppro.ClipProjectItem?.cast) clip = ppro.ClipProjectItem.cast(raw) || raw; } catch {}
        const targets = raw === clip ? [raw] : [raw, clip];
        for (const t of targets) {
          if (typeof t.createSetScaleToFrameSizeAction !== "function") continue;
          try {
            await project.executeTransaction((tx) => {
              tx.addAction(t.createSetScaleToFrameSizeAction());
            }, "OBTV scale to frame");
            scaled++; break;
          } catch (e) { scaleErr = String(e && e.message || e); }
        }
      }
    }
    let scaleMsg = "";

    // Sequence settings can NOT be set via FCP7 XML — Premiere ignores the
    // format block for editing mode/previews. Instead we clone the full
    // settings from a donor sequence named "OBTV HOUSE" (create it once from
    // the house preset and keep it in the project template).
    let settingsMsg = "";
    let importedSeqs = [];
    try {
      const sequences = (await project.getSequences()) || [];
      let donor = sequences.find((s) => /^obtv house$/i.test(String(s.name || "").trim()));
      const imported = sequences.filter((s) => !seqIdsBefore.has(String(s.guid || s.id || s.name)));
      importedSeqs = imported;
      if (!donor) {
        // Auto-create the donor from the .sqpreset bundled with the plugin.
        donor = await createDonorFromBundledPreset(project);
      }
      if (!donor) {
        settingsMsg = ' No "OBTV HOUSE" sequence and no bundled presets/OBTV HOUSE.sqpreset — sequence settings NOT applied. Add the preset to the plugin or create the sequence manually (AVC-Intra 100 1080i / 29.97).';
      } else if (imported.length) {
        const donorSettings = await donor.getSettings();
        let applied = 0;
        let lastErr = "";
        for (const seq of imported) {
          try {
            const run = () => project.executeTransaction((tx) => {
              tx.addAction(seq.createSetSettingsAction(donorSettings));
            }, "OBTV house settings");
            try {
              await run();
            } catch (e1) {
              // Some builds require sequence mutations inside lockedAccess.
              if (typeof project.lockedAccess === "function") {
                await project.lockedAccess(() => run());
              } else {
                throw e1;
              }
            }
            applied++;
          } catch (eSet) {
            lastErr = String((eSet && eSet.message) || eSet);
          }
        }
        settingsMsg = applied
          ? ` House settings applied to ${applied} sequence(s).`
          : ` Could not apply house settings: ${lastErr || "unknown error"} — check the sequence manually.`;
      }
    } catch (eSeq) {
      settingsMsg = " Sequence settings step failed: " + String((eSeq && eSeq.message) || eSeq);
    }

    // Retro-scale the PLACED clips so the editor never touches them manually.
    // The master-clip flag is not retroactive and the Default Media Scaling
    // pref is unreliable, so per placed clip: flag its backing master, pin the
    // master's in/out to the placed range, remove the placed video item
    // (no ripple), overwrite the same master back at the same spot — the
    // re-inserted clip inherits scale-to-frame — then clear the master in/out.
    step = "rescale-placed-clips";
    let rescaled = 0, rescaleFail = 0;
    if (wantScale && importedSeqs.length && ppro.SequenceEditor) {
      const C = ppro.Constants || {};
      const TI_CLIP = (C.TrackItemType && (C.TrackItemType.CLIP ?? C.TrackItemType.Clip)) ?? 1;
      const MT_VIDEO = C.MediaType && (C.MediaType.VIDEO ?? C.MediaType.Video);
      for (const seq of importedSeqs) {
        try {
          const editor = await ppro.SequenceEditor.getEditor(seq);
          const vCount = await seq.getVideoTrackCount();
          for (let v = 0; v < vCount; v++) {
            const track = await seq.getVideoTrack(v);
            const items = (await track.getTrackItems(TI_CLIP, false)) || [];
            for (const ti of items) {
              try {
                const start = await ti.getStartTime();
                const inP = await ti.getInPoint();
                const outP = await ti.getOutPoint();
                const pi = await ti.getProjectItem();
                let clip = pi;
                try { if (ppro.ClipProjectItem?.cast) clip = ppro.ClipProjectItem.cast(pi) || pi; } catch {}
                if (typeof clip.createSetScaleToFrameSizeAction !== "function") { rescaleFail++; continue; }
                // 1) flag the master + pin in/out to the placed range
                await project.executeTransaction((tx) => {
                  tx.addAction(clip.createSetScaleToFrameSizeAction());
                  tx.addAction(clip.createSetInOutPointsAction(inP, outP));
                }, "OBTV scale flag");
                // 2) remove the placed video item (leave linked audio, no ripple)
                const sel = await seq.getSelection();
                try {
                  const cur = (await sel.getTrackItems()) || [];
                  for (const c of cur) { try { sel.removeItem(c); } catch {} }
                } catch {}
                sel.addItem(ti, false);
                await project.executeTransaction((tx) => {
                  tx.addAction(editor.createRemoveItemsAction(sel, false, MT_VIDEO, false));
                }, "OBTV rescale remove");
                // 3) re-place the same master at the same spot (inherits flag)
                await project.executeTransaction((tx) => {
                  tx.addAction(editor.createOverwriteItemAction(pi, start, v, 0));
                }, "OBTV rescale place");
                // 4) restore the master's in/out
                try {
                  await project.executeTransaction((tx) => {
                    tx.addAction(clip.createClearInOutPointsAction());
                  }, "OBTV rescale clear io");
                } catch {}
                rescaled++;
              } catch (eTi) {
                rescaleFail++;
                dbg("rescale item failed:", String((eTi && eTi.message) || eTi));
              }
            }
          }
        } catch (eS) {
          dbg("rescale sequence failed:", String((eS && eS.message) || eS));
        }
      }
      dbg("rescale placed clips: ok=" + rescaled + " failed=" + rescaleFail);
      if (rescaled) scaleMsg = ` ${rescaled} placed clip(s) scaled to frame.`;
      if (rescaleFail) scaleMsg += ` ${rescaleFail} clip(s) could NOT be auto-scaled — right-click them > Scale to Frame Size.`;
    }

    const dbgPath = await flushDebug();

    let msg = `Imported "${binName}": ${total} item(s)`;
    if (scaled) msg += `, scale-to-frame set on ${scaled}`;
    if (offline) msg += `, ${offline} OFFLINE — check your media mounts`;
    const bad = offline || /NOT applied|refused|failed|NOT set/.test(settingsMsg + scaleMsg);
    dbg("SUMMARY:", msg + scaleMsg + settingsMsg);
    dbg("debug log:", dbgPath);
    await flushDebug();
    setStatus(msg + "." + scaleMsg + settingsMsg + " Debug log: " + dbgPath, bad ? "err" : "ok");
  } catch (e) {
    fail(new Error(`[${step}] ` + String((e && e.message) || e)));
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
