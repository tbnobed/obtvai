import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

type ExampleInput = { instruction: string; context: string; answer: string; source_ref: string; group: string; rights_approved: boolean; required_terms: string[]; expected_format: "text" | "json" };
type Example = ExampleInput & { id: string; status: string; author: string; reviewer: string | null };
type Dataset = { id: string; base_model: string; base_revision: string; dataset_hash: string; train_count: number; heldout_count: number };
type ResultOutput = { answer: string; required_terms_pass: boolean; has_term_checks: boolean; format_pass: boolean; expected_format: string };
type Result = { id: string; reference_answer: string; baseline: ResultOutput; candidate: ResultOutput };
type Evaluation = { id: string; dataset_id: string; status: string; review_note: string | null; report: { results: Result[]; adapter_hash: string } };
type State = { examples: Example[]; datasets: Dataset[]; evaluations: Evaluation[]; execution_mode: string };
const empty: ExampleInput = { instruction: "", context: "", answer: "", source_ref: "", group: "", rights_approved: false, required_terms: [], expected_format: "text" };
const scoreKeys = ["baseline_grounding", "candidate_grounding", "baseline_style", "candidate_style"] as const;

async function api(path = "", method = "GET", body?: unknown) {
  const response = await fetch(`/api/training${path}`, { method, credentials: "include", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data.error ?? "Request failed"));
  return data;
}

export default function Training() {
  const queryClient = useQueryClient();
  const state = useQuery<State>({ queryKey: ["training-admin"], queryFn: () => api(), refetchInterval: 30000 });
  const [form, setForm] = useState<ExampleInput>(empty);
  const [editing, setEditing] = useState<string | null>(null);
  const [terms, setTerms] = useState("");
  const [model, setModel] = useState("");
  const [revision, setRevision] = useState("");
  const [license, setLicense] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [scores, setScores] = useState<Record<string, Record<string, number>>>({});
  async function action(run: () => Promise<unknown>, message: string) {
    setBusy(true); setError(""); setNotice("");
    try { await run(); await queryClient.invalidateQueries({ queryKey: ["training-admin"] }); setNotice(message); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  const data = state.data;
  return <div className="space-y-6 p-4 md:p-6 max-w-7xl mx-auto">
    <header><h1 className="text-2xl font-bold">Model Training</h1><p className="text-muted-foreground mt-1">Curate trusted examples, prepare a LoRA pilot, and compare it against the base model.</p></header>
    <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-4 text-sm space-y-2">
      <p className="font-medium">Live inference and ingestion are unchanged.</p>
      <p>Training executes on a dedicated idle host using services/training/train.py. This page does not queue GPU jobs. An exported dataset is prepared—not trained. Approval records a review, not a deployment.</p>
    </div>
    {(error || state.error) && <p role="alert" className="text-destructive border border-destructive/40 p-3 rounded">{error || String(state.error)}</p>}
    {notice && <p role="status" className="text-sm text-green-500">{notice}</p>}
    {state.isLoading && <p>Loading training records…</p>}
    <div className="grid lg:grid-cols-2 gap-6">
      <section className="rounded-lg border p-5 space-y-4">
        <h2 className="font-semibold text-lg">{editing ? "Edit example (approval will reset)" : "Add a human-authored example"}</h2>
        <form className="space-y-3" onSubmit={e => { e.preventDefault(); void action(async () => {
          await api(editing ? `/examples/${editing}` : "/examples", editing ? "PUT" : "POST", { ...form, required_terms: terms.split(",").map(t => t.trim()).filter(Boolean) });
          setForm(empty); setTerms(""); setEditing(null);
        }, "Example saved as a draft. Review and approve it before export."); }}>
          {(["instruction", "context", "answer", "source_ref", "group"] as const).map(key => <div key={key} className="space-y-1">
            <Label htmlFor={`training-${key}`}>{({ instruction: "Instruction / question", context: "Source context (optional)", answer: "Desired answer", source_ref: "Source reference / asset ID", group: "Leakage group (same asset or episode = same group)" })[key]}</Label>
            {["instruction", "context", "answer"].includes(key)
              ? <Textarea id={`training-${key}`} value={form[key]} required={key !== "context"} maxLength={key === "instruction" ? 4000 : 16000} onChange={e => setForm({ ...form, [key]: e.target.value })} rows={key === "answer" ? 5 : 3} />
              : <Input id={`training-${key}`} value={form[key]} required minLength={3} maxLength={key === "group" ? 200 : 500} onChange={e => setForm({ ...form, [key]: e.target.value })} />}
          </div>)}
          <div><Label htmlFor="training-terms">Required terms, comma separated (optional checks—not truth scores)</Label><Input id="training-terms" value={terms} onChange={e => setTerms(e.target.value)} /></div>
          <div><Label htmlFor="training-format">Expected output format</Label><select id="training-format" className="block bg-background border rounded p-2 mt-1" value={form.expected_format} onChange={e => setForm({ ...form, expected_format: e.target.value as "text" | "json" })}><option value="text">Text</option><option value="json">Valid JSON</option></select></div>
          <label className="flex gap-2 text-sm items-start"><input type="checkbox" checked={form.rights_approved} onChange={e => setForm({ ...form, rights_approved: e.target.checked })} />I confirm we have the rights to use this material for model training.</label>
          <div className="flex gap-2"><Button disabled={busy} type="submit">Save draft</Button>{editing && <Button type="button" variant="outline" onClick={() => { setEditing(null); setForm(empty); setTerms(""); }}>Cancel edit</Button>}</div>
        </form>
      </section>
      <section className="rounded-lg border p-5 space-y-4">
        <h2 className="font-semibold text-lg">Review examples</h2>
        <p className="text-sm text-muted-foreground">{data?.examples.filter(e => e.status === "approved").length ?? 0} approved. Pilot export requires 10 examples, 5 independent groups, and a held-out split. This minimum is not evidence of model quality.</p>
        <div className="space-y-3 max-h-[780px] overflow-auto">
          {data?.examples.length === 0 && <p className="text-sm text-muted-foreground">No examples yet. Add your own preferred answers or editorial corrections—AI-generated outputs are not automatically approved.</p>}
          {data?.examples.map(example => <article key={example.id} className="border rounded p-3 space-y-2">
            <div className="flex justify-between gap-3"><h3 className="font-medium break-words">{example.instruction}</h3><span className="text-xs shrink-0">{example.status}</span></div>
            <p className="text-xs text-muted-foreground break-all">Source: {example.source_ref} · Group: {example.group} · Author: {example.author}{example.reviewer && ` · Reviewer: ${example.reviewer}`}</p>
            <details className="text-sm"><summary className="cursor-pointer">Review context and answer</summary><p className="whitespace-pre-wrap mt-2">{example.context || "No source context."}</p><p className="whitespace-pre-wrap border-t pt-2 mt-2">{example.answer}</p></details>
            <div className="flex gap-2 flex-wrap">
              <Button size="sm" variant="outline" disabled={busy} onClick={() => { setForm(example); setEditing(example.id); setTerms(example.required_terms.join(", ")); }}>Edit</Button>
              <Button size="sm" disabled={busy || !example.rights_approved || example.status === "approved"} onClick={() => void action(() => api(`/examples/${example.id}/review`, "POST", { status: "approved" }), "Human approval recorded.")}>Approve</Button>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => void action(() => api(`/examples/${example.id}/review`, "POST", { status: "rejected" }), "Example rejected.")}>Reject</Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => { if (window.confirm("Delete this curation example? Existing immutable exports will still contain it.")) void action(() => api(`/examples/${example.id}`, "DELETE"), "Example deleted. Prior exports were not changed."); }}>Delete</Button>
            </div>
          </article>)}
        </div>
      </section>
    </div>
    <section className="rounded-lg border p-5 space-y-4">
      <h2 className="font-semibold text-lg">Freeze an immutable dataset</h2>
      <p className="text-sm text-muted-foreground">Only approved, rights-cleared examples are exported. Groups stay together; duplicate and near-duplicate train/held-out content is rejected. Use the exact unquantized base checkpoint—not its AWQ serving variant.</p>
      <form className="grid md:grid-cols-3 gap-3" onSubmit={e => { e.preventDefault(); void action(() => api("/datasets", "POST", { base_model: model, base_revision: revision, license_note: license }), "Immutable dataset prepared for external training."); }}>
        <div><Label htmlFor="training-model">Verified base model ID</Label><Input id="training-model" required value={model} onChange={e => setModel(e.target.value)} /></div>
        <div><Label htmlFor="training-revision">Exact 40-character model revision</Label><Input id="training-revision" required pattern="[0-9a-f]{40}" value={revision} onChange={e => setRevision(e.target.value)} /></div>
        <div><Label htmlFor="training-license">Model license and data-rights notes</Label><Input id="training-license" required minLength={10} value={license} onChange={e => setLicense(e.target.value)} /></div>
        <Button className="md:col-span-3 justify-self-start" disabled={busy} type="submit">Prepare dataset</Button>
      </form>
      {data?.datasets.map(dataset => <article key={dataset.id} className="border rounded p-4 space-y-2">
        <h3 className="font-medium">{dataset.base_model} · Prepared for external training</h3>
        <p className="text-sm">{dataset.train_count} train / {dataset.heldout_count} held out</p><p className="text-xs text-muted-foreground break-all">SHA-256: {dataset.dataset_hash}</p>
        <div className="flex flex-wrap items-center gap-4"><a className="text-primary underline text-sm" href={`/api/training/datasets/${dataset.id}/download`}>Download immutable dataset</a>
          <label className="text-sm">Import actual evaluation report <input type="file" accept=".json,application/json" disabled={busy} className="block mt-1 text-xs" onChange={e => {
            const file = e.target.files?.[0]; e.target.value = ""; if (!file) return;
            void action(async () => { if (file.size > 2_000_000) throw new Error("Report must be smaller than 2 MB."); return api(`/datasets/${dataset.id}/evaluations`, "POST", { report: JSON.parse(await file.text()) }); }, "Paired evaluation imported for human review.");
          }} /></label></div>
        <code className="block text-xs whitespace-pre-wrap break-all bg-muted p-2 rounded">python services/training/train.py training-{dataset.id}.json --output ./adapter-{dataset.id.slice(0, 8)} --dedicated-host-confirmed</code>
      </article>)}
    </section>
    <section className="rounded-lg border p-5 space-y-4">
      <h2 className="font-semibold text-lg">Baseline vs. candidate review</h2>
      <p className="text-sm text-muted-foreground">Imported reports are operator-provided evidence. Verify the actual endpoint checkpoint and loaded adapter. Required-term checks are not grounding scores. Approval does not deploy anything.</p>
      {!data?.evaluations.length && <p className="text-sm">No evaluations imported. After external training, run services/training/evaluate.py against separate test endpoints.</p>}
      {data?.evaluations.map(evaluation => <article key={evaluation.id} className="border rounded p-4 space-y-3">
        <h3 className="font-medium">{evaluation.status.replaceAll("_", " ")}</h3><p className="text-xs break-all">Dataset {evaluation.dataset_id} · Adapter {evaluation.report.adapter_hash}</p>
        {evaluation.report.results.map(result => <details key={result.id} className="border rounded p-2">
          <summary className="cursor-pointer text-sm">Held-out example {result.id}</summary>
          <p className="text-sm whitespace-pre-wrap mt-2"><strong>Reference: </strong>{result.reference_answer}</p>
          <div className="grid md:grid-cols-2 gap-4 mt-3">{(["baseline", "candidate"] as const).map(kind => <div key={kind}><h4 className="font-medium capitalize">{kind}</h4><p className="text-xs text-muted-foreground">{result[kind].has_term_checks ? (result[kind].required_terms_pass ? "Required terms present" : "Required terms missing") : "No required-term checks configured"} · {result[kind].expected_format} format: {result[kind].format_pass ? "pass" : "fail"}</p><p className="text-sm whitespace-pre-wrap mt-2">{result[kind].answer}</p></div>)}</div>
        </details>)}
        {evaluation.review_note && <p className="text-sm">Review: {evaluation.review_note}</p>}
        <Label htmlFor={`review-${evaluation.id}`}>Human review rationale (minimum 20 characters)</Label>
        <Textarea id={`review-${evaluation.id}`} value={notes[evaluation.id] ?? ""} onChange={e => setNotes({ ...notes, [evaluation.id]: e.target.value })} />
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2">{scoreKeys.map(key => <label key={key} className="text-sm capitalize">{key.replaceAll("_", " ")}<select aria-label={`${key} ${evaluation.id}`} className="block bg-background border rounded p-2 mt-1 w-full" value={scores[evaluation.id]?.[key] ?? ""} onChange={e => setScores({ ...scores, [evaluation.id]: { ...scores[evaluation.id], [key]: Number(e.target.value) } })}><option value="">Score 1–5</option>{[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n}{n === 1 ? " — poor" : n === 5 ? " — excellent" : ""}</option>)}</select></label>)}</div>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={!!checked[evaluation.id]} onChange={e => setChecked({ ...checked, [evaluation.id]: e.target.checked })} />I reviewed all answers for grounding and editorial style, and verified endpoint/adapter provenance.</label>
        <div className="flex gap-2">{(["approved_for_manual_trial", "rejected"] as const).map(decision => <Button key={decision} variant={decision === "rejected" ? "outline" : "default"} disabled={busy || !checked[evaluation.id] || scoreKeys.some(key => !scores[evaluation.id]?.[key]) || (notes[evaluation.id] ?? "").trim().length < 20} onClick={() => void action(() => api(`/evaluations/${evaluation.id}/review`, "POST", { decision, note: notes[evaluation.id], checked_grounding_and_style: checked[evaluation.id], scores: scores[evaluation.id] }), "Review recorded. Production inference is unchanged.")}>{decision === "rejected" ? "Reject candidate" : "Approve for a manual trial"}</Button>)}</div>
      </article>)}
    </section>
  </div>;
}