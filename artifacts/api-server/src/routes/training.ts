/** Development parity only. Real production persistence/auth lives in services/api. */
import { Router } from "express";
import { mkdirSync, readFileSync, writeFileSync, renameSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { createHash, randomUUID } from "node:crypto";

const router = Router();
const filename = resolve(".data/training-admin.json");
type Row = Record<string, any>;
type Store = { examples: Row[]; datasets: Row[]; evaluations: Row[] };
const canonical = (value: any): string => value !== null && typeof value === "object"
  ? Array.isArray(value) ? `[${value.map(canonical).join(",")}]` : `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k])}`).join(",")}}`
  : JSON.stringify(value);
const hash = (value: any) => createHash("sha256").update(canonical(value)).digest("hex");
const norm = (value: string) => (value.toLowerCase().match(/[\p{L}\p{N}_]+/gu) ?? []).join(" ");
function nearDuplicate(left: string, right: string) {
  const a = new Set(Array.from({ length: left.length - 1 }, (_, i) => left.slice(i, i + 2)));
  const b = new Set(Array.from({ length: right.length - 1 }, (_, i) => right.slice(i, i + 2)));
  return 2 * [...a].filter(t => b.has(t)).length / (a.size + b.size) >= .9;
}
function load(): Store {
  try { return JSON.parse(readFileSync(filename, "utf8")); }
  catch (e) { if ((e as NodeJS.ErrnoException).code === "ENOENT") return { examples: [], datasets: [], evaluations: [] }; throw e; }
}
function save(value: Store) {
  mkdirSync(dirname(filename), { recursive: true });
  writeFileSync(filename + ".tmp", JSON.stringify(value), { mode: 0o600 });
  renameSync(filename + ".tmp", filename);
}
function requireValue(ok: unknown, message: string): asserts ok { if (!ok) throw new Error(message); }
function example(body: Row) {
  const result: Row = {};
  for (const [key, max] of Object.entries({ instruction: 4000, context: 16000, answer: 16000, source_ref: 500, group: 200 })) {
    requireValue(typeof body[key] === "string" && body[key].length <= max && (key === "context" || body[key].trim().length >= 3), `Invalid ${key}`);
    result[key] = key === "context" ? body[key] : body[key].trim();
  }
  requireValue(typeof body.rights_approved === "boolean", "Rights confirmation must be a boolean.");
  result.rights_approved = body.rights_approved;
  const terms = body.required_terms ?? [];
  requireValue(Array.isArray(terms) && terms.length <= 20 && terms.every(t => typeof t === "string" && t.trim() && t.length <= 100), "Invalid required terms");
  result.required_terms = terms.map((t: string) => t.trim());
  requireValue(body.expected_format === undefined || ["text", "json"].includes(body.expected_format), "Invalid expected format");
  result.expected_format = body.expected_format ?? "text";
  return result;
}
router.use("/training", (req, res, next) => {
  if ((req as typeof req & { user?: { role: string } }).user?.role !== "admin") { res.status(403).json({ detail: "Admin access required" }); return; }
  next();
});
router.all("/training/{*path}", handle);
router.all("/training", handle);
function handle(req: any, res: any) {
  try {
    const store = load();
    const user = req.user?.username ?? req.user?.id;
    const path = req.path.slice("/training".length).split("/").filter(Boolean);
    const [kind, id, operation] = path;
    const method = req.method;
    const body = req.body ?? {};
    if (!kind && method === "GET") {
      res.json({ execution_mode: "external_dedicated_host", examples: store.examples.slice().reverse(),
        datasets: store.datasets.slice().reverse().map(d => ({ id: d.id, base_model: d.manifest.base_model, base_revision: d.manifest.base_revision, dataset_hash: d.manifest.dataset_hash, train_count: d.manifest.train.length, heldout_count: d.manifest.heldout.length })),
        evaluations: store.evaluations.slice().reverse() }); return;
    }
    let response: Row = {};
    if (kind === "examples" && !id && method === "POST") {
      const row = { ...example(body), id: randomUUID(), author: user, reviewer: null, status: "draft" };
      store.examples.push(row); response = { id: row.id };
    } else if (kind === "examples" && id) {
      const row = store.examples.find(e => e.id === id);
      if (!row) { res.status(404).json({ detail: "Record not found" }); return; }
      if (method === "PUT") Object.assign(row, example(body), { status: "draft", reviewer: null });
      else if (method === "DELETE") store.examples = store.examples.filter(e => e.id !== id);
      else if (method === "POST" && operation === "review") {
        requireValue(["draft", "approved", "rejected"].includes(body.status), "Invalid review status");
        requireValue(body.status !== "approved" || row.rights_approved, "Confirm training rights before approving.");
        Object.assign(row, { status: body.status, reviewer: user });
      } else { res.sendStatus(405); return; }
      response = { id, status: row.status };
    } else if (kind === "datasets" && !id && method === "POST") {
      requireValue(typeof body.base_model === "string" && body.base_model.length >= 3 && /^[0-9a-f]{40}$/.test(body.base_revision) && typeof body.license_note === "string" && body.license_note.length >= 10, "Model, immutable revision and license notes are required.");
      const records: Row[] = store.examples.filter(e => e.status === "approved" && e.rights_approved).map((e): Row => {
        const { status: _status, ...record } = e;
        return { ...record, content_hash: hash({ instruction: norm(e.instruction), context: norm(e.context), answer: norm(e.answer) }) };
      }).sort((a, b) => a.id.localeCompare(b.id));
      requireValue(records.length >= 10 && records.length <= 2000, "Pilot requires 10–2,000 approved examples.");
      requireValue(new Set(records.map(e => e.content_hash)).size === records.length, "Duplicate examples found.");
      const sources = new Map<string, string>();
      for (const row of records) { requireValue(!sources.has(row.source_ref) || sources.get(row.source_ref) === row.group, "One source is assigned to multiple split groups."); sources.set(row.source_ref, row.group); }
      const groups = [...new Set(records.map(e => e.group as string))].sort((a, b) => hash(a).localeCompare(hash(b)));
      requireValue(groups.length >= 5, "At least five independent source groups are required.");
      const evalGroups = new Set(groups.slice(0, Math.max(1, Math.floor(groups.length / 5))));
      const train = records.filter(e => !evalGroups.has(e.group)), heldout = records.filter(e => evalGroups.has(e.group));
      requireValue(train.length >= 8 && heldout.length >= 2, "Split requires at least eight training and two held-out examples.");
      for (const a of train) for (const b of heldout) for (const key of ["context", "answer"]) {
        const left = norm(a[key]), right = norm(b[key]);
        requireValue(Math.min(left.length, right.length) < 40 || !nearDuplicate(left, right), "Near-duplicate context/answer crosses train and held-out groups.");
      }
      const manifest = { schema_version: 1, base_model: body.base_model, base_revision: body.base_revision, license_note: body.license_note, train, heldout, training_policy: "Human-approved examples only; no automatic production promotion." };
      const row = { id: randomUUID(), manifest: { ...manifest, dataset_hash: hash(manifest) } };
      store.datasets.push(row); response = { id: row.id, dataset_hash: row.manifest.dataset_hash };
    } else if (kind === "datasets" && id) {
      const dataset = store.datasets.find(d => d.id === id);
      if (!dataset) { res.status(404).json({ detail: "Record not found" }); return; }
      if (operation === "download" && method === "GET") { res.set("Cache-Control", "no-store").attachment(`training-${id}.json`).json(dataset.manifest); return; }
      requireValue(operation === "evaluations" && method === "POST", "Unsupported operation");
      const report = body.report;
      requireValue(report && JSON.stringify(report).length < 2_000_000, "Report required, maximum 2 MB");
      for (const key of ["dataset_hash", "base_model", "base_revision"]) requireValue(report[key] === dataset.manifest[key], `Mismatched ${key}`);
      requireValue(/^[0-9a-f]{64}$/.test(report.adapter_hash), "Adapter checksum required.");
      const expected = new Map<string, Row>(dataset.manifest.heldout.map((r: Row) => [r.id, r]));
      requireValue(Array.isArray(report.results) && report.results.length === expected.size && new Set(report.results.map((r: Row) => r.id)).size === expected.size, "Complete unique held-out coverage is required.");
      for (const result of report.results) {
        const target = expected.get(result.id); requireValue(target, "Unknown held-out example");
        for (const kind of ["baseline", "candidate"]) {
          requireValue(typeof result[kind]?.answer === "string" && result[kind].answer.trim() && result[kind].answer.length <= 32000, "Complete paired answers required.");
          result[kind].required_terms_pass = target.required_terms.every((t: string) => norm(result[kind].answer).includes(norm(t)));
          result[kind].has_term_checks = !!target.required_terms.length;
          result[kind].expected_format = target.expected_format ?? "text";
          result[kind].format_pass = true;
          if (target.expected_format === "json") { try { JSON.parse(result[kind].answer); } catch { result[kind].format_pass = false; } }
        }
        result.reference_answer = target.answer;
      }
      const row = { id: randomUUID(), dataset_id: id, report, status: "needs_review", review_note: null };
      store.evaluations.push(row); response = { id: row.id, status: row.status };
    } else if (kind === "evaluations" && operation === "review" && method === "POST") {
      const row = store.evaluations.find(r => r.id === id);
      if (!row) { res.status(404).json({ detail: "Record not found" }); return; }
      requireValue(["approved_for_manual_trial", "rejected"].includes(body.decision) && body.checked_grounding_and_style === true && typeof body.note === "string" && body.note.trim().length >= 20, "Human review, decision and rationale required.");
      const keys = ["baseline_grounding", "candidate_grounding", "baseline_style", "candidate_style"];
      requireValue(body.scores && Object.keys(body.scores).length === 4 && keys.every(k => Number.isInteger(body.scores[k]) && body.scores[k] >= 1 && body.scores[k] <= 5), "Four grounding/style scores from 1 to 5 are required.");
      Object.assign(row, { status: body.decision, review_note: body.note, reviewed_by: user, review_scores: body.scores }); response = { status: row.status };
    } else { res.status(404).json({ detail: "Unknown training operation" }); return; }
    save(store); res.status(method === "POST" && !operation ? 201 : 200).json(response);
  } catch (error) { res.status(422).json({ detail: error instanceof Error ? error.message : String(error) }); }
}
export default router;