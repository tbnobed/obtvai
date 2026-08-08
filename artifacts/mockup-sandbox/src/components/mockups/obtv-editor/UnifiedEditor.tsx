import {
  Play, SkipBack, SkipForward, ChevronLeft, ChevronRight, Scissors, Download,
  Sparkles, Send, Film, Search, LayoutGrid, Type, FileText, Settings,
  ChevronDown, Volume2, Maximize2, Gauge, SlidersHorizontal, MonitorPlay,
  ThumbsUp, ThumbsDown, Lock, Trash2, X, Clapperboard,
} from "lucide-react";

/* ── fake data ─────────────────────────────────────────────────────── */
const transcript = [
  { sp: "Erik Stakelbeck", tc: "0:12", tone: "positive", text: "Mike Huckabee, Ambassador, great to see you as always. It seems we're in a different place now." },
  { sp: "Mike Huckabee", tc: "0:31", tone: "tension", text: "With Iran, clearly, than we have been in the past 47 years. President Trump means business." },
  { sp: "Mike Huckabee", tc: "1:04", tone: "positive", text: "Seen the strait of hostilities ease; the dexterity here has been remarkable to watch." },
  { sp: "Erik Stakelbeck", tc: "1:42", tone: "tension", text: "Is that the sense you get from your conversations with him? I mean, I think if you just look at the record…" },
  { sp: "Mike Huckabee", tc: "2:15", tone: "anger", text: "There's going to be no half measures here, no kind of appeasement of the regime like we've seen from his predecessors." },
];
const moments = [
  { who: "Mike Huckabee", tag: "Israel Flag", color: "bg-emerald-400" },
  { who: "Erik Stakelbeck", tag: "Mention: Trump", color: "bg-sky-400" },
];
const chat = [
  { role: "sys", text: "Draft cut v6 created for \"Israel Flag\" scenes" },
  { role: "user", text: "Ask AI: \"Refine the flag cut, adding a wide before Mike speaks.\"" },
  { role: "ai", text: "Mike Huckabee created for \"Israel Flag scenes\" — adding a wide shot before he speaks. 1 flow · 3 threads" },
  { role: "sys", text: "Draft cut v6 updated — 7 clips · 4:37" },
];
const clips = [
  { n: 1, name: "Flag B-Roll", dur: 12, w: 9, hue: "from-sky-800 to-sky-950" },
  { n: 2, name: "Huckabee's Line", dur: 32, w: 20, hue: "from-zinc-700 to-zinc-900" },
  { n: 3, name: "Huckabee's Line 2", dur: 45, w: 26, hue: "from-slate-700 to-slate-900" },
  { n: 4, name: "Stakelbeck Q", dur: 27, w: 16, hue: "from-zinc-600 to-zinc-900" },
  { n: 5, name: "Huckabee's Line 3", dur: 45, w: 24, hue: "from-stone-700 to-stone-950" },
  { n: 6, name: "Wide 2-shot", dur: 38, w: 22, hue: "from-neutral-700 to-neutral-950" },
  { n: 7, name: "Huckabee closer", dur: 45, w: 24, hue: "from-zinc-700 to-zinc-950" },
];
const tags = [
  { label: "Mike Huckabee", color: "bg-emerald-500/80 text-emerald-50", left: "2%" },
  { label: "Erik Stakelbeck", color: "bg-sky-500/80 text-sky-50", left: "24%" },
  { label: "Israel Flag", color: "bg-amber-500/80 text-amber-950", left: "45%" },
  { label: "Israel Flag", color: "bg-amber-500/80 text-amber-950", left: "60%" },
  { label: "Mention: Trump", color: "bg-fuchsia-500/80 text-fuchsia-50", left: "80%" },
];
const toneColor: Record<string, string> = {
  positive: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  tension: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  anger: "bg-rose-500/15 text-rose-300 border-rose-500/30",
};

/* ── tiny helpers ──────────────────────────────────────────────────── */
function Thumb({ hue, className = "" }: { hue: string; className?: string }) {
  return (
    <div className={`relative bg-gradient-to-br ${hue} overflow-hidden ${className}`}>
      <div className="absolute inset-0 opacity-30 [background:radial-gradient(circle_at_30%_30%,rgba(255,255,255,.25),transparent_55%)]" />
      <Film className="absolute inset-0 m-auto w-4 h-4 text-white/25" />
    </div>
  );
}
function Wave() {
  const bars = Array.from({ length: 160 }, (_, i) =>
    18 + Math.abs(Math.sin(i * 0.55) * 42) + Math.abs(Math.sin(i * 0.13) * 24));
  return (
    <div className="flex items-center h-full w-full gap-px px-1">
      {bars.map((h, i) => <div key={i} className="flex-1 bg-sky-400/60 rounded-sm" style={{ height: `${h}%` }} />)}
    </div>
  );
}

/* ── mockup ────────────────────────────────────────────────────────── */
export function UnifiedEditor() {
  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-zinc-950 text-zinc-200 text-[13px] font-['Inter',sans-serif]">
      {/* Top bar */}
      <div className="h-11 shrink-0 border-b border-zinc-800 flex items-center px-3 gap-3">
        <div className="flex items-center gap-2 text-zinc-400">
          <Clapperboard className="w-4 h-4 text-sky-400" />
          <span className="font-semibold text-zinc-200 tracking-wide">[PROJECT: HUCKABEE_STAKS]</span>
          <span className="text-zinc-600">|</span>
          <span className="uppercase text-xs tracking-wider">Library</span>
        </div>
        <div className="mx-auto flex items-center gap-1.5 bg-zinc-900 border border-zinc-800 rounded-md px-3 py-1">
          <span className="font-semibold">[DRAFT CUT v6]</span>
          <ChevronDown className="w-3.5 h-3.5 text-zinc-500" />
        </div>
        <button className="flex items-center gap-1.5 border border-zinc-700 rounded-md px-2.5 py-1 text-xs hover:bg-zinc-900"><Scissors className="w-3.5 h-3.5" /> TRIM</button>
        <button className="flex items-center gap-1.5 bg-sky-600 hover:bg-sky-500 text-white rounded-md px-3 py-1 text-xs font-semibold"><Download className="w-3.5 h-3.5" /> EXPORT</button>
      </div>

      <div className="flex-1 flex min-h-0">
        {/* Icon rail */}
        <div className="w-11 shrink-0 border-r border-zinc-800 flex flex-col items-center gap-4 py-3 text-zinc-500">
          <MonitorPlay className="w-4.5 h-4.5 text-sky-400" />
          <LayoutGrid className="w-4 h-4" />
          <Type className="w-4 h-4" />
          <FileText className="w-4 h-4" />
          <Search className="w-4 h-4" />
          <Settings className="w-4 h-4 mt-auto" />
        </div>

        {/* Project & Insights */}
        <div className="w-[280px] shrink-0 border-r border-zinc-800 flex flex-col min-h-0">
          <div className="px-3 py-2.5 border-b border-zinc-800 flex items-center justify-between">
            <span className="text-[11px] font-bold tracking-widest text-zinc-300">PROJECT &amp; INSIGHTS</span>
            <SlidersHorizontal className="w-3.5 h-3.5 text-zinc-600" />
          </div>
          <div className="flex-1 overflow-hidden px-3 py-2 space-y-4">
            <div>
              <div className="text-[10px] font-bold tracking-widest text-zinc-500 mb-2">TRANSCRIPT</div>
              <div className="space-y-2.5">
                {transcript.map((t, i) => (
                  <div key={i} className={`rounded p-1.5 -mx-1.5 ${i === 1 ? "bg-sky-500/10 ring-1 ring-sky-500/30" : ""}`}>
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className={`text-[11px] font-semibold ${t.sp.startsWith("Mike") ? "text-emerald-400" : "text-sky-400"}`}>{t.sp}</span>
                      <span className="text-[10px] text-zinc-600 font-mono">{t.tc}</span>
                      <span className={`ml-auto text-[9px] px-1 rounded border ${toneColor[t.tone]}`}>{t.tone}</span>
                    </div>
                    <p className="text-[12px] leading-snug text-zinc-400">{t.text}</p>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[10px] font-bold tracking-widest text-zinc-500 mb-2">AI KEY MOMENTS</div>
              <div className="grid grid-cols-2 gap-1.5">
                {moments.map((m, i) => (
                  <div key={i} className="rounded border border-zinc-800 bg-zinc-900/70 p-1.5">
                    <div className="flex items-center gap-1"><span className={`w-1.5 h-1.5 rounded-full ${m.color}`} /><span className="text-[11px] font-medium truncate">{m.who}</span></div>
                    <div className="text-[10px] text-zinc-500 truncate">{m.tag}</div>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[10px] font-bold tracking-widest text-zinc-500 mb-1.5">SYNOPSIS</div>
              <p className="text-[11px] leading-relaxed text-zinc-500 line-clamp-5">
                Erik Stakelbeck interviews Ambassador Mike Huckabee on Iran, Israel and the shifting security
                posture under President Trump — an uncompromising war-horse framing with historic Israel-Lebanon
                breakthroughs and Red Sea shipping threats as key beats.
              </p>
            </div>
          </div>
        </div>

        {/* Editorial assistant */}
        <div className="w-[250px] shrink-0 border-r border-zinc-800 flex flex-col min-h-0">
          <div className="px-3 py-2.5 border-b border-zinc-800 flex items-center justify-between">
            <span className="text-[11px] font-bold tracking-widest text-zinc-300 flex items-center gap-1.5"><Sparkles className="w-3 h-3 text-sky-400" /> EDITORIAL ASSISTANT</span>
            <X className="w-3.5 h-3.5 text-zinc-600" />
          </div>
          <div className="px-3 pt-2 text-[10px] font-bold tracking-widest text-zinc-600">CHAT LOG</div>
          <div className="flex-1 overflow-hidden px-3 py-2 space-y-2">
            {chat.map((c, i) => (
              <div key={i} className={`rounded-md px-2 py-1.5 text-[11px] leading-snug border ${
                c.role === "user" ? "bg-sky-600/90 border-sky-500 text-white ml-4"
                : c.role === "ai" ? "bg-zinc-900 border-zinc-800 text-zinc-300"
                : "bg-zinc-900/50 border-zinc-800/70 text-zinc-500"}`}>
                {c.text}
              </div>
            ))}
            <button className="text-[10px] text-zinc-600 hover:text-zinc-400">Show 6 more in Action…</button>
          </div>
          <div className="p-2 border-t border-zinc-800 flex items-center gap-1.5">
            <div className="flex-1 bg-zinc-900 border border-zinc-800 rounded-md px-2 py-1.5 text-[11px] text-zinc-600">Prompt input bar</div>
            <button className="bg-sky-600 rounded-md p-1.5"><Send className="w-3 h-3 text-white" /></button>
          </div>
        </div>

        {/* Viewport canvas */}
        <div className="flex-1 min-w-0 flex flex-col bg-black relative">
          <div className="absolute top-3 left-3 z-10 flex rounded overflow-hidden border border-zinc-700 text-[10px] font-bold tracking-widest">
            <span className="bg-white text-black px-2 py-1">PREVIEW</span>
            <span className="bg-black/60 text-zinc-400 px-2 py-1">SOURCE</span>
          </div>
          <div className="flex-1 grid grid-cols-2 gap-px bg-zinc-900 min-h-0">
            <Thumb hue="from-sky-900 via-zinc-900 to-black" className="w-full h-full" />
            <Thumb hue="from-amber-900/50 via-zinc-900 to-black" className="w-full h-full" />
          </div>
          {/* scrub + transport */}
          <div className="shrink-0 px-3 py-2 space-y-2 border-t border-zinc-800 bg-zinc-950">
            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full bg-white" />
              <div className="h-1 flex-1 rounded bg-zinc-800"><div className="h-full w-[22%] rounded bg-sky-500" /></div>
              <span className="font-mono text-[10px] text-zinc-500">0:01.05 / 4:37.02</span>
            </div>
            <div className="flex items-center">
              <span className="text-[10px] font-bold tracking-widest text-zinc-500">PREVIEW <span className="text-zinc-700">|</span> SOURCE</span>
              <div className="mx-auto flex items-center gap-3 text-zinc-400">
                <SkipBack className="w-4 h-4" /><ChevronLeft className="w-4 h-4" />
                <span className="bg-white text-black rounded-full p-1.5"><Play className="w-3.5 h-3.5 fill-black" /></span>
                <ChevronRight className="w-4 h-4" /><SkipForward className="w-4 h-4" />
              </div>
              <div className="flex items-center gap-2.5 text-zinc-500">
                <Gauge className="w-3.5 h-3.5" /><Volume2 className="w-3.5 h-3.5" /><Maximize2 className="w-3.5 h-3.5" />
              </div>
            </div>
          </div>
          {/* floating Ask-AI bar */}
          <div className="absolute bottom-16 left-1/2 -translate-x-1/2 z-10 w-[62%] flex items-center gap-2 bg-zinc-900/95 border border-zinc-700 rounded-lg px-3 py-2 shadow-2xl shadow-black/60 backdrop-blur">
            <Sparkles className="w-3.5 h-3.5 text-sky-400 shrink-0" />
            <span className="text-[12px] text-zinc-300 truncate">Ask AI: “Refine the flag cut, adding a wide shot before Mike speaks.”</span>
            <button className="ml-auto bg-sky-600 rounded p-1"><Send className="w-3 h-3 text-white" /></button>
          </div>
        </div>
      </div>

      {/* Timeline */}
      <div className="shrink-0 border-t border-zinc-800 bg-zinc-950">
        <div className="flex items-center gap-2 px-3 py-1.5 border-b border-zinc-800/70">
          <span className="text-[10px] font-bold tracking-widest text-zinc-300">DRAFT CUT v6</span>
          <ChevronDown className="w-3 h-3 text-zinc-600" />
          <span className="text-[10px] text-zinc-600">7 clips · 4:37</span>
          <div className="ml-auto flex items-center gap-2 text-zinc-600">
            <ThumbsUp className="w-3 h-3" /><ThumbsDown className="w-3 h-3" /><Lock className="w-3 h-3" /><Trash2 className="w-3 h-3" />
          </div>
        </div>
        <div className="grid grid-cols-[110px_1fr] text-[9px] font-bold tracking-widest text-zinc-600">
          {/* thumbnails row */}
          <div className="px-3 py-1.5 flex items-center border-b border-zinc-900">CLIPS</div>
          <div className="border-b border-zinc-900 flex gap-1 px-1 py-1 overflow-hidden">
            {clips.map((c) => (
              <div key={c.n} className={`shrink-0 rounded-sm overflow-hidden border ${c.n === 1 ? "border-sky-400" : "border-zinc-800"}`} style={{ width: 92 }}>
                <Thumb hue={c.hue} className="h-11 w-full" />
                <div className="bg-zinc-900 px-1 py-0.5 text-[9px] font-medium text-zinc-400 truncate normal-case tracking-normal">{c.n}: {c.name}</div>
              </div>
            ))}
          </div>
          {/* video track */}
          <div className="px-3 py-1.5 flex items-center border-b border-zinc-900">[VIDEO]</div>
          <div className="border-b border-zinc-900 flex items-center gap-px px-1 py-1">
            {clips.map((c) => (
              <div key={c.n} className={`h-6 rounded-sm bg-gradient-to-r ${c.hue} border ${c.n === 1 ? "border-sky-400" : "border-zinc-700/60"} flex items-center px-1.5 min-w-0`} style={{ width: `${c.w}%` }}>
                <span className="text-[9px] text-zinc-300 truncate normal-case tracking-normal">{c.n}: {c.name}</span>
              </div>
            ))}
          </div>
          {/* dialogue */}
          <div className="px-3 py-1.5 flex items-center border-b border-zinc-900">[DIALOGUE]</div>
          <div className="border-b border-zinc-900 h-8 relative px-1 py-1">
            <div className="absolute inset-1 rounded-sm bg-sky-950/50 border border-sky-900/50 overflow-hidden"><Wave /></div>
            <span className="absolute left-1/3 top-1/2 -translate-y-1/2 text-[9px] text-sky-200/90 normal-case tracking-normal bg-sky-950/80 px-1.5 rounded">Mike Huckabee, that wide editing frame impacts dialogue of “Israel-like” speaks.</span>
          </div>
          {/* semantic tags */}
          <div className="px-3 py-1.5 flex items-center border-b border-zinc-900">[AI SEMANTIC TAGS]</div>
          <div className="border-b border-zinc-900 h-7 relative px-1">
            {tags.map((t, i) => (
              <span key={i} className={`absolute top-1/2 -translate-y-1/2 ${t.color} rounded-full px-2 py-0.5 text-[9px] font-semibold normal-case tracking-normal whitespace-nowrap`} style={{ left: t.left }}>● {t.label}</span>
            ))}
          </div>
          {/* emotion heatmap */}
          <div className="px-3 py-1.5 flex items-center">[EMOTION HEATMAP]</div>
          <div className="h-5 px-1 py-1">
            <div className="h-full w-full rounded-sm [background:linear-gradient(90deg,#16a34a_0%,#84cc16_14%,#eab308_28%,#f97316_40%,#dc2626_52%,#f97316_63%,#eab308_74%,#22c55e_88%,#4ade80_100%)]" />
          </div>
        </div>
      </div>
    </div>
  );
}
