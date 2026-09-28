import { Redirect, useSearch } from "wouter";

/** Legacy /ai destination — the assistant now lives inside the Media Library. */
export default function AIQA() {
  const params = new URLSearchParams(useSearch());
  const next = new URLSearchParams({ ask: "1" });
  const q = params.get("q");
  const conv = params.get("conv");
  if (q && q.trim()) next.set("q", q.trim());
  else if (conv) next.set("conv", conv);
  return <Redirect to={`/library?${next.toString()}`} replace />;
}
