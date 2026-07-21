import { Router } from "express";
import multer from "multer";
import { normalizeTopicKey, topicLabel, groupTopics } from "../lib/topics";

const router = Router();

const VIDEO_EXTENSIONS = new Set([
  ".mp4", ".mov", ".mkv", ".avi", ".mxf", ".ts", ".m2ts", ".wmv", ".flv", ".webm",
]);

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 500 * 1024 * 1024 },
});

const now = new Date().toISOString();
const assets = [
  {
    id: "asset-001",
    filename: "interview_sarah_chen.mp4",
    original_path: "/media/interview_sarah_chen.mp4",
    proxy_path: "/artifacts/proxies/asset-001.mp4",
    thumbnail_url: null,
    duration_seconds: 1842,
    width: 1920,
    height: 1080,
    fps: 29.97,
    codec: "h264",
    file_size_bytes: 2147483648,
    status: "ready",
    processing_stage: "complete",
    processing_progress: 100,
    scene_count: 47,
    speaker_count: 2,
    synopsis:
      "An in-depth interview with urban planner Sarah Chen covering the city's downtown revitalization plan. Chen discusses affordable housing targets, transit-oriented development, and pushback from local business owners, closing with her outlook on the 2026 bond measure.",
    key_moments: [
      { time: 45, title: "Introduction and background", description: "Sarah Chen outlines her role in the downtown revitalization task force." },
      { time: 312, title: "Affordable housing targets", description: "Discussion of the 30% affordability requirement and developer incentives." },
      { time: 705, title: "Transit-oriented development", description: "Chen explains the light-rail corridor rezoning proposal." },
      { time: 1128, title: "Business owner pushback", description: "Addressing concerns from the merchants association about construction impacts." },
      { time: 1580, title: "2026 bond measure outlook", description: "Closing thoughts on funding prospects and the November ballot." },
    ],
    topics: ["urban planning", "affordable housing", "public transit", "local politics", "development"],
    qc_flags: {
      flags: ["audio_low", "black_frames"],
      max_volume_db: -6.2,
      mean_volume_db: -37.4,
      black_seconds: 3.1,
      black_segments: [{ start: 0.0, end: 3.1, duration: 3.1 }],
    },
    creative: {
      logline:
        "A city planner stakes her career on a 30% affordability promise — and the merchants fighting her may decide whether downtown survives its own rescue.",
      story_beats: [
        { time: 45, beat: "hook", title: "The promise", description: "Chen opens with the task-force mandate — sets stakes for the whole interview. Strong cold-open candidate.", emotion: "confident" },
        { time: 312, beat: "setup", title: "The 30% target", description: "The affordability requirement is laid out with the developer incentive math — the intellectual spine of the piece.", emotion: "measured" },
        { time: 705, beat: "development", title: "Rezoning the corridor", description: "Transit-oriented development plan; visual sequence needs maps and B-roll of the light-rail corridor.", emotion: "optimistic" },
        { time: 1128, beat: "turn", title: "The merchants push back", description: "First real conflict — Chen visibly bristles at the foot-traffic question. This is the dramatic engine of the edit.", emotion: "tense" },
        { time: 1450, beat: "climax", title: "The data rebuttal", description: "Chen counters with construction-impact data from three comparable cities. Her strongest, most quotable exchange.", emotion: "assertive" },
        { time: 1580, beat: "resolution", title: "The ballot question", description: "Bond measure outlook — lands the stakes and gives the piece a forward-looking close.", emotion: "resolute" },
      ],
      clip_suggestions: [
        { start: 43, end: 68, title: "Cold open: the mandate", quote: "We have one shot at this — the next five years decide what downtown is for the next fifty.", reason: "Self-contained stakes-setter with a natural hook; works as the opening of any cut.", strength: 88, platforms: ["youtube", "tiktok", "instagram"] },
        { start: 318, end: 352, title: "The 30% math", quote: "Thirty percent isn't a dream number — the incentive package pays for itself by year six.", reason: "The single clearest explanation of the policy; pull for explainer cuts and the chaptered upload.", strength: 74, platforms: ["youtube", "x"] },
        { start: 1131, end: 1169, title: "Merchants vs. the plan", quote: "They're telling me construction will kill foot traffic. I'm telling them the alternative is a downtown nobody walks to at all.", reason: "The conflict beat — highest engagement potential; invites debate on X and drives replies.", strength: 92, platforms: ["x", "tiktok", "facebook"] },
        { start: 1448, end: 1483, title: "The data rebuttal", quote: "Portland, Minneapolis, Denver — every one of them saw retail revenue recover within eighteen months.", reason: "Best delivery of the session; assertive, specific, and quotable. Anchor of the highlight reel.", strength: 90, platforms: ["youtube", "instagram", "x"] },
        { start: 1583, end: 1614, title: "The ballot close", quote: "If the bond fails in November, this plan doesn't get delayed — it gets buried.", reason: "Time-sensitive news angle and a natural closer for every cut.", strength: 81, platforms: ["youtube", "facebook", "x"] },
      ],
      editorial_notes: [
        { category: "pacing", note: "The 08:00–11:30 stretch on zoning code history drags — cut it to a 20-second summary or lose it entirely; nothing there pays off later." },
        { category: "structure", note: "Consider opening on the 18:48 merchant-pushback exchange, then rewinding to the mandate — conflict-first structure will hold retention far better than the chronological cut." },
        { category: "broll", note: "The corridor rezoning section (11:45–18:00) is unwatchable as a talking head — needs map overlays, light-rail footage, and storefront exteriors throughout." },
        { category: "best_take", note: "Chen's data rebuttal at 24:08 is her best on-camera moment of the session — protect it in every cut, don't trim into the pause before 'every one of them'." },
        { category: "cuts", note: "Both bond-measure explanations (26:20 and 29:40) cover identical ground — keep the second, it's tighter and lands the 'buried' line." },
        { category: "delivery", note: "Chen speeds up noticeably when defensive (18:50–19:30) — leave breathing room around her answers there rather than jump-cutting, or she'll read as rattled." },
      ],
      generated_at: new Date(Date.now() - 82800000).toISOString(),
    } as any,
    highlight_url: null as string | null,
    translated_languages: ["es"] as string[] | null,
    dubbed_languages: ["es"] as string[] | null,
    social_scores: [
      {
        platform: "youtube",
        score: 78,
        verdict: "Strong long-form fit — policy interviews sustain watch time when chaptered around the key moments.",
        strengths: ["31-minute runtime suits YouTube's watch-time algorithm", "Highly searchable topic: downtown revitalization + 2026 bond measure", "Clear chapter structure from key moments"],
        weaknesses: ["Talking-head format needs B-roll to hold retention", "Niche local audience caps ceiling"],
        best_format: "Full interview with chapters, plus a 60s Short teasing the bond measure outlook",
        suggested_caption: "Urban planner Sarah Chen breaks down the downtown revitalization plan — affordable housing targets, transit rezoning, and what the 2026 bond measure means for the city.",
        hashtags: ["#urbanplanning", "#affordablehousing", "#transit", "#localgov", "#cityplanning"],
      },
      {
        platform: "instagram",
        score: 54,
        verdict: "Moderate — needs punchy sub-90s Reels with captions; the full interview won't travel here.",
        strengths: ["Housing affordability clips resonate with 25-40 demo", "Quote cards from Chen's strongest lines are shareable"],
        weaknesses: ["No strong visual hook in a seated interview", "Policy detail gets skipped in feed scrolling"],
        best_format: "3 Reels: housing targets (45s), transit rezoning (60s), bond measure (30s) — bold captions over speaker",
        suggested_caption: "30% affordable housing — bold target or empty promise? Urban planner Sarah Chen explains the plan.",
        hashtags: ["#housingcrisis", "#urbanism", "#citylife", "#affordablehousing"],
      },
      {
        platform: "x",
        score: 71,
        verdict: "Good fit — local politics and housing policy drive replies and quote-posts.",
        strengths: ["Bond measure angle is newsworthy and time-sensitive", "Business-owner pushback segment invites debate", "Clip + thread format suits policy breakdowns"],
        weaknesses: ["Video completion rates on X are low past 45s"],
        best_format: "40s clip of the pushback exchange + a 5-post thread summarizing the plan",
        suggested_caption: "Merchants say construction will kill foot traffic. The city's lead planner says the data shows otherwise. Who's right?",
        hashtags: ["#localpolitics", "#housing", "#transit"],
      },
      {
        platform: "facebook",
        score: 66,
        verdict: "Solid — local-issue content shares well in community groups and older demos.",
        strengths: ["Neighborhood groups actively share city-planning news", "45+ demo engages with bond measure coverage", "Longer videos acceptable on Facebook"],
        weaknesses: ["Organic page reach is weak without group seeding", "Younger demos won't see it"],
        best_format: "3-5 min cutdown focused on 'what changes for your neighborhood', posted natively + seeded to local groups",
        suggested_caption: "Big changes coming downtown: 30% affordable housing, light-rail rezoning, and a 2026 bond measure. Here's what the city's lead planner says it means for you.",
        hashtags: ["#community", "#downtown", "#localnews"],
      },
      {
        platform: "tiktok",
        score: 38,
        verdict: "Weak — no 3-second hook, and policy interviews underperform unless reframed as conflict or stakes.",
        strengths: ["Housing affordability is a proven TikTok topic for Gen Z"],
        weaknesses: ["Seated interview format fights the algorithm", "No trending audio or visual momentum", "Requires heavy re-editing to work"],
        best_format: "15-30s vertical cut: 'They want to tear up downtown — here's the plan' with kinetic captions and B-roll",
        suggested_caption: "Your city might look completely different by 2027 👀 Here's the plan nobody's talking about",
        hashtags: ["#housing", "#fyp", "#citytok", "#genzpolitics"],
      },
    ] as any[] | null,
    created_at: new Date(Date.now() - 86400000 * 2).toISOString(),
    updated_at: new Date(Date.now() - 86400000 * 1).toISOString(),
  },
  {
    id: "asset-002",
    filename: "city_council_meeting_oct24.mp4",
    original_path: "/media/city_council_meeting_oct24.mp4",
    proxy_path: null,
    thumbnail_url: null,
    duration_seconds: 5402,
    width: 1280,
    height: 720,
    fps: 30,
    codec: "h264",
    file_size_bytes: 3758096384,
    status: "processing",
    processing_stage: "transcribing",
    processing_progress: 52,
    scene_count: 12,
    speaker_count: null,
    topics: ["zoning_policy", "budget allocation", "public infrastructure", "community development"],
    created_at: new Date(Date.now() - 3600000).toISOString(),
    updated_at: new Date(Date.now() - 1800000).toISOString(),
  },
  {
    id: "asset-003",
    filename: "documentary_rough_cut_v3.mkv",
    original_path: "/media/documentary_rough_cut_v3.mkv",
    proxy_path: null,
    thumbnail_url: null,
    duration_seconds: 3612,
    width: 3840,
    height: 2160,
    fps: 24,
    codec: "hevc",
    file_size_bytes: 8589934592,
    status: "pending",
    processing_stage: null,
    processing_progress: null,
    scene_count: null,
    speaker_count: null,
    topics: ["local_ai_infrastructure", "GPU-Computing", "documentary production"],
    created_at: new Date(Date.now() - 600000).toISOString(),
    updated_at: null,
  },
  {
    id: "asset-004",
    filename: "press_conference_may15.mp4",
    original_path: "/media/press_conference_may15.mp4",
    proxy_path: "/artifacts/proxies/asset-004.mp4",
    thumbnail_url: null,
    duration_seconds: 2876,
    width: 1920,
    height: 1080,
    fps: 29.97,
    codec: "h264",
    file_size_bytes: 1073741824,
    status: "ready",
    processing_stage: "complete",
    processing_progress: 100,
    scene_count: 31,
    speaker_count: 5,
    topics: ["Local AI Infrastructure", "press relations", "cloud cost reduction"],
    created_at: new Date(Date.now() - 86400000 * 5).toISOString(),
    updated_at: new Date(Date.now() - 86400000 * 4).toISOString(),
  },
  {
    id: "asset-005",
    filename: "broll_warehouse_district.mp4",
    original_path: "/media/broll_warehouse_district.mp4",
    proxy_path: null,
    thumbnail_url: null,
    duration_seconds: 612,
    width: 1920,
    height: 1080,
    fps: 60,
    codec: "h264",
    file_size_bytes: 536870912,
    status: "error",
    processing_stage: "transcribe_failed",
    processing_progress: 48,
    scene_count: 8,
    speaker_count: null,
    topics: ["urban development", "b-roll"],
    created_at: new Date(Date.now() - 86400000 * 3).toISOString(),
    updated_at: new Date(Date.now() - 86400000 * 3 + 7200000).toISOString(),
  },
];

// Pad the mock library so pagination and list-view scrolling are exercised in preview.
for (let i = assets.length; i < 75; i++) {
  const base = assets[i % 5];
  assets.push({
    ...base,
    id: `asset-mock-${i}`,
    filename: `BT_2026${String(100 + i)}_PGM_EP${1500 + i}-proxy.mp4`,
    original_path: `/media2/BT/BT_2026${String(100 + i)}_PGM_EP${1500 + i}-proxy.mp4`,
    created_at: new Date(Date.now() - 3600000 * (i + 10)).toISOString(),
  });
}

const jobs = [
  {
    id: "job-001",
    media_id: "asset-001",
    filename: "interview_sarah_chen.mp4",
    job_type: "transcribe",
    status: "success",
    progress: 100,
    error_message: null,
    logs: ["Loading Whisper model: medium", "Transcribing with cuda...", "Transcription complete: 312 segments"],
    retry_count: 0,
    created_at: new Date(Date.now() - 86400000 * 2 + 3600000).toISOString(),
    started_at: new Date(Date.now() - 86400000 * 2 + 3600000 + 60000).toISOString(),
    finished_at: new Date(Date.now() - 86400000 * 2 + 3600000 + 420000).toISOString(),
  },
  {
    id: "job-002",
    media_id: "asset-001",
    filename: "interview_sarah_chen.mp4",
    job_type: "visual_embed",
    status: "success",
    progress: 100,
    error_message: null,
    logs: ["Loading CLIP model on cuda...", "Embedded 47 scenes"],
    retry_count: 0,
    created_at: new Date(Date.now() - 86400000 * 2 + 7200000).toISOString(),
    started_at: new Date(Date.now() - 86400000 * 2 + 7200000 + 30000).toISOString(),
    finished_at: new Date(Date.now() - 86400000 * 2 + 7200000 + 180000).toISOString(),
  },
  {
    id: "job-003",
    media_id: "asset-002",
    filename: "city_council_meeting_oct24.mp4",
    job_type: "transcribe",
    status: "running",
    progress: 52,
    error_message: null,
    logs: ["Loading Whisper model: medium", "Transcribing with cuda...", "Progress: 52% — 2810s processed"],
    retry_count: 0,
    created_at: new Date(Date.now() - 1800000).toISOString(),
    started_at: new Date(Date.now() - 1740000).toISOString(),
    finished_at: null,
  },
  {
    id: "job-004",
    media_id: "asset-005",
    filename: "broll_warehouse_district.mp4",
    job_type: "transcribe",
    status: "error",
    progress: 48,
    error_message: "CUDA out of memory. Tried to allocate 2.5 GiB.",
    logs: ["Loading Whisper model: medium", "Transcribing with cuda...", "CUDA out of memory. Tried to allocate 2.5 GiB."],
    retry_count: 1,
    created_at: new Date(Date.now() - 86400000 * 3 + 3600000).toISOString(),
    started_at: new Date(Date.now() - 86400000 * 3 + 3660000).toISOString(),
    finished_at: new Date(Date.now() - 86400000 * 3 + 3900000).toISOString(),
  },
  {
    id: "job-005",
    media_id: "asset-003",
    filename: "documentary_rough_cut_v3.mkv",
    job_type: "ingest",
    status: "pending",
    progress: null,
    error_message: null,
    logs: [],
    retry_count: 0,
    created_at: new Date(Date.now() - 600000).toISOString(),
    started_at: null,
    finished_at: null,
  },
];

const scenes = [
  { id: "scene-001", media_id: "asset-001", start_time: 0, end_time: 42.3, thumbnail_url: null, description: "Interview setup, subject seated in office", embedding_id: "scene-001" },
  { id: "scene-002", media_id: "asset-001", start_time: 42.3, end_time: 127.8, thumbnail_url: null, description: "Discussion about Q3 results and team performance", embedding_id: "scene-002" },
  { id: "scene-003", media_id: "asset-001", start_time: 127.8, end_time: 246.1, thumbnail_url: null, description: "Close-up interview, technology strategy topic", embedding_id: "scene-003" },
];

const transcript: {
  id: string; media_id: string; start_time: number; end_time: number;
  text: string; speaker: string; confidence: number;
  translations?: Record<string, string>;
}[] = [
  { id: "seg-001", media_id: "asset-001", start_time: 2.1, end_time: 8.4, text: "Thank you for having me. I'm really excited to talk about what we've been building.", speaker: "SPEAKER_00", confidence: 0.94,
    translations: { es: "Gracias por invitarme. Estoy muy emocionada de hablar sobre lo que hemos estado construyendo." } },
  { id: "seg-002", media_id: "asset-001", start_time: 9.0, end_time: 14.2, text: "So Sarah, can you tell us about the new infrastructure initiative?", speaker: "SPEAKER_01", confidence: 0.91,
    translations: { es: "Entonces, Sarah, ¿puedes contarnos sobre la nueva iniciativa de infraestructura?" } },
  { id: "seg-003", media_id: "asset-001", start_time: 15.5, end_time: 32.0, text: "Absolutely. We've been working on a distributed processing pipeline that can handle petabyte-scale video archives. The key insight was that you don't need cloud infrastructure to do this at scale.", speaker: "SPEAKER_00", confidence: 0.96,
    translations: { es: "Por supuesto. Hemos estado trabajando en una canalización de procesamiento distribuido capaz de manejar archivos de video a escala de petabytes. La clave fue darnos cuenta de que no se necesita infraestructura en la nube para hacerlo a esta escala." } },
  { id: "seg-004", media_id: "asset-001", start_time: 33.1, end_time: 48.7, text: "That's fascinating. Most organizations assume you need AWS or Google Cloud for anything at this scale.", speaker: "SPEAKER_01", confidence: 0.88,
    translations: { es: "Fascinante. La mayoría de las organizaciones asumen que se necesita AWS o Google Cloud para cualquier cosa a esta escala." } },
  { id: "seg-005", media_id: "asset-001", start_time: 50.0, end_time: 71.3, text: "Right, and that's exactly the misconception we're challenging. With modern GPU hardware and the right software architecture, you can build a fully local AI inference stack that outperforms cloud solutions on throughput.", speaker: "SPEAKER_00", confidence: 0.97,
    translations: { es: "Exacto, y esa es precisamente la idea errónea que estamos cuestionando. Con hardware GPU moderno y la arquitectura de software adecuada, se puede construir una pila de inferencia de IA totalmente local que supera a las soluciones en la nube en rendimiento." } },
];

const searchHistory = [
  { id: "sh-001", query: "infrastructure AI processing", result_count: 12, searched_at: new Date(Date.now() - 3600000).toISOString() },
  { id: "sh-002", query: "city council vote on housing", result_count: 7, searched_at: new Date(Date.now() - 7200000).toISOString() },
  { id: "sh-003", query: "Sarah Chen speaking about cloud", result_count: 3, searched_at: new Date(Date.now() - 86400000).toISOString() },
];

const conversations = [
  { id: "conv-001", title: "What did Sarah Chen say about cloud infrastructure?", created_at: new Date(Date.now() - 3600000).toISOString(), message_count: 4 },
  { id: "conv-002", title: "Housing vote discussion at city council", created_at: new Date(Date.now() - 86400000).toISOString(), message_count: 6 },
];

type MockProject = {
  id: string; name: string; description: string | null; script: string | null;
  status: "active" | "archived";
  media_ids: string[];
  created_at: string; updated_at: string | null;
};

function touchProject(pid: string | null | undefined) {
  if (!pid) return;
  const p = projects.find((x) => x.id === pid);
  if (p) p.updated_at = new Date().toISOString();
}

const projects: MockProject[] = [
  {
    id: "proj-001",
    name: "Infrastructure Special",
    description: "Evening special on local AI infrastructure",
    script: "Sarah Chen explains the local AI infrastructure initiative\nCouncil vote on the affordable housing measure",
    status: "active",
    media_ids: [],
    created_at: new Date(Date.now() - 86400000).toISOString(),
    updated_at: null,
  },
];

const markers: {
  id: string;
  media_id: string;
  time: number;
  end_time: number | null;
  kind: string;
  note: string | null;
  source: string;
  created_at: string;
}[] = [
  { id: "mk-001", media_id: "asset-001", time: 1131, end_time: 1169, kind: "select", note: "Conflict beat — use in main cut", source: "editor", created_at: new Date(Date.now() - 3600000).toISOString() },
  { id: "mk-002", media_id: "asset-001", time: 210, end_time: null, kind: "reject", note: "Long tangent about zoning history", source: "editor", created_at: new Date(Date.now() - 3500000).toISOString() },
  { id: "mk-003", media_id: "asset-001", time: 1448, end_time: null, kind: "marker", note: "Check b-roll for data rebuttal", source: "editor", created_at: new Date(Date.now() - 3400000).toISOString() },
];

const clipLists = [
  {
    id: "cl-001",
    name: "Infrastructure Interview Highlights",
    description: "Key moments from the Sarah Chen interview",
    project_id: "proj-001" as string | null,
    locked: false,
    created_at: new Date(Date.now() - 7200000).toISOString(),
    clips: [
      { id: "clip-001", media_id: "asset-001", filename: "interview_sarah_chen.mp4", start_time: 15.5, end_time: 71.3, label: "On local AI infrastructure", notes: null, approved: true, match_reason: 'Matched search "local AI infrastructure" — strong semantic score, speaker emphasis peak', thumbnail_url: null },
      { id: "clip-002", media_id: "asset-001", filename: "interview_sarah_chen.mp4", start_time: 127.8, end_time: 180.0, label: "Q3 results discussion", notes: null, approved: false, match_reason: 'Script line "cover the quarterly results" — transcript match on Q3 discussion', thumbnail_url: null },
    ],
  },
];

function mapClipInput(c: any, i: number, now: number) {
  return {
    id: `clip-${now}-${i}`,
    media_id: c.media_id,
    filename: assets.find((a) => a.id === c.media_id)?.filename || "unknown",
    start_time: c.start_time,
    end_time: c.end_time,
    label: c.label || null,
    notes: c.notes ?? null,
    approved: !!c.approved,
    match_reason: c.match_reason ?? null,
    thumbnail_url: assets.find((a) => a.id === c.media_id)?.thumbnail_url ?? null,
  };
}

// ── Media ────────────────────────────────────────────────────────────────────

// Reconciled duration figures — the single source both /media/stats/summary and
// /insights read, so Dashboard and Insights can never disagree.
function libraryDurations() {
  const transcribed = assets.filter((a) => a.status === "ready");
  return {
    totalSeconds: assets.reduce((s, a) => s + (a.duration_seconds || 0), 0),
    speechIndexedSeconds: transcribed.reduce((s, a) => s + (a.duration_seconds || 0), 0),
    transcribedCount: transcribed.length,
  };
}

function assetTopics(a: any): string[] {
  return Array.isArray(a.topics) ? a.topics : [];
}

function countAssetsWithTopic(key: string): number {
  return assets.filter((a) => assetTopics(a).some((t) => normalizeTopicKey(t) === key)).length;
}

router.get("/media/stats/summary", (_req, res) => {
  const d = libraryDurations();
  res.json({
    total_assets: assets.length,
    total_duration_seconds: d.totalSeconds,
    speech_indexed_seconds: d.speechIndexedSeconds,
    status_counts: assets.reduce<Record<string, number>>((acc, a) => {
      acc[a.status] = (acc[a.status] ?? 0) + 1;
      return acc;
    }, {}),
    storage_bytes: assets.reduce((s, a) => s + (a.file_size_bytes || 0), 0),
    recent_activity: assets.slice(0, 10),
  });
});

router.get("/media", (req, res) => {
  let items = [...assets];
  const status = String(req.query.status ?? "");
  if (status) items = items.filter((a) => a.status === status);
  const person = String(req.query.person ?? "");
  if (person) {
    const ids = new Set((personAppearances[person] ?? []).map((x) => x.media_id));
    items = items.filter((a) => ids.has(a.id));
  }
  const topic = String(req.query.topic ?? "").trim();
  if (topic) {
    const key = normalizeTopicKey(topic);
    items = items.filter((a) => assetTopics(a).some((t) => normalizeTopicKey(t) === key));
  }
  const search = String(req.query.search ?? "").trim().toLowerCase();
  if (search) {
    const fields = (a: (typeof assets)[number]) =>
      search.includes("/")
        ? [a.filename, (a as any).title, a.original_path]
        : [a.filename, (a as any).title];
    items = items.filter((a) =>
      fields(a).some((v) => typeof v === "string" && v.toLowerCase().includes(search)),
    );
  }
  const sort = String(req.query.sort ?? "created_desc");
  const cmp: Record<string, (a: any, b: any) => number> = {
    created_desc: (a, b) => String(b.created_at).localeCompare(String(a.created_at)),
    created_asc: (a, b) => String(a.created_at).localeCompare(String(b.created_at)),
    name_asc: (a, b) => a.filename.toLowerCase().localeCompare(b.filename.toLowerCase()),
    name_desc: (a, b) => b.filename.toLowerCase().localeCompare(a.filename.toLowerCase()),
    duration_desc: (a, b) => (b.duration_seconds ?? -1) - (a.duration_seconds ?? -1),
    duration_asc: (a, b) => (a.duration_seconds ?? Infinity) - (b.duration_seconds ?? Infinity),
    size_desc: (a, b) => (b.file_size_bytes ?? -1) - (a.file_size_bytes ?? -1),
    size_asc: (a, b) => (a.file_size_bytes ?? Infinity) - (b.file_size_bytes ?? Infinity),
  };
  items.sort(cmp[sort] ?? cmp.created_desc);
  const total = items.length;
  const limit = Math.min(Math.max(parseInt(String(req.query.limit ?? "50"), 10) || 50, 1), 200);
  const offset = Math.max(parseInt(String(req.query.offset ?? "0"), 10) || 0, 0);
  res.json({ items: items.slice(offset, offset + limit), total });
});

router.post("/media", (req, res) => {
  const newAsset = {
    id: `asset-${Date.now()}`,
    filename: req.body.title || require("path").basename(req.body.file_path || "unknown.mp4"),
    original_path: req.body.file_path,
    proxy_path: null,
    thumbnail_url: null,
    duration_seconds: null,
    width: null,
    height: null,
    fps: null,
    codec: null,
    file_size_bytes: null,
    status: "pending",
    processing_stage: null,
    processing_progress: null,
    scene_count: null,
    speaker_count: null,
    created_at: new Date().toISOString(),
    updated_at: null,
  };
  res.status(202).json(newAsset);
});

router.post("/media/upload", upload.single("file"), (req, res) => {
  const file = req.file;
  if (!file) {
    res.status(400).json({ error: "No file provided" });
    return;
  }
  const ext = require("path").extname(file.originalname).toLowerCase();
  if (!VIDEO_EXTENSIONS.has(ext)) {
    res.status(400).json({ error: `Unsupported file type: ${ext}` });
    return;
  }
  const id = `asset-${Date.now()}`;
  const newAsset = {
    id,
    filename: req.body.title || file.originalname,
    original_path: `/media/uploads/${file.originalname}`,
    proxy_path: null,
    thumbnail_url: null,
    duration_seconds: null,
    width: null,
    height: null,
    fps: null,
    codec: null,
    file_size_bytes: file.size,
    status: "pending",
    processing_stage: null,
    processing_progress: null,
    scene_count: null,
    speaker_count: null,
    created_at: new Date().toISOString(),
    updated_at: null,
  };
  assets.unshift(newAsset as unknown as (typeof assets)[number]);
  res.status(202).json(newAsset);
});

router.post("/media/import-link", (req, res) => {
  const { url, title } = req.body ?? {};
  if (typeof url !== "string" || !/^https?:\/\/\S+$/.test(url.trim())) {
    res.status(400).json({ error: "Invalid URL — must be an http(s) link" });
    return;
  }
  let guess = "link import";
  try {
    const p = decodeURIComponent(new URL(url.trim()).pathname);
    guess = p.split("/").filter(Boolean).pop() || guess;
  } catch { /* keep default */ }
  const id = `asset-${Date.now()}`;
  const newAsset = {
    id,
    filename: title || guess,
    original_path: `pending-download:${id}`,
    proxy_path: null,
    thumbnail_url: null,
    duration_seconds: null,
    width: null,
    height: null,
    fps: null,
    codec: null,
    file_size_bytes: 0,
    status: "pending",
    processing_stage: "downloading",
    processing_progress: 1,
    scene_count: null,
    speaker_count: null,
    created_at: new Date().toISOString(),
    updated_at: null,
  };
  assets.unshift(newAsset as unknown as (typeof assets)[number]);
  res.status(202).json(newAsset);
});

router.get("/media/:id", (req, res) => {
  const asset = assets.find((a) => a.id === req.params.id);
  if (!asset) { res.status(404).json({ error: "Not found" }); return; }
  res.json(asset);
});

router.delete("/media/:id", (req, res) => {
  const idx = assets.findIndex((a) => a.id === req.params.id);
  if (idx === -1) { res.status(404).json({ error: "Not found" }); return; }
  assets.splice(idx, 1);
  res.status(204).send();
});

router.get("/media/:id/scenes", (req, res) => {
  res.json(scenes.filter((s) => s.media_id === req.params.id));
});

router.get("/media/:id/markers", (req, res) => {
  res.json(markers.filter((m) => m.media_id === req.params.id).sort((a, b) => a.time - b.time));
});

router.post("/media/:id/markers", (req, res) => {
  const asset = assets.find((a) => a.id === req.params.id);
  if (!asset) { res.status(404).json({ detail: "Media not found" }); return; }
  const m = {
    id: `mk-${Date.now()}`,
    media_id: req.params.id,
    time: Math.max(0, Number(req.body.time) || 0),
    end_time: req.body.end_time != null ? Number(req.body.end_time) : null,
    kind: ["select", "reject", "marker"].includes(req.body.kind) ? req.body.kind : "marker",
    note: req.body.note || null,
    source: "editor",
    created_at: new Date().toISOString(),
  };
  markers.push(m);
  res.status(201).json(m);
});

router.delete("/media/:id/markers/:markerId", (req, res) => {
  const idx = markers.findIndex((m) => m.id === req.params.markerId && m.media_id === req.params.id);
  if (idx === -1) { res.status(404).json({ detail: "Marker not found" }); return; }
  markers.splice(idx, 1);
  res.status(204).send();
});

router.get("/media/:id/transcript", (req, res) => {
  const lang = typeof req.query.lang === "string" ? req.query.lang : null;
  const segments = transcript
    .filter((s) => s.media_id === req.params.id)
    .map((s) => {
      const { translations, ...rest } = s;
      if (lang && translations?.[lang]) {
        return { ...rest, text: translations[lang] };
      }
      return rest;
    });
  res.json(segments);
});

router.patch("/media/:id/transcript/:segmentId", (req, res) => {
  const seg = transcript.find((s) => s.media_id === req.params.id && String(s.id) === req.params.segmentId);
  if (!seg) { res.status(404).json({ detail: "Segment not found" }); return; }
  const text = String(req.body?.text ?? "").trim();
  if (!text) { res.status(400).json({ detail: "Text cannot be empty" }); return; }
  const lang = String(req.body?.lang ?? "").trim().toLowerCase() || null;
  if (lang) {
    if (!seg.translations?.[lang]) {
      res.status(400).json({ detail: `No '${lang}' translation exists for this segment — run translation first` });
      return;
    }
    seg.translations[lang] = text;
  } else {
    seg.text = text;
  }
  const { translations, ...rest } = seg;
  res.json(lang ? { ...rest, text: translations![lang] } : rest);
});

router.get("/media/:id/faces", (req, res) => {
  res.json([]);
});

router.get("/media/:id/people", (req, res) => {
  const out: any[] = [];
  for (const p of people) {
    const apps = (personAppearances[p.id] ?? []).filter((a) => a.media_id === req.params.id);
    if (!apps.length) continue;
    const speakers = new Set(apps.map((a) => a.speaker_label).filter(Boolean));
    const speaking = transcript
      .filter((s) => s.media_id === req.params.id && speakers.has(s.speaker))
      .sort((a, b) => a.start_time - b.start_time)
      .map((s) => ({ start_time: s.start_time, end_time: s.end_time, text: s.text }));
    // Mock on-camera ranges: pad + merge the speaking spans when a face cluster exists.
    const onCamera: { start_time: number; end_time: number }[] = [];
    if (apps.some((a) => a.face_cluster_id)) {
      const spans = speaking.length
        ? speaking.map((s) => ({ start_time: Math.max(0, s.start_time - 3), end_time: s.end_time + 3 }))
        : apps
            .filter((a) => a.first_spoken_at != null)
            .map((a) => ({ start_time: Math.max(0, a.first_spoken_at - 5), end_time: a.first_spoken_at + 40 }));
      for (const s of spans.sort((a, b) => a.start_time - b.start_time)) {
        const last = onCamera[onCamera.length - 1];
        if (last && s.start_time <= last.end_time) last.end_time = Math.max(last.end_time, s.end_time);
        else onCamera.push({ ...s });
      }
    }
    out.push({
      person_id: p.id,
      display_name: p.display_name,
      thumbnail_url: p.thumbnail_url ?? apps.find((a) => a.thumbnail_url)?.thumbnail_url ?? null,
      speaker_label: apps.find((a) => a.speaker_label)?.speaker_label ?? null,
      speaking_seconds: apps.reduce((sum, a) => sum + (a.speaking_seconds ?? 0), 0),
      speaking,
      on_camera: onCamera,
    });
  }
  out.sort((a, b) => (b.speaking_seconds ?? 0) - (a.speaking_seconds ?? 0));
  res.json(out);
});

// ── Search ────────────────────────────────────────────────────────────────────
router.post("/search", (req, res) => {
  const query = (req.body.query || "").toLowerCase();
  const searchType: string = req.body.search_type || "combined";
  const mediaIds: string[] | null = Array.isArray(req.body.media_ids) && req.body.media_ids.length ? req.body.media_ids : null;
  const inPool = (id: string) =>
    (!mediaIds || mediaIds.includes(id)) && (!req.body.media_id || req.body.media_id === id);
  const results: {
    media_id: string; filename: string; thumbnail_url: string | null;
    start_time: number; end_time: number; score: number;
    match_type: string; snippet: string | null;
  }[] = [];

  if (searchType === "transcript" || searchType === "combined") {
    for (const s of transcript) {
      if (!inPool(s.media_id)) continue;
      if (!s.text.toLowerCase().includes(query.split(" ")[0] || query)) continue;
      const asset = assets.find((a) => a.id === s.media_id);
      results.push({
        media_id: s.media_id,
        filename: asset?.filename || "unknown",
        thumbnail_url: null,
        start_time: s.start_time,
        end_time: s.end_time,
        score: 0.72 + Math.random() * 0.25,
        match_type: "transcript",
        snippet: s.text,
      });
    }
  }

  if (searchType === "visual" || searchType === "combined") {
    // Keyword match against scene descriptions stands in for CLIP visual search.
    const words = query.split(/\W+/).filter((w: string) => w.length > 2);
    for (const sc of scenes) {
      if (!inPool(sc.media_id)) continue;
      const desc = (sc.description || "").toLowerCase();
      if (!words.length || !words.some((w: string) => desc.includes(w))) continue;
      const asset = assets.find((a) => a.id === sc.media_id);
      results.push({
        media_id: sc.media_id,
        filename: asset?.filename || "unknown",
        thumbnail_url: sc.thumbnail_url,
        start_time: sc.start_time,
        end_time: sc.end_time,
        score: 0.6 + Math.random() * 0.3,
        match_type: "visual",
        snippet: sc.description,
      });
    }
  }

  results.sort((a, b) => b.score - a.score);
  if (req.body.query && String(req.body.query).trim()) {
    searchHistory.unshift({
      id: `sh-${Date.now()}`,
      query: String(req.body.query).trim(),
      result_count: results.length,
      searched_at: new Date().toISOString(),
    });
    if (searchHistory.length > 20) searchHistory.length = 20;
  }
  setTimeout(() => res.json({ results, query: req.body.query, took_ms: 42 + Math.random() * 80 }), 150);
});

router.get("/search/history", (_req, res) => {
  res.json(searchHistory);
});

router.post("/search/reindex", (_req, res) => {
  res.status(202).json({ assets_queued: 3, jobs_created: 5 });
});

// ── Jobs ─────────────────────────────────────────────────────────────────────
router.post("/people/:id/reprofile", (req, res) => {
  const person = people.find((p) => p.id === req.params.id);
  if (!person) {
    res.status(404).json({ error: "Person not found" });
    return;
  }
  res.status(202).end();
});

const mockPersonPhotos: Record<string, { buf: Buffer; mime: string }> = {};

router.get("/thumbnails/:name", (req, res) => {
  const stored = mockPersonPhotos[req.params.name];
  if (!stored) {
    res.status(404).end();
    return;
  }
  res.set("Content-Type", stored.mime).send(stored.buf);
});

router.post("/people/:id/photo", upload.single("photo"), (req, res) => {
  const person = people.find((p) => p.id === req.params.id);
  if (!person) {
    res.status(404).json({ error: "Person not found" });
    return;
  }
  const file = (req as any).file;
  if (!file || !file.buffer?.length) {
    res.status(422).json({ error: "Empty photo upload" });
    return;
  }
  if (file.buffer.length > 15 * 1024 * 1024) {
    res.status(413).json({ error: "Photo too large (15 MB max)" });
    return;
  }
  const name = `mock_person_photo_${person.id}_${Date.now()}.jpg`;
  const old = person.thumbnail_url;
  mockPersonPhotos[name] = { buf: file.buffer, mime: file.mimetype || "image/jpeg" };
  person.thumbnail_url = name;
  person.updated_at = new Date().toISOString();
  if (old && mockPersonPhotos[old]) delete mockPersonPhotos[old];
  res.json(person);
});

router.delete("/people/:id/photo", (req, res) => {
  const person = people.find((p) => p.id === req.params.id);
  if (!person) {
    res.status(404).json({ error: "Person not found" });
    return;
  }
  const old = person.thumbnail_url;
  person.thumbnail_url = null;
  person.updated_at = new Date().toISOString();
  if (old && mockPersonPhotos[old]) delete mockPersonPhotos[old];
  res.json(person);
});

router.post("/people/:id/face-search", (req, res) => {
  const person = people.find((p) => p.id === req.params.id);
  if (!person) {
    res.status(404).json({ error: "Person not found" });
    return;
  }
  person.face_search = { status: "pending", queued_at: new Date().toISOString() };
  setTimeout(() => {
    person.face_search = {
      status: "done",
      searched_at: new Date().toISOString(),
      candidates: [
        {
          title: `${person.display_name} — Keynote at TechForward 2023`,
          link: "https://example.com/techforward-2023-speakers",
          source: "example.com",
          thumbnail: null,
        },
        {
          title: `Interview: ${person.display_name} on local AI infrastructure`,
          link: "https://example.com/interviews/local-ai",
          source: "example.com",
          thumbnail: null,
        },
        {
          title: "Panel discussion — Broadcast Media Summit",
          link: "https://example.com/panels/broadcast-summit",
          source: "example.com",
          thumbnail: null,
        },
      ],
    };
  }, 2500);
  res.status(202).end();
});

router.post("/people/reanalyze", (_req, res) => {
  res.status(202).json({ assets_queued: 3, jobs_created: 6 });
});

router.post("/jobs/cleanup", (req, res) => {
  const requested: string[] = Array.isArray(req.body?.statuses) && req.body.statuses.length
    ? req.body.statuses
    : ["success", "error", "cancelled"];
  const allowed = new Set(["success", "error", "cancelled"]);
  if (requested.some((s) => !allowed.has(s))) {
    res.status(422).json({ error: "Only finished statuses can be cleaned up" });
    return;
  }
  const statuses = new Set(requested);
  let deleted = 0;
  for (let i = jobs.length - 1; i >= 0; i--) {
    if (statuses.has((jobs[i] as any).status)) {
      jobs.splice(i, 1);
      deleted++;
    }
  }
  res.json({ deleted });
});

router.get("/jobs", (req, res) => {
  const status = req.query.status as string | undefined;
  res.json(status ? jobs.filter((j: any) => j.status === status) : jobs);
});

router.post("/media/resume-stalled", (_req, res) => {
  res.status(202).json({ assets_resumed: 3, jobs_created: 5, assets_marked_ready: 1 });
});

router.post("/jobs/retry-failed", (_req, res) => {
  let retried = 0;
  for (const j of jobs as any[]) {
    if (j.status === "error") {
      j.status = "pending";
      j.error_message = null;
      retried++;
    }
  }
  res.status(202).json({ retried });
});

router.get("/jobs/stats", (_req, res) => {
  const stageMap: Record<string, { pending: number; running: number; success: number; error: number }> = {};
  for (const j of jobs as any[]) {
    const s = (stageMap[j.job_type] ??= { pending: 0, running: 0, success: 0, error: 0 });
    if (j.status in s) s[j.status as keyof typeof s] += 1;
  }
  const totals = { pending: 0, running: 0, error: 0 };
  for (const s of Object.values(stageMap)) {
    totals.pending += s.pending;
    totals.running += s.running;
    totals.error += s.error;
  }
  const ready = assets.filter((a) => a.status === "ready").length;
  const errored = assets.filter((a) => a.status === "error").length;
  res.json({
    assets_total: assets.length,
    assets_ready: ready,
    assets_processing: assets.length - ready - errored,
    assets_error: errored,
    jobs_pending: totals.pending,
    jobs_running: totals.running,
    jobs_error: totals.error,
    stages: Object.entries(stageMap)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([job_type, s]) => ({ job_type, ...s })),
  });
});

router.get("/jobs/:id", (req, res) => {
  const job = jobs.find((j) => j.id === req.params.id);
  if (!job) { res.status(404).json({ error: "Not found" }); return; }
  res.json(job);
});

router.post("/jobs/:id/retry", (req, res) => {
  const job = jobs.find((j) => j.id === req.params.id);
  if (!job) { res.status(404).json({ error: "Not found" }); return; }
  res.status(202).json({ ...job, status: "pending", retry_count: job.retry_count + 1 });
});

router.post("/jobs/:id/cancel", (req, res) => {
  const job = jobs.find((j) => j.id === req.params.id);
  if (!job) { res.status(404).json({ error: "Not found" }); return; }
  res.json({ ...job, status: "cancelled" });
});

// ── Highlight reel ───────────────────────────────────────────────────────────
router.post("/media/:id/highlight", (req, res) => {
  const asset = assets.find((a) => a.id === req.params.id);
  if (!asset) { res.status(404).json({ error: "Media not found" }); return; }
  if (!asset.key_moments || asset.key_moments.length === 0) {
    res.status(400).json({ detail: "No key moments available — run AI analysis first" });
    return;
  }
  const job = {
    id: `job-hl-${Date.now()}`,
    media_id: asset.id,
    filename: asset.filename,
    job_type: "highlight",
    status: "running",
    progress: 10,
    error_message: null as string | null,
    logs: ["Building highlight reel", "Cutting 5 clips from source"],
    retry_count: 0,
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    finished_at: null as string | null,
  };
  jobs.unshift(job as any);
  // Simulate the worker: advance progress, then finish and set highlight_url.
  const timer = setInterval(() => {
    job.progress = Math.min(90, (job.progress ?? 0) + 25);
  }, 2000);
  setTimeout(() => {
    clearInterval(timer);
    job.status = "success";
    job.progress = 100;
    job.finished_at = new Date().toISOString();
    job.logs.push("Highlight reel ready: 5 clips");
    (asset as any).highlight_url = `${asset.id}.mp4`;
  }, 9000);
  res.status(202).json(job);
});

router.post("/media/:id/creative", (req, res) => {
  const asset = assets.find((a) => a.id === req.params.id);
  if (!asset) { res.status(404).json({ error: "Media not found" }); return; }
  const hasTranscript = transcript.some((s) => s.media_id === asset.id);
  if (!hasTranscript && !asset.synopsis) {
    res.status(400).json({ detail: "No transcript available — the creative pass needs a transcribed asset" });
    return;
  }
  const job = {
    id: `job-cr-${Date.now()}`,
    media_id: asset.id,
    filename: asset.filename,
    job_type: "creative",
    status: "running",
    progress: 10,
    error_message: null as string | null,
    logs: ["Creative pass over 2 transcript chunk(s)", "Mining soundbites and mapping story arc"],
    retry_count: 0,
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    finished_at: null as string | null,
  };
  jobs.unshift(job as any);
  const timer = setInterval(() => {
    job.progress = Math.min(90, (job.progress ?? 0) + 20);
  }, 2000);
  setTimeout(() => {
    clearInterval(timer);
    job.status = "success";
    job.progress = 100;
    job.finished_at = new Date().toISOString();
    job.logs.push("Creative pass complete: 6 beats, 5 clip suggestions, 6 editorial notes");
    if (!(asset as any).creative) {
      (asset as any).creative = (assets[0] as any).creative;
    }
  }, 9000);
  res.status(202).json(job);
});

router.post("/media/:id/social", (req, res) => {
  const asset = assets.find((a) => a.id === req.params.id);
  if (!asset) { res.status(404).json({ error: "Media not found" }); return; }
  if (!asset.synopsis) {
    res.status(400).json({ detail: "No transcript or analysis available — process the media first" });
    return;
  }
  const job = {
    id: `job-soc-${Date.now()}`,
    media_id: asset.id,
    filename: asset.filename,
    job_type: "social",
    status: "running",
    progress: 15,
    error_message: null as string | null,
    logs: ["Scoring social media potential for 5 platforms"],
    retry_count: 0,
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    finished_at: null as string | null,
  };
  jobs.unshift(job as any);
  const timer = setInterval(() => {
    job.progress = Math.min(90, (job.progress ?? 0) + 25);
  }, 2000);
  setTimeout(() => {
    clearInterval(timer);
    job.status = "success";
    job.progress = 100;
    job.finished_at = new Date().toISOString();
    job.logs.push("Social scoring complete for 5 platforms");
    if (!(asset as any).social_scores) {
      (asset as any).social_scores = assets[0].social_scores;
    }
  }, 8000);
  res.status(202).json(job);
});

const SUPPORTED_LANGS = ["es", "fr", "de", "pt", "it", "nl", "ru", "ja", "ko", "zh", "ar", "hi"];

router.post("/media/:id/translate", (req, res) => {
  const asset = assets.find((a) => a.id === req.params.id);
  if (!asset) { res.status(404).json({ error: "Media not found" }); return; }
  const lang = String(req.body?.target_language ?? "").trim().toLowerCase();
  if (!SUPPORTED_LANGS.includes(lang)) {
    res.status(400).json({ detail: `Unsupported language '${lang}'. Supported: ${SUPPORTED_LANGS.join(", ")}` });
    return;
  }
  const hasTranscript = transcript.some((s) => s.media_id === asset.id);
  if (!hasTranscript) {
    res.status(400).json({ detail: "No transcript available — process the media first" });
    return;
  }
  const job = {
    id: `job-tr-${Date.now()}`,
    media_id: asset.id,
    filename: asset.filename,
    job_type: "translate",
    status: "running",
    progress: 10,
    error_message: null as string | null,
    logs: [`Target language: ${lang}`, `Translating ${transcript.length} segments to '${lang}'`],
    retry_count: 0,
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    finished_at: null as string | null,
  };
  jobs.unshift(job as any);
  const timer = setInterval(() => {
    job.progress = Math.min(90, (job.progress ?? 0) + 25);
  }, 2000);
  setTimeout(() => {
    clearInterval(timer);
    job.status = "success";
    job.progress = 100;
    job.finished_at = new Date().toISOString();
    job.logs.push(`Translation to '${lang}' complete`);
    for (const seg of transcript) {
      if (seg.media_id !== asset.id) continue;
      seg.translations = seg.translations ?? {};
      if (!seg.translations[lang]) {
        seg.translations[lang] = `[${lang.toUpperCase()}] ${seg.text}`;
      }
    }
    const langs = new Set((asset as any).translated_languages ?? []);
    langs.add(lang);
    (asset as any).translated_languages = Array.from(langs);
  }, 8000);
  res.status(202).json(job);
});

const DUB_LANGS = ["es", "fr", "de", "pt", "nl", "ru", "ko", "ar", "hi"];

router.post("/media/:id/dub", (req, res) => {
  const asset = assets.find((a) => a.id === req.params.id);
  if (!asset) { res.status(404).json({ error: "Media not found" }); return; }
  const lang = String(req.body?.target_language ?? "").trim().toLowerCase();
  if (!DUB_LANGS.includes(lang)) {
    res.status(400).json({ detail: `Dubbing not supported for '${lang}'. Supported: ${DUB_LANGS.join(", ")}` });
    return;
  }
  if (!((asset as any).translated_languages ?? []).includes(lang)) {
    res.status(400).json({ detail: `Transcript not translated to '${lang}' yet — run translation first` });
    return;
  }
  const job = {
    id: `job-dub-${Date.now()}`,
    media_id: asset.id,
    filename: asset.filename,
    job_type: "dub",
    status: "running",
    progress: 10,
    error_message: null as string | null,
    logs: [
      `Target language: ${lang}`,
      `Loading TTS model: facebook/mms-tts-${lang}`,
      ...(req.body?.lip_sync ? ["Lip sync enabled — Wav2Lip pass will run after audio render"] : []),
    ],
    retry_count: 0,
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    finished_at: null as string | null,
  };
  jobs.unshift(job as any);
  const timer = setInterval(() => {
    job.progress = Math.min(90, (job.progress ?? 0) + 20);
  }, 2000);
  setTimeout(() => {
    clearInterval(timer);
    job.status = "success";
    job.progress = 100;
    job.finished_at = new Date().toISOString();
    job.logs.push(`Dubbed audio track for '${lang}' complete`);
    const langs = new Set((asset as any).dubbed_languages ?? []);
    langs.add(lang);
    (asset as any).dubbed_languages = Array.from(langs);
  }, 8000);
  res.status(202).json(job);
});

router.get("/media/:id/dub/:lang/video", (req, res) => {
  const asset = assets.find((a) => a.id === req.params.id);
  const lang = String(req.params.lang ?? "").toLowerCase();
  if (!asset || !((asset as any).dubbed_languages ?? []).includes(lang)) {
    res.status(404).json({ error: "No dub for this language" });
    return;
  }
  // No real media in the mock environment — the production API streams the
  // muxed dubbed MP4. Redirect to the regular stream so the player toggle
  // can be exercised.
  res.redirect(307, `/api/media/${req.params.id}/stream`);
});

router.get("/media/:id/frame", (_req, res) => {
  // No real media in the mock environment — the production API extracts the
  // frame with ffmpeg. 404 lets the UI fall back to the scene thumbnail/icon.
  res.status(404).json({ detail: "Frame extraction requires real media (production only)" });
});

router.get("/media/:id/dub/:lang/stream", (req, res) => {
  const asset = assets.find((a) => a.id === req.params.id);
  const lang = String(req.params.lang ?? "").toLowerCase();
  if (!asset || !((asset as any).dubbed_languages ?? []).includes(lang)) {
    res.status(404).json({ error: "No dubbed audio for this language" });
    return;
  }
  // No real TTS in the mock environment — serve a silent WAV matching the
  // asset duration so the player toggle can be exercised end-to-end.
  const sampleRate = 8000;
  const seconds = Math.min(Math.ceil((asset as any).duration_seconds ?? 60), 3600);
  const dataSize = sampleRate * seconds * 2;
  const header = Buffer.alloc(44);
  header.write("RIFF", 0);
  header.writeUInt32LE(36 + dataSize, 4);
  header.write("WAVE", 8);
  header.write("fmt ", 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(1, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(sampleRate * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write("data", 36);
  header.writeUInt32LE(dataSize, 40);
  res.setHeader("Content-Type", "audio/wav");
  res.setHeader("Content-Length", String(44 + dataSize));
  res.write(header);
  res.end(Buffer.alloc(dataSize));
});

router.get("/media/:id/highlight/stream", (req, res) => {
  const asset = assets.find((a) => a.id === req.params.id);
  if (!asset || !(asset as any).highlight_url) {
    res.status(404).json({ error: "No highlight reel available" });
    return;
  }
  // No real video in the mock environment.
  res.status(404).json({ error: "Highlight reel file missing (mock)" });
});

// ── AI ────────────────────────────────────────────────────────────────────────
const conversationMessages: Record<string, any[]> = {
  "conv-001": [
    { id: "msg-001", conversation_id: "conv-001", role: "user", content: "What did Sarah Chen say about cloud infrastructure?", citations: null, created_at: new Date(Date.now() - 3600000).toISOString() },
    { id: "msg-002", conversation_id: "conv-001", role: "assistant", content: "Sarah Chen argued that cloud infrastructure is not required for petabyte-scale video processing. She noted: \"With modern GPU hardware and the right software architecture, you can build a fully local AI inference stack that outperforms cloud solutions on throughput.\"", citations: [{ media_id: "asset-001", filename: "interview_sarah_chen.mp4", start_time: 50.0, end_time: 71.3, snippet: "With modern GPU hardware and the right software architecture..." }], created_at: new Date(Date.now() - 3590000).toISOString() },
  ],
};

router.post("/ai/ask", (req, res) => {
  const convId = req.body.conversation_id || `conv-${Date.now()}`;
  if (!conversations.find(c => c.id === convId)) {
    conversations.unshift({
      id: convId,
      title: String(req.body.question || "").slice(0, 80),
      created_at: new Date().toISOString(),
      message_count: 0,
    });
  }
  const scopedAsset = req.body.media_id
    ? assets.find((a) => a.id === req.body.media_id)
    : null;
  const citeAsset = scopedAsset ?? assets[0];
  const answer = scopedAsset
    ? `Looking only at ${scopedAsset.filename}, here is what I found for: "${req.body.question}"\n\nAround 50 seconds in, the speaker notes: "With modern GPU hardware and the right software architecture, you can build a fully local AI inference stack that outperforms cloud solutions on throughput."\n\nThis is the most relevant passage in this video.`
    : `Based on the indexed transcripts, I found relevant content related to your question: "${req.body.question}"\n\nIn the interview with Sarah Chen (interview_sarah_chen.mp4), she discusses this topic extensively starting around 50 seconds in, noting: "With modern GPU hardware and the right software architecture, you can build a fully local AI inference stack that outperforms cloud solutions on throughput."\n\nThis appears to be the most relevant passage in the current library.`;
  const citations = [
    {
      media_id: citeAsset.id,
      filename: citeAsset.filename,
      start_time: 50.0,
      end_time: 71.3,
      snippet: "With modern GPU hardware and the right software architecture, you can build a fully local AI inference stack that outperforms cloud solutions on throughput.",
    },
  ];
  const msgs = conversationMessages[convId] || (conversationMessages[convId] = []);
  msgs.push(
    { id: `msg-${Date.now()}-u`, conversation_id: convId, role: "user", content: req.body.question, citations: null, created_at: new Date().toISOString() },
    { id: `msg-${Date.now()}-a`, conversation_id: convId, role: "assistant", content: answer, citations, created_at: new Date().toISOString() },
  );
  const conv = conversations.find(c => c.id === convId);
  if (conv) conv.message_count = msgs.length;
  setTimeout(() => {
    res.json({ answer, conversation_id: convId, citations });
  }, 800);
});

router.get("/ai/conversations", (_req, res) => {
  res.json(conversations);
});

router.delete("/ai/conversations/:id", (req, res) => {
  const idx = conversations.findIndex(c => c.id === req.params.id);
  if (idx === -1) {
    res.status(404).json({ detail: "Conversation not found" });
    return;
  }
  conversations.splice(idx, 1);
  delete conversationMessages[req.params.id];
  res.status(204).end();
});

router.get("/ai/conversations/:id/messages", (req, res) => {
  const msgs = conversationMessages[req.params.id];
  if (!msgs) {
    res.status(404).json({ detail: "Conversation not found" });
    return;
  }
  res.json(msgs);
});

// ── Projects ──────────────────────────────────────────────────────────────────
function projectOut(p: MockProject) {
  return {
    ...p,
    counts: {
      clip_lists: clipLists.filter((c) => c.project_id === p.id).length,
      stories: stories.filter((s) => s.project_id === p.id).length,
      reels: reels.filter((r) => r.project_id === p.id).length,
      renders: renders.filter((r) => r.project_id === p.id).length,
    },
  };
}

router.get("/projects", (_req, res) => {
  res.json(projects.map(projectOut));
});

router.post("/projects", (req, res) => {
  const name = (req.body?.name || "").trim();
  if (!name) { res.status(400).json({ detail: "Name is required" }); return; }
  const p: MockProject = {
    id: `proj-${Date.now()}`,
    name,
    description: req.body?.description || null,
    script: req.body?.script || null,
    status: "active",
    media_ids: Array.isArray(req.body?.media_ids) ? req.body.media_ids : [],
    created_at: new Date().toISOString(),
    updated_at: null,
  };
  projects.unshift(p);
  res.status(201).json(projectOut(p));
});

router.get("/projects/:id", (req, res) => {
  const p = projects.find((x) => x.id === req.params.id);
  if (!p) { res.status(404).json({ detail: "Project not found" }); return; }
  res.json(projectOut(p));
});

router.patch("/projects/:id", (req, res) => {
  const p = projects.find((x) => x.id === req.params.id);
  if (!p) { res.status(404).json({ detail: "Project not found" }); return; }
  if (req.body.name !== undefined) p.name = req.body.name;
  if (req.body.description !== undefined) p.description = req.body.description;
  if (req.body.script !== undefined) p.script = req.body.script;
  if (req.body.status === "active" || req.body.status === "archived") p.status = req.body.status;
  if (req.body.media_ids !== undefined) p.media_ids = Array.isArray(req.body.media_ids) ? req.body.media_ids : [];
  p.updated_at = new Date().toISOString();
  res.json(projectOut(p));
});

router.delete("/projects/:id", (req, res) => {
  const idx = projects.findIndex((x) => x.id === req.params.id);
  if (idx === -1) { res.status(404).json({ detail: "Project not found" }); return; }
  const pid = projects[idx].id;
  projects.splice(idx, 1);
  clipLists.forEach((c) => { if (c.project_id === pid) c.project_id = null; });
  stories.forEach((s) => { if (s.project_id === pid) s.project_id = null; });
  reels.forEach((r) => { if (r.project_id === pid) r.project_id = null; });
  renders.forEach((r) => { if (r.project_id === pid) r.project_id = null; });
  res.status(204).send();
});

// ── Clips ─────────────────────────────────────────────────────────────────────
router.get("/clips", (req, res) => {
  const pid = typeof req.query.project_id === "string" ? req.query.project_id : null;
  res.json(pid ? clipLists.filter((c) => c.project_id === pid) : clipLists);
});

router.post("/clips", (req, res) => {
  const newList = {
    id: `cl-${Date.now()}`,
    name: req.body.name,
    description: req.body.description || null,
    project_id: (req.body.project_id as string | null) || null,
    locked: false,
    created_at: new Date().toISOString(),
    clips: (req.body.clips || []).map((c: any, i: number) => mapClipInput(c, i, Date.now())),
  };
  clipLists.unshift(newList);
  touchProject(newList.project_id);
  res.status(201).json(newList);
});

router.get("/clips/:id", (req, res) => {
  const cl = clipLists.find((c) => c.id === req.params.id);
  if (!cl) { res.status(404).json({ error: "Not found" }); return; }
  res.json(cl);
});

router.patch("/clips/:id", (req, res) => {
  const cl = clipLists.find((c) => c.id === req.params.id);
  if (!cl) { res.status(404).json({ error: "Not found" }); return; }
  if (req.body.locked !== undefined) (cl as any).locked = !!req.body.locked;
  const mutating = req.body.name !== undefined || req.body.description !== undefined || req.body.project_id !== undefined || req.body.clips !== undefined;
  if ((cl as any).locked && mutating) {
    res.status(423).json({ detail: "Clip list is picture-locked. Unlock it to make changes." });
    return;
  }
  if (req.body.name !== undefined) cl.name = req.body.name;
  if (req.body.description !== undefined) cl.description = req.body.description;
  if (req.body.project_id !== undefined) cl.project_id = req.body.project_id;
  if (req.body.clips !== undefined) {
    cl.clips = (req.body.clips || []).map((c: any, i: number) => mapClipInput(c, i, Date.now()));
  }
  touchProject(cl.project_id);
  res.json(cl);
});

router.delete("/clips/:id", (req, res) => {
  const cl = clipLists.find((c) => c.id === req.params.id);
  if (cl && (cl as any).locked) {
    res.status(423).json({ detail: "Clip list is picture-locked. Unlock it to delete." });
    return;
  }
  res.status(204).send();
});

router.post("/clips/:id/export", (req, res) => {
  const cl = clipLists.find((c) => c.id === req.params.id);
  if (!cl) { res.status(404).json({ error: "Not found" }); return; }
  const fmt = req.body.format || "json";
  const content = fmt === "json"
    ? JSON.stringify({ name: cl.name, clips: cl.clips }, null, 2)
    : fmt === "csv"
    ? ["clip_id,filename,start_time,end_time,label", ...cl.clips.map((c) => `${c.id},${c.filename},${c.start_time},${c.end_time},${c.label || ""}`)].join("\n")
    : fmt === "fcpxml"
    ? `<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n<fcpxml version="1.9">\n  <resources>\n    <format id="r1" name="FFVideoFormat1080p25" frameDuration="1/25s" width="1920" height="1080"/>\n${[...new Set(cl.clips.map((c) => c.filename))].map((f, i) => `    <asset id="r${i + 2}" name="${f}" start="0s" hasVideo="1" hasAudio="1" format="r1"/>`).join("\n")}\n  </resources>\n  <library>\n    <event name="${cl.name}">\n      <project name="${cl.name}">\n        <sequence format="r1">\n          <spine>\n${cl.clips.map((c) => `            <asset-clip name="${c.label || c.filename}" start="${Math.round(c.start_time * 25)}/25s" duration="${Math.round((c.end_time - c.start_time) * 25)}/25s" format="r1"/>`).join("\n")}\n          </spine>\n        </sequence>\n      </project>\n    </event>\n  </library>\n</fcpxml>\n`
    : fmt === "otio"
    ? JSON.stringify({
        OTIO_SCHEMA: "Timeline.1",
        name: cl.name,
        tracks: {
          OTIO_SCHEMA: "Stack.1", name: "tracks",
          children: [{
            OTIO_SCHEMA: "Track.1", name: "V1", kind: "Video",
            children: cl.clips.map((c) => ({
              OTIO_SCHEMA: "Clip.2",
              name: c.label || c.filename,
              source_range: {
                OTIO_SCHEMA: "TimeRange.1",
                start_time: { OTIO_SCHEMA: "RationalTime.1", rate: 25, value: c.start_time * 25 },
                duration: { OTIO_SCHEMA: "RationalTime.1", rate: 25, value: (c.end_time - c.start_time) * 25 },
              },
              media_references: { DEFAULT_MEDIA: { OTIO_SCHEMA: "ExternalReference.1", target_url: c.filename } },
              active_media_reference_key: "DEFAULT_MEDIA",
            })),
          }],
        },
      }, null, 2)
    : `TITLE: ${cl.name}\nFCM: NON-DROP FRAME\n`;
  res.json({ format: fmt, content, filename: `${cl.name.replace(/ /g, "_")}.${fmt}` });
});

// ── Renders & publishing ─────────────────────────────────────────────────────

type MockRender = {
  id: string; media_id: string; filename: string | null; clip_list_id: string | null;
  project_id: string | null;
  label: string | null; start_time: number; end_time: number;
  preset: string; burn_captions: boolean; unreviewed: boolean; status: string; progress: number;
  output_url: string | null; error_message: string | null;
  publish_status: string | null; publish_url: string | null; publish_error: string | null;
  publish_stats: { platform: string; views: number; likes: number; comments: number; fetched_at: string } | null;
  created_at: string; finished_at: string | null;
  _startedAt: number; _publishStartedAt: number | null;
};

const renders: MockRender[] = [];

function makeRender(mediaId: string, start: number, end: number, preset: string, burnCaptions: boolean, label: string | null, clipListId: string | null, projectId: string | null = null, unreviewed = false): MockRender {
  touchProject(projectId);
  return {
    id: `render-${Date.now()}-${Math.floor(Math.random() * 10000)}`,
    media_id: mediaId,
    filename: assets.find((a) => a.id === mediaId)?.filename || null,
    clip_list_id: clipListId,
    project_id: projectId,
    label,
    start_time: start,
    end_time: end,
    preset,
    burn_captions: burnCaptions,
    unreviewed,
    status: "pending",
    progress: 0,
    output_url: null,
    error_message: null,
    publish_status: null,
    publish_url: null,
    publish_error: null,
    publish_stats: null,
    created_at: new Date().toISOString(),
    finished_at: null,
    _startedAt: Date.now(),
    _publishStartedAt: null,
  };
}

// Simulate render + publish progress based on elapsed time.
function tickRender(r: MockRender) {
  if (r.status === "pending" || r.status === "running") {
    const elapsed = (Date.now() - r._startedAt) / 1000;
    if (elapsed < 1.5) {
      r.status = "pending";
    } else if (elapsed < 10) {
      r.status = "running";
      r.progress = Math.min(99, Math.round(((elapsed - 1.5) / 8.5) * 100));
    } else {
      r.status = "success";
      r.progress = 100;
      r.finished_at = new Date().toISOString();
      r.output_url = `/api/renders/${r.id}/download`;
    }
  }
  if (r.publish_status === "pending" || r.publish_status === "running") {
    const elapsed = (Date.now() - (r._publishStartedAt || Date.now())) / 1000;
    if (elapsed < 1) {
      r.publish_status = "pending";
    } else if (elapsed < 6) {
      r.publish_status = "running";
    } else {
      r.publish_status = "success";
      r.publish_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";
      r.publish_stats = { platform: "youtube", views: 1834, likes: 97, comments: 12, fetched_at: new Date().toISOString() };
    }
  }
}

function renderOut(r: MockRender) {
  const { _startedAt, _publishStartedAt, ...out } = r;
  return out;
}

router.post("/clips/:id/render", (req, res) => {
  const cl = clipLists.find((c) => c.id === req.params.id);
  if (!cl) { res.status(404).json({ detail: "Clip list not found" }); return; }
  if (!cl.clips.length) { res.status(400).json({ detail: "Clip list has no clips" }); return; }
  const preset = req.body.preset || "original";
  const burn = !!req.body.burn_captions;
  const unreviewed = !cl.clips.every((c) => c.approved);
  const created = cl.clips.map((c) => makeRender(c.media_id, c.start_time, c.end_time, preset, burn, c.label, cl.id, cl.project_id ?? null, unreviewed));
  renders.unshift(...created);
  res.status(202).json(created.map(renderOut));
});

router.get("/renders", (req, res) => {
  renders.forEach(tickRender);
  let out = renders;
  if (req.query.clip_list_id) out = out.filter((r) => r.clip_list_id === req.query.clip_list_id);
  if (req.query.media_id) out = out.filter((r) => r.media_id === req.query.media_id);
  if (req.query.project_id) out = out.filter((r) => r.project_id === req.query.project_id);
  res.json(out.map(renderOut));
});

router.post("/renders", (req, res) => {
  const asset = assets.find((a) => a.id === req.body.media_id);
  if (!asset) { res.status(404).json({ detail: "Media not found" }); return; }
  const r = makeRender(
    req.body.media_id, req.body.start_time, req.body.end_time,
    req.body.preset || "original", !!req.body.burn_captions,
    req.body.label || null, req.body.clip_list_id || null, req.body.project_id || null,
  );
  renders.unshift(r);
  res.status(202).json(renderOut(r));
});

router.get("/renders/publish/platforms", (_req, res) => {
  res.json({ youtube: true });
});

router.get("/renders/:id", (req, res) => {
  const r = renders.find((x) => x.id === req.params.id);
  if (!r) { res.status(404).json({ detail: "Render not found" }); return; }
  tickRender(r);
  res.json(renderOut(r));
});

router.delete("/renders/:id", (req, res) => {
  const idx = renders.findIndex((x) => x.id === req.params.id);
  if (idx === -1) { res.status(404).json({ detail: "Render not found" }); return; }
  renders.splice(idx, 1);
  res.status(204).send();
});

router.get("/renders/:id/download", (req, res) => {
  const r = renders.find((x) => x.id === req.params.id);
  if (!r) { res.status(404).json({ detail: "Render not found" }); return; }
  tickRender(r);
  if (r.status !== "success") { res.status(404).json({ detail: "Render output not available" }); return; }
  // Tiny placeholder payload; the production API streams the real MP4.
  const name = `${(r.label || "clip").replace(/ /g, "_")}_${r.id.slice(-8)}.mp4`;
  res.setHeader("Content-Type", "video/mp4");
  res.setHeader("Content-Disposition", `attachment; filename="${name}"`);
  res.send(Buffer.from("mock mp4 output — real file is produced by the production render worker"));
});

router.post("/renders/:id/publish", (req, res) => {
  const r = renders.find((x) => x.id === req.params.id);
  if (!r) { res.status(404).json({ detail: "Render not found" }); return; }
  tickRender(r);
  if (r.status !== "success") { res.status(400).json({ detail: "Render is not finished yet" }); return; }
  if (r.publish_status === "pending" || r.publish_status === "running") {
    res.status(400).json({ detail: "Publish already in progress" });
    return;
  }
  r.publish_status = "pending";
  r.publish_url = null;
  r.publish_error = null;
  r._publishStartedAt = Date.now();
  res.status(202).json(renderOut(r));
});

// ── Social cuts ──────────────────────────────────────────────────────────────

const SOCIAL_CUT_SPECS: Record<string, { preset: string; burn: boolean; seconds: number }> = {
  youtube: { preset: "original", burn: false, seconds: 60 },
  facebook: { preset: "original", burn: false, seconds: 60 },
  x: { preset: "original", burn: true, seconds: 40 },
  instagram: { preset: "vertical", burn: true, seconds: 45 },
  tiktok: { preset: "vertical", burn: true, seconds: 30 },
};

router.post("/media/:id/social/cuts", (req, res) => {
  const asset = assets.find((a) => a.id === req.params.id);
  if (!asset) { res.status(404).json({ detail: "Media not found" }); return; }
  if (!asset.key_moments || !asset.key_moments.length) {
    res.status(400).json({ detail: "No key moments available — run AI analysis first" });
    return;
  }
  const requested = req.body?.platform ?? null;
  if (requested !== null && !SOCIAL_CUT_SPECS[requested]) {
    res.status(400).json({ detail: `Unknown platform: ${requested}` });
    return;
  }
  const platforms = requested
    ? [requested]
    : (asset.social_scores?.map((s: any) => s.platform).filter((p: string) => SOCIAL_CUT_SPECS[p])
        ?? Object.keys(SOCIAL_CUT_SPECS));
  const duration = asset.duration_seconds || 0;
  const moments = asset.key_moments
    .filter((m) => typeof m.time === "number" && m.time >= 0 && (!duration || m.time < duration))
    .slice(0, 3);
  if (!moments.length) { res.status(400).json({ detail: "Key moments did not yield any usable cuts" }); return; }

  const created: MockRender[] = [];
  for (const platform of platforms) {
    const spec = SOCIAL_CUT_SPECS[platform];
    for (const m of moments) {
      const start = Math.max(0, m.time - 1);
      const end = duration ? Math.min(start + spec.seconds, duration) : start + spec.seconds;
      if (end - start < 3) continue;
      created.push(makeRender(asset.id, start, end, spec.preset, spec.burn, `${platform}: ${m.title}`, null));
    }
  }
  if (!created.length) { res.status(400).json({ detail: "No usable cut windows for this asset" }); return; }
  renders.unshift(...created);
  res.status(202).json(created.map(renderOut));
});

// ── Reels (prompt-based highlight reels) ─────────────────────────────────────

type MockReel = {
  id: string; prompt: string; media_id: string | null; project_id: string | null;
  target_duration_seconds: number | null;
  preset: string; burn_captions: boolean; unreviewed: boolean;
  clips: { media_id: string; filename: string; start_time: number; end_time: number; snippet: string | null; thumbnail_url: string | null }[];
  status: string; progress: number;
  output_url: string | null; error_message: string | null;
  created_at: string; finished_at: string | null;
  _startedAt: number;
};

const reels: MockReel[] = [];

function nearestSceneThumb(mediaId: string, startTime: number): string | null {
  const scene = scenes
    .filter((sc) => sc.media_id === mediaId && sc.start_time <= startTime)
    .sort((a, b) => b.start_time - a.start_time)[0];
  return scene?.thumbnail_url ?? assets.find((a) => a.id === mediaId)?.thumbnail_url ?? null;
}

function tickReel(r: MockReel) {
  if (r.status !== "pending" && r.status !== "running") return;
  const elapsed = (Date.now() - r._startedAt) / 1000;
  if (elapsed < 1.5) {
    r.status = "pending";
  } else if (elapsed < 12) {
    r.status = "running";
    r.progress = Math.min(99, Math.round(((elapsed - 1.5) / 10.5) * 100));
  } else {
    r.status = "success";
    r.progress = 100;
    r.finished_at = new Date().toISOString();
    r.output_url = `/api/reels/${r.id}/download`;
  }
}

function reelOut(r: MockReel) {
  const { _startedAt, ...out } = r;
  return out;
}

router.get("/reels", (req, res) => {
  reels.forEach(tickReel);
  const mediaId = typeof req.query.media_id === "string" ? req.query.media_id : null;
  const pid = typeof req.query.project_id === "string" ? req.query.project_id : null;
  let list = mediaId ? reels.filter((r) => r.media_id === mediaId) : reels;
  if (pid) list = list.filter((r) => r.project_id === pid);
  res.json(list.map(reelOut));
});

router.post("/reels", (req, res) => {
  const prompt: string = (req.body.prompt || "").trim();
  if (prompt.length < 3) { res.status(400).json({ detail: "Prompt is too short" }); return; }
  const preset = req.body.preset || "original";
  const burn = !!req.body.burn_captions;
  const targetDuration: number | null =
    typeof req.body.target_duration_seconds === "number" && req.body.target_duration_seconds >= 30
      ? Math.min(req.body.target_duration_seconds, 14400)
      : null;
  // With a target run time the clip count is driven by the duration goal.
  const maxClips = targetDuration
    ? Math.min(Math.max(Math.ceil(targetDuration / 20), 3), 500)
    : Math.min(Math.max(req.body.max_clips || 6, 1), 500);
  const mediaId: string | null = req.body.media_id || null;
  if (mediaId && !assets.find((a) => a.id === mediaId)) {
    res.status(404).json({ detail: "Media asset not found" });
    return;
  }
  const reelMediaIds: string[] | null =
    Array.isArray(req.body.media_ids) && req.body.media_ids.length ? req.body.media_ids : null;
  const pool = transcript.filter((seg) =>
    mediaId ? seg.media_id === mediaId : !reelMediaIds || reelMediaIds.includes(seg.media_id));

  // Same keyword scoring the mock script-match uses.
  const words = prompt.toLowerCase().split(/\W+/).filter((w) => w.length > 3);
  const scored = pool
    .map((seg) => {
      const text = seg.text.toLowerCase();
      const hits = words.filter((w) => text.includes(w)).length;
      return { seg, score: words.length ? hits / words.length : 0 };
    })
    .filter((s) => s.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, maxClips);

  // For long-form targets, backfill beyond keyword hits so the runtime goal is reachable.
  let picked = scored.length ? scored.map((s) => s.seg) : pool.slice(0, Math.min(maxClips, 4));
  if (targetDuration && picked.length < maxClips) {
    const chosen = new Set(picked.map((s) => s.id));
    for (const seg of pool) {
      if (picked.length >= maxClips) break;
      if (!chosen.has(seg.id)) { picked.push(seg); chosen.add(seg.id); }
    }
  }
  if (!picked.length) {
    res.status(404).json({
      detail: mediaId
        ? "No moments in this video match that prompt — try different wording"
        : "No moments in the library match that prompt — try different wording",
    });
    return;
  }

  // Longer targets allow longer individual clips (up to 5 min each).
  const maxClipLen = targetDuration ? Math.min(300, Math.max(30, targetDuration / Math.max(picked.length, 1))) : 30;
  const clips = picked
    .map((seg) => {
      const asset = assets.find((a) => a.id === seg.media_id);
      const start = Math.max(0, seg.start_time - 1);
      const end = Math.max(start + 6, seg.end_time);
      const scene = scenes
        .filter((sc) => sc.media_id === seg.media_id && sc.start_time <= start)
        .sort((a, b) => b.start_time - a.start_time)[0];
      return {
        media_id: seg.media_id,
        filename: asset?.filename || "unknown.mp4",
        start_time: start,
        end_time: Math.min(end, start + maxClipLen),
        snippet: seg.text,
        thumbnail_url: scene?.thumbnail_url ?? asset?.thumbnail_url ?? null,
      };
    })
    .sort((a, b) => a.media_id.localeCompare(b.media_id) || a.start_time - b.start_time);

  const reel: MockReel = {
    id: `reel-${Date.now()}-${Math.floor(Math.random() * 10000)}`,
    prompt,
    media_id: mediaId,
    project_id: (req.body.project_id as string | null) || null,
    target_duration_seconds: targetDuration,
    preset,
    burn_captions: burn,
    unreviewed: false,
    clips,
    status: "pending",
    progress: 0,
    output_url: null,
    error_message: null,
    created_at: new Date().toISOString(),
    finished_at: null,
    _startedAt: Date.now(),
  };
  reels.unshift(reel);
  touchProject(reel.project_id);
  res.status(202).json(reelOut(reel));
});

router.get("/reels/:id", (req, res) => {
  const r = reels.find((x) => x.id === req.params.id);
  if (!r) { res.status(404).json({ detail: "Reel not found" }); return; }
  tickReel(r);
  res.json(reelOut(r));
});

router.delete("/reels/:id", (req, res) => {
  const idx = reels.findIndex((x) => x.id === req.params.id);
  if (idx === -1) { res.status(404).json({ detail: "Reel not found" }); return; }
  reels.splice(idx, 1);
  res.status(204).send();
});

router.get("/reels/:id/download", (req, res) => {
  const r = reels.find((x) => x.id === req.params.id);
  if (!r) { res.status(404).json({ detail: "Reel not found" }); return; }
  tickReel(r);
  if (r.status !== "success") { res.status(404).json({ detail: "Reel output not available" }); return; }
  const safe = r.prompt.slice(0, 40).replace(/[^a-zA-Z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "reel";
  res.setHeader("Content-Type", "video/mp4");
  res.setHeader("Content-Disposition", `attachment; filename="reel_${safe}_${r.id.slice(-8)}.mp4"`);
  res.send(Buffer.from("mock reel mp4 — real file is produced by the production reel worker"));
});

// ── Captions, tighten, rough cuts, stories ───────────────────────────────────

function captionTs(sec: number, vtt: boolean): string {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
  const ms = Math.round((sec % 1) * 1000);
  const pad = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${pad(h)}:${pad(m)}:${pad(s)}${vtt ? "." : ","}${pad(ms, 3)}`;
}

router.get("/media/:id/captions", (req, res) => {
  const asset = assets.find((a) => a.id === req.params.id);
  if (!asset) { res.status(404).json({ detail: "Media not found" }); return; }
  const fmt = String(req.query.format || "").toLowerCase();
  if (fmt !== "srt" && fmt !== "vtt") { res.status(400).json({ detail: "Format must be srt or vtt" }); return; }
  const lang = typeof req.query.lang === "string" ? req.query.lang : null;
  const segs = transcript.filter((s) => s.media_id === asset.id);
  if (!segs.length) { res.status(404).json({ detail: "No transcript available" }); return; }
  const vtt = fmt === "vtt";
  const lines: string[] = vtt ? ["WEBVTT", ""] : [];
  segs.forEach((s, i) => {
    const text = lang && s.translations?.[lang] ? s.translations[lang] : s.text;
    if (!vtt) lines.push(String(i + 1));
    lines.push(`${captionTs(s.start_time, vtt)} --> ${captionTs(s.end_time, vtt)}`);
    lines.push(s.speaker ? `${s.speaker}: ${text}` : text);
    lines.push("");
  });
  const stem = asset.filename.replace(/\.[^.]+$/, "");
  res.json({ format: fmt, content: lines.join("\n"), filename: `${stem}${lang ? "." + lang : ""}.${fmt}` });
});

const FILLERS = new Set(["um", "uh", "uhm", "erm", "er", "hmm", "hm", "mhm", "mm", "ah", "eh", "like", "so", "well", "right", "okay", "ok", "yeah"]);

router.post("/media/:id/tighten", (req, res) => {
  const asset = assets.find((a) => a.id === req.params.id);
  if (!asset) { res.status(404).json({ detail: "Media not found" }); return; }
  const threshold = Math.max(0.3, Number(req.body?.silence_threshold ?? 1.25));
  const removeFillers = req.body?.remove_fillers !== false;
  const segs = transcript.filter((s) => s.media_id === asset.id).sort((a, b) => a.start_time - b.start_time);
  if (!segs.length) { res.status(404).json({ detail: "No transcript available" }); return; }
  const duration = asset.duration_seconds || segs[segs.length - 1].end_time;

  const cuts: { start: number; end: number; reason: string }[] = [];
  const kept: [number, number][] = [];
  let cursor = 0;
  for (const s of segs) {
    if (s.start_time - cursor >= threshold) cuts.push({ start: cursor, end: s.start_time, reason: "silence" });
    const words = s.text.toLowerCase().replace(/[^a-z' ]/g, " ").split(/\s+/).filter(Boolean);
    const isFiller = removeFillers && words.length > 0 && words.length <= 4 && words.every((w) => FILLERS.has(w));
    if (isFiller) {
      cuts.push({ start: s.start_time, end: s.end_time, reason: "filler" });
      cursor = Math.max(cursor, s.end_time);
      continue;
    }
    const ps = Math.max(cursor, s.start_time - 0.15);
    const pe = Math.min(duration, s.end_time + 0.15);
    if (kept.length && ps - kept[kept.length - 1][1] < threshold) kept[kept.length - 1][1] = pe;
    else kept.push([ps, pe]);
    cursor = Math.max(cursor, s.end_time);
  }
  if (duration - cursor >= threshold) cuts.push({ start: cursor, end: duration, reason: "silence" });

  const removed = cuts.reduce((acc, c) => acc + (c.end - c.start), 0);
  const stem = asset.filename.replace(/\.[^.]+$/, "");
  const newList = {
    id: `cl-${Date.now()}`,
    name: `${stem} — tightened`,
    description: `Auto-tightened cut: ${cuts.length} cuts, ${removed.toFixed(1)}s removed`,
    created_at: new Date().toISOString(),
    clips: kept.map(([ks, ke], i) => ({
      id: `clip-${Date.now()}-${i}`,
      media_id: asset.id,
      filename: asset.filename,
      start_time: Math.round(ks * 100) / 100,
      end_time: Math.round(ke * 100) / 100,
      label: `Keep ${String(i + 1).padStart(2, "0")}`,
      notes: null,
      approved: false,
      match_reason: "Auto-tighten: kept speech segment between silence/filler cuts",
      thumbnail_url: asset.thumbnail_url ?? null,
    })),
  };
  clipLists.unshift(newList as any);
  res.status(201).json({
    media_id: asset.id,
    clip_list_id: newList.id,
    kept_segments: kept.length,
    cuts,
    removed_seconds: Math.round(removed * 100) / 100,
    original_duration: Math.round(duration * 100) / 100,
  });
});

function makeMockReel(prompt: string, mediaId: string | null, preset: string, burn: boolean, clips: MockReel["clips"], projectId: string | null = null, unreviewed = false): MockReel {
  touchProject(projectId);
  const reel: MockReel = {
    id: `reel-${Date.now()}-${Math.floor(Math.random() * 10000)}`,
    prompt, media_id: mediaId, project_id: projectId, target_duration_seconds: null, preset, burn_captions: burn, unreviewed, clips,
    status: "pending", progress: 0, output_url: null, error_message: null,
    created_at: new Date().toISOString(), finished_at: null, _startedAt: Date.now(),
  };
  reels.unshift(reel);
  return reel;
}

router.post("/media/:id/roughcut", (req, res) => {
  const asset = assets.find((a) => a.id === req.params.id);
  if (!asset) { res.status(404).json({ detail: "Media not found" }); return; }
  const preset = req.body?.preset || "original";
  if (preset !== "original" && preset !== "vertical") { res.status(400).json({ detail: "Preset must be original or vertical" }); return; }
  const suggestions = (asset as any).creative?.clip_suggestions || [];
  if (!suggestions.length) {
    res.status(409).json({ detail: "No creative clip suggestions yet — run the creative pass first" });
    return;
  }
  const clips = [...suggestions]
    .sort((a: any, b: any) => a.start - b.start)
    .map((c: any) => ({
      media_id: asset.id, filename: asset.filename,
      start_time: c.start, end_time: c.end, snippet: c.title || c.quote || null,
      thumbnail_url: nearestSceneThumb(asset.id, c.start),
    }));
  const reel = makeMockReel(`Rough cut — ${asset.filename}`, asset.id, preset, !!req.body?.burn_captions, clips);
  res.status(202).json(reelOut(reel));
});

router.post("/clips/:id/roughcut", (req, res) => {
  const cl = clipLists.find((c) => c.id === req.params.id);
  if (!cl) { res.status(404).json({ detail: "Clip list not found" }); return; }
  if (!cl.clips.length) { res.status(409).json({ detail: "Clip list is empty" }); return; }
  const preset = req.body?.preset || "original";
  if (preset !== "original" && preset !== "vertical") { res.status(400).json({ detail: "Preset must be original or vertical" }); return; }
  const clips = cl.clips.map((c) => ({
    media_id: c.media_id, filename: c.filename,
    start_time: c.start_time, end_time: c.end_time, snippet: c.label || null,
    thumbnail_url: nearestSceneThumb(c.media_id, c.start_time),
  }));
  const reel = makeMockReel(`Rough cut — ${cl.name}`, null, preset, !!req.body?.burn_captions, clips, cl.project_id ?? null, !cl.clips.every((c) => c.approved));
  res.status(202).json(reelOut(reel));
});

// ── Stories ──────────────────────────────────────────────────────────────────

type MockStory = {
  id: string; prompt: string | null; project_id: string | null; asset_ids: string[];
  status: string; progress: number;
  title: string | null; narrative: string | null; clip_list_id: string | null;
  error_message: string | null; created_at: string; finished_at: string | null;
  _startedAt: number;
};

const stories: MockStory[] = [];

function tickStory(s: MockStory) {
  if (s.status !== "pending" && s.status !== "running") return;
  const elapsed = (Date.now() - s._startedAt) / 1000;
  if (elapsed < 1.5) { s.status = "pending"; return; }
  if (elapsed < 14) {
    s.status = "running";
    s.progress = Math.min(99, Math.round(((elapsed - 1.5) / 12.5) * 100));
    return;
  }
  s.status = "success";
  s.progress = 100;
  s.finished_at = new Date().toISOString();
  s.title = s.title || "Downtown at a Crossroads";
  s.narrative = s.narrative ||
    "The cut opens on the mandate to set stakes, moves through the affordability math and the merchant conflict, and closes on the ballot deadline. Interleaving the field-report reaction against the planner's data rebuttal turns two separate videos into one argument, and the bond-measure close gives the piece a ticking clock.";
  if (!s.clip_list_id) {
    const picked: any[] = [];
    for (const mid of s.asset_ids) {
      const a = assets.find((x) => x.id === mid);
      const sugg = (a as any)?.creative?.clip_suggestions || [];
      const source = sugg.length
        ? sugg.slice(0, 3).map((c: any) => ({ start: c.start, end: c.end, label: c.title, reason: c.reason ? `Story beat: ${c.reason}` : "Story beat: strong clip suggestion from analysis" }))
        : transcript.filter((t) => t.media_id === mid).slice(0, 2).map((t) => ({ start: Math.max(0, t.start_time - 1), end: t.end_time + 1, label: t.text.slice(0, 60), reason: `Transcript match: "${t.text.slice(0, 80)}…"` }));
      for (const c of source) picked.push({ media_id: mid, filename: a?.filename || "unknown.mp4", thumbnail_url: a?.thumbnail_url ?? null, ...c });
    }
    const newList = {
      id: `cl-${Date.now()}`,
      name: `Story — ${s.title}`,
      description: s.narrative,
      project_id: s.project_id,
      created_at: new Date().toISOString(),
      clips: picked.map((c, i) => ({
        id: `clip-${Date.now()}-${i}`,
        media_id: c.media_id, filename: c.filename,
        start_time: c.start, end_time: c.end, label: c.label || null, notes: null,
        approved: false, match_reason: c.reason || null, thumbnail_url: c.thumbnail_url ?? null,
      })),
    };
    clipLists.unshift(newList as any);
    s.clip_list_id = newList.id;
  }
}

function storyOut(s: MockStory) {
  const { _startedAt, ...out } = s;
  return out;
}

router.get("/stories", (req, res) => {
  stories.forEach(tickStory);
  const pid = typeof req.query.project_id === "string" ? req.query.project_id : null;
  const list = pid ? stories.filter((s) => s.project_id === pid) : stories;
  res.json(list.map(storyOut));
});

router.post("/stories", (req, res) => {
  const assetIds: string[] = [...new Set((req.body?.asset_ids || []) as string[])].filter(Boolean);
  if (!assetIds.length) { res.status(400).json({ detail: "Pick at least one asset" }); return; }
  const missing = assetIds.filter((id) => !assets.find((a) => a.id === id));
  if (missing.length) { res.status(404).json({ detail: `Unknown assets: ${missing.join(", ")}` }); return; }
  const story: MockStory = {
    id: `story-${Date.now()}-${Math.floor(Math.random() * 10000)}`,
    prompt: (req.body?.prompt || "").trim() || null,
    project_id: (req.body?.project_id as string | null) || null,
    asset_ids: assetIds,
    status: "pending", progress: 0,
    title: null, narrative: null, clip_list_id: null,
    error_message: null,
    created_at: new Date().toISOString(), finished_at: null,
    _startedAt: Date.now(),
  };
  stories.unshift(story);
  touchProject(story.project_id);
  res.status(202).json(storyOut(story));
});

router.get("/stories/:id", (req, res) => {
  const s = stories.find((x) => x.id === req.params.id);
  if (!s) { res.status(404).json({ detail: "Story not found" }); return; }
  tickStory(s);
  res.json(storyOut(s));
});

router.delete("/stories/:id", (req, res) => {
  const idx = stories.findIndex((x) => x.id === req.params.id);
  if (idx === -1) { res.status(404).json({ detail: "Story not found" }); return; }
  const story = stories[idx];
  if (story.clip_list_id) {
    const clIdx = clipLists.findIndex((c) => c.id === story.clip_list_id);
    if (clIdx !== -1) {
      if ((clipLists[clIdx] as any).locked) {
        res.status(423).json({ detail: "This story's clip list is picture-locked. Unlock it to delete the story." });
        return;
      }
      clipLists.splice(clIdx, 1);
    }
  }
  stories.splice(idx, 1);
  touchProject(story.project_id);
  res.status(204).send();
});

// ── Script match ─────────────────────────────────────────────────────────────

router.post("/search/script-match", (req, res) => {
  const script: string = req.body.script || "";
  const perLine = Math.min(Math.max(req.body.matches_per_line || 3, 1), 10);
  const smMediaIds: string[] | null = Array.isArray(req.body.media_ids) && req.body.media_ids.length ? req.body.media_ids : null;
  const smInPool = (id: string) =>
    (!smMediaIds || smMediaIds.includes(id)) && (!req.body.media_id || req.body.media_id === id);
  const pool = transcript.filter((seg) => smInPool(seg.media_id));
  const lines = script
    .split("\n")
    .map((l: string) => l.trim())
    .filter((l: string) => l.length >= 3)
    .slice(0, 50);

  const out = lines.map((line: string) => {
    const words = line.toLowerCase().split(/\W+/).filter((w: string) => w.length > 3);
    const scored = pool
      .map((seg) => {
        const text = seg.text.toLowerCase();
        const hits = words.filter((w: string) => text.includes(w)).length;
        return { seg, score: words.length ? hits / words.length : 0 };
      })
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, perLine);
    const matches = (scored.length ? scored : pool.slice(0, 1).map((seg) => ({ seg, score: 0.42 })))
      .map(({ seg, score }) => {
        const asset = assets.find((a) => a.id === seg.media_id);
        return {
          media_id: seg.media_id,
          filename: asset?.filename || "unknown",
          thumbnail_url: null,
          start_time: seg.start_time,
          end_time: seg.end_time,
          score: Math.round((0.5 + score / 2) * 100) / 100,
          match_type: "transcript",
          snippet: seg.text,
        };
      });
    return { line, matches };
  });

  res.json({ lines: out, took_ms: 42 });
});

// ── People & Insights ────────────────────────────────────────────────────────

const people = [
  {
    id: "person-001",
    display_name: "Sarah Chen",
    name_source: "auto",
    thumbnail_url: null as string | null,
    speech_style:
      "Confident and precise, favors concrete technical detail over generalities. Speaks in measured, complete sentences and often reframes questions before answering them.",
    key_topics: ["local AI infrastructure", "GPU computing", "video processing at scale", "cloud cost reduction", "team leadership"],
    summary:
      "Appears to be a senior technology executive leading an infrastructure team. Frequently interviewed about large-scale local AI processing and challenges to cloud-first assumptions.",
    asset_count: 3,
    total_speaking_seconds: 1845.2,
    segment_count: 214,
    updated_at: now,
    face_search: null as Record<string, any> | null,
  },
  {
    id: "person-002",
    display_name: "Marcus Webb",
    name_source: "auto",
    thumbnail_url: null as string | null,
    speech_style:
      "Warm, conversational interviewer style. Asks short open-ended questions, frequently affirms the speaker, and uses accessible analogies for technical topics.",
    key_topics: ["technology interviews", "infrastructure", "startup strategy"],
    summary:
      "Recurring interviewer/host across the library. Guides conversations rather than presenting; appears in most interview-format assets.",
    asset_count: 2,
    total_speaking_seconds: 612.7,
    segment_count: 98,
    updated_at: now,
    face_search: null as Record<string, any> | null,
  },
  {
    id: "person-003",
    display_name: "Councilwoman Rivera",
    name_source: "auto",
    thumbnail_url: null as string | null,
    speech_style:
      "Formal procedural register with deliberate pacing. Uses policy terminology, cites ordinance numbers, and frequently defers to points of order.",
    key_topics: ["zoning policy", "budget allocation", "public infrastructure", "community development"],
    summary:
      "City council member who chairs sessions in the civic meeting footage. Primary speaker in municipal government assets.",
    asset_count: 1,
    total_speaking_seconds: 1120.4,
    segment_count: 156,
    updated_at: now,
    face_search: null as Record<string, any> | null,
  },
  {
    id: "person-004",
    display_name: "Person 4",
    name_source: null as string | null,
    thumbnail_url: null as string | null,
    speech_style: null as string | null,
    key_topics: [] as string[],
    summary: null as string | null,
    asset_count: 1,
    total_speaking_seconds: 87.3,
    segment_count: 12,
    updated_at: now,
    face_search: null as Record<string, any> | null,
  },
];

const personAppearances: Record<string, any[]> = {
  "person-001": [
    { media_id: "asset-001", filename: "interview_sarah_chen.mp4", thumbnail_url: null, duration_seconds: 1122.5, speaker_label: "SPEAKER_00", face_cluster_id: "cluster-001", speaking_seconds: 812.4, segment_count: 96, first_spoken_at: 2.1 },
    { media_id: "asset-003", filename: "documentary_rough_cut_v3.mkv", thumbnail_url: null, duration_seconds: 5406.0, speaker_label: "SPEAKER_02", face_cluster_id: null, speaking_seconds: 734.5, segment_count: 84, first_spoken_at: 341.8 },
    { media_id: "asset-004", filename: "press_conference_may15.mp4", thumbnail_url: null, duration_seconds: 1863.2, speaker_label: "SPEAKER_01", face_cluster_id: "cluster-004", speaking_seconds: 298.3, segment_count: 34, first_spoken_at: 122.6, merged_from: { person_id: "person-legacy-012", display_name: "Person 12" } },
  ],
  "person-002": [
    { media_id: "asset-001", filename: "interview_sarah_chen.mp4", thumbnail_url: null, duration_seconds: 1122.5, speaker_label: "SPEAKER_01", face_cluster_id: "cluster-002", speaking_seconds: 310.2, segment_count: 52, first_spoken_at: 9.0 },
    { media_id: "asset-003", filename: "documentary_rough_cut_v3.mkv", thumbnail_url: null, duration_seconds: 5406.0, speaker_label: "SPEAKER_00", face_cluster_id: null, speaking_seconds: 302.5, segment_count: 46, first_spoken_at: 12.4 },
  ],
  "person-003": [
    { media_id: "asset-002", filename: "city_council_meeting_oct24.mp4", thumbnail_url: null, duration_seconds: 7204.8, speaker_label: "SPEAKER_00", face_cluster_id: "cluster-003", speaking_seconds: 1120.4, segment_count: 156, first_spoken_at: 44.2 },
  ],
  "person-004": [
    { media_id: "asset-004", filename: "press_conference_may15.mp4", thumbnail_url: null, duration_seconds: 1863.2, speaker_label: "SPEAKER_03", face_cluster_id: null, speaking_seconds: 87.3, segment_count: 12, first_spoken_at: 903.1 },
  ],
};

type InsightPersonRef = { person_id: string | null; display_name: string };
type InsightTopicRef = { key: string; label: string };

let libraryInsights: {
  generated_at: string | null;
  headline: string | null;
  insights: { title: string; detail: string; related_people?: InsightPersonRef[]; related_topics?: InsightTopicRef[] }[];
  opportunities: { title: string; rationale: string; asset_ids: string[]; people: InsightPersonRef[]; total_duration_seconds: number }[];
  coverage_gaps: { key: string; label: string }[];
} = {
  generated_at: new Date(Date.now() - 86400000).toISOString(),
  headline:
    "An interview-heavy technology archive anchored by Sarah Chen, with growing but under-processed civic and documentary footage.",
  insights: [
    {
      title: "Sarah Chen is the library's central figure",
      detail:
        "She appears in 3 of 5 assets and accounts for over 30 minutes of speaking time — more than any other person. Her recurring themes (local AI infrastructure, GPU computing) effectively define the archive's editorial identity.",
      related_people: [{ person_id: "person-001", display_name: "Sarah Chen" }],
      related_topics: [
        { key: "local ai infrastructure", label: "Local AI Infrastructure" },
        { key: "gpu computing", label: "GPU Computing" },
      ],
    },
    {
      title: "Interview format dominates the collection",
      detail:
        "Most speech content comes from two-person interview setups hosted by Marcus Webb. Consider tagging B-roll and civic footage more aggressively, since search quality currently skews toward interview content.",
      related_people: [{ person_id: "person-002", display_name: "Marcus Webb" }],
      related_topics: [{ key: "b-roll", label: "B-roll" }],
    },
    {
      title: "Civic footage is a single point of coverage",
      detail:
        "All municipal government content traces to one council meeting featuring Councilwoman Rivera. If civic coverage matters to the library, this is a significant gap.",
      related_people: [{ person_id: "person-003", display_name: "Councilwoman Rivera" }],
      related_topics: [{ key: "zoning policy", label: "Zoning Policy" }],
    },
    {
      title: "One speaker remains unidentified",
      detail:
        "A speaker in the May 15 press conference could not be matched to any known person or named from context. Reviewing and naming them would improve cross-asset tracking.",
      related_people: [{ person_id: "person-004", display_name: "Person 4" }],
    },
  ],
  opportunities: [
    {
      title: "The case against cloud — a Sarah Chen anchor piece",
      rationale:
        "Three assets cover local AI infrastructure from complementary angles: the sit-down interview lays out the argument, the documentary rough cut adds narrative context, and the press conference provides a public-facing counterpoint. Enough material for a 10–15 minute edited feature.",
      asset_ids: ["asset-001", "asset-003", "asset-004"],
      people: [
        { person_id: "person-001", display_name: "Sarah Chen" },
        { person_id: "person-002", display_name: "Marcus Webb" },
      ],
      total_duration_seconds: 1842 + 3612 + 2876,
    },
    {
      title: "Downtown's bet: the planner vs. the merchants",
      rationale:
        "The Chen interview's revitalization thread and the council meeting cover the same policy fight from both sides — the planner's case and the public record. A two-voice piece pairing Chen's promises against Rivera's procedural pushback writes itself.",
      asset_ids: ["asset-001", "asset-002"],
      people: [
        { person_id: "person-001", display_name: "Sarah Chen" },
        { person_id: "person-003", display_name: "Councilwoman Rivera" },
      ],
      total_duration_seconds: 1842 + 5402,
    },
  ],
  coverage_gaps: [
    { key: "community development", label: "Community Development" },
    { key: "press relations", label: "Press Relations" },
    { key: "election coverage", label: "Election Coverage" },
  ],
};

router.get("/people", (req, res) => {
  const limit = Math.min(Math.max(parseInt(String(req.query.limit ?? "48"), 10) || 48, 1), 200);
  const offset = Math.max(parseInt(String(req.query.offset ?? "0"), 10) || 0, 0);
  const q = String(req.query.q ?? "").trim().toLowerCase();
  const sort = String(req.query.sort ?? "appearances");
  const facesOnly = String(req.query.faces_only ?? "") === "true";
  let filtered = q
    ? people.filter((p) => p.display_name.toLowerCase().includes(q))
    : [...people];
  if (facesOnly) {
    // Mock heuristic: speaker-label-only identities stand in for voice-only people.
    filtered = filtered.filter(
      (p) => p.thumbnail_url != null || !/^(SPEAKER_|VO\b|VO\d)/.test(p.display_name)
    );
  }
  if (sort === "name") {
    filtered.sort((a, b) => a.display_name.toLowerCase().localeCompare(b.display_name.toLowerCase()));
  }
  res.json({ items: filtered.slice(offset, offset + limit), total: filtered.length });
});

// Must be registered before /people/:id, or "co-appearances" is treated as an id.
router.get("/people/co-appearances", (req, res) => {
  const namedOnly = String(req.query.named_only ?? "") === "true";
  const minShared = Math.max(1, parseInt(String(req.query.min_shared ?? "1"), 10) || 1);
  const visible = namedOnly ? people.filter((p) => p.name_source != null) : people;
  const visibleIds = new Set(visible.map((p) => p.id));
  const byMedia: Record<string, string[]> = {};
  for (const p of visible) {
    for (const a of personAppearances[p.id] ?? []) {
      (byMedia[a.media_id] ??= []).push(p.id);
    }
  }
  const pairs: Record<string, { person_a_id: string; person_b_id: string; shared_assets: number; together_seconds: number }> = {};
  for (const pids of Object.values(byMedia)) {
    const uniq = [...new Set(pids)].sort();
    for (let i = 0; i < uniq.length; i++) {
      for (let j = i + 1; j < uniq.length; j++) {
        const key = `${uniq[i]}|${uniq[j]}`;
        pairs[key] ??= { person_a_id: uniq[i], person_b_id: uniq[j], shared_assets: 0, together_seconds: 0 };
        pairs[key].shared_assets += 1;
        // Mock on-camera overlap: a deterministic slice of the smaller speaking time.
        const specificSpeaking = (pid: string, mid: string) =>
          (personAppearances[pid] ?? []).find((x) => x.media_id === mid)?.speaking_seconds ?? 0;
        const mid = Object.keys(byMedia).find((m) => byMedia[m] === pids)!;
        pairs[key].together_seconds += Math.round(Math.min(specificSpeaking(uniq[i], mid), specificSpeaking(uniq[j], mid)) * 0.45);
      }
    }
  }
  const pairList = Object.values(pairs).filter(
    (p) => p.shared_assets >= minShared && visibleIds.has(p.person_a_id) && visibleIds.has(p.person_b_id)
  );
  // Every person passing the filter is a node — solo people render unconnected.
  res.json({
    nodes: visible.map((p) => ({ person_id: p.id, display_name: p.display_name, thumbnail_url: p.thumbnail_url, asset_count: p.asset_count })),
    pairs: pairList,
  });
});

router.post("/people/enroll", upload.single("photo"), (req, res) => {
  const file = (req as any).file;
  const displayName = String(req.body?.display_name ?? "").trim();
  if (!file) { res.status(422).json({ error: "No photo uploaded" }); return; }
  if (!displayName) { res.status(422).json({ error: "display_name must not be empty" }); return; }
  const newPerson = {
    id: `person-${String(people.length + 1).padStart(3, "0")}`,
    display_name: displayName,
    name_source: "manual" as string | null,
    thumbnail_url: null as string | null,
    speech_style: null as string | null,
    key_topics: [] as string[],
    summary: null as string | null,
    asset_count: 0,
    total_speaking_seconds: 0,
    segment_count: 0,
    updated_at: new Date().toISOString(),
    face_search: null as Record<string, any> | null,
  };
  people.push(newPerson);
  personAppearances[newPerson.id] = [];
  // Mock matches: pretend the photo resembles the two busiest existing people.
  const matches = people
    .filter((p) => p.id !== newPerson.id)
    .sort((a, b) => b.asset_count - a.asset_count)
    .slice(0, 2)
    .map((p, i) => ({
      person_id: p.id,
      display_name: p.display_name,
      thumbnail_url: p.thumbnail_url,
      asset_count: p.asset_count,
      similarity: i === 0 ? 0.78 : 0.31,
      strong: i === 0,
    }));
  res.status(201).json({ person: newPerson, matches });
});

router.get("/people/:id", (req, res) => {
  const p = people.find((x) => x.id === req.params.id);
  if (!p) { res.status(404).json({ error: "Not found" }); return; }
  res.json({ ...p, appearances: personAppearances[p.id] ?? [] });
});

router.get("/people/:id/appearances/:mediaId", (req, res) => {
  const p = people.find((x) => x.id === req.params.id);
  if (!p) { res.status(404).json({ error: "Not found" }); return; }
  const apps = (personAppearances[p.id] ?? []).filter((a) => a.media_id === req.params.mediaId);
  if (!apps.length) { res.status(404).json({ error: "No appearance in this asset" }); return; }
  const speakers = new Set(apps.map((a) => a.speaker_label).filter(Boolean));
  const speaking = transcript
    .filter((s) => s.media_id === req.params.mediaId && speakers.has(s.speaker))
    .sort((a, b) => a.start_time - b.start_time)
    .map((s) => ({ start_time: s.start_time, end_time: s.end_time, text: s.text }));
  // Mock on-camera ranges: pad + merge the speaking spans when a face cluster exists.
  const onCamera: { start_time: number; end_time: number }[] = [];
  if (apps.some((a) => a.face_cluster_id)) {
    const spans = speaking.length
      ? speaking.map((s) => ({ start_time: Math.max(0, s.start_time - 3), end_time: s.end_time + 3 }))
      : apps
          .filter((a) => a.first_spoken_at != null)
          .map((a) => ({ start_time: Math.max(0, a.first_spoken_at - 5), end_time: a.first_spoken_at + 40 }));
    for (const s of spans.sort((a, b) => a.start_time - b.start_time)) {
      const last = onCamera[onCamera.length - 1];
      if (last && s.start_time <= last.end_time) last.end_time = Math.max(last.end_time, s.end_time);
      else onCamera.push({ ...s });
    }
  }
  res.json({ media_id: req.params.mediaId, speaking, on_camera: onCamera });
});

router.patch("/people/:id", (req, res) => {
  const p = people.find((x) => x.id === req.params.id);
  if (!p) { res.status(404).json({ error: "Not found" }); return; }
  if (req.body?.display_name === undefined && req.body?.summary === undefined) {
    res.status(422).json({ error: "Provide display_name and/or summary" });
    return;
  }
  if (req.body?.display_name !== undefined) {
    const name = String(req.body.display_name ?? "").trim();
    if (!name) { res.status(422).json({ error: "display_name must not be empty" }); return; }
    p.display_name = name;
    p.name_source = "manual";
  }
  if (req.body?.summary !== undefined) {
    p.summary = String(req.body.summary ?? "").trim().slice(0, 2000) || null;
  }
  p.updated_at = new Date().toISOString();
  res.json(p);
});

router.delete("/people/:id", (req, res) => {
  const idx = people.findIndex((x) => x.id === req.params.id);
  if (idx < 0) { res.status(404).json({ error: "Not found" }); return; }
  const pid = people[idx].id;
  delete personAppearances[pid];
  for (let i = voiceSamples.length - 1; i >= 0; i--) {
    if (voiceSamples[i].person_id === pid) voiceSamples.splice(i, 1);
  }
  for (let i = voiceGenerations.length - 1; i >= 0; i--) {
    if (voiceGenerations[i].person_id === pid) voiceGenerations.splice(i, 1);
  }
  people.splice(idx, 1);
  res.status(204).end();
});

router.post("/people/:id/merge", (req, res) => {
  const target = people.find((x) => x.id === req.params.id);
  const sourceId = String(req.body?.source_person_id ?? "");
  const sourceIdx = people.findIndex((x) => x.id === sourceId);
  if (!target || sourceIdx < 0) { res.status(404).json({ error: "Not found" }); return; }
  if (target.id === sourceId) { res.status(400).json({ error: "Cannot merge a person into themselves" }); return; }
  const source = people[sourceIdx];
  target.asset_count += source.asset_count;
  target.total_speaking_seconds += source.total_speaking_seconds;
  target.segment_count += source.segment_count;
  // Stamp merge provenance so the merge can be undone; earlier provenance wins.
  const moved = (personAppearances[sourceId] ?? []).map((a: any) => ({
    ...a,
    merged_from: a.merged_from ?? {
      person_id: source.id,
      display_name: source.display_name,
      name_source: source.name_source ?? null,
    },
  }));
  personAppearances[target.id] = [...(personAppearances[target.id] ?? []), ...moved];
  delete personAppearances[sourceId];
  people.splice(sourceIdx, 1);
  res.json(target);
});

router.post("/people/:id/split", (req, res) => {
  const source = people.find((x) => x.id === req.params.id);
  if (!source) { res.status(404).json({ error: "Not found" }); return; }
  const mediaId = String(req.body?.media_id ?? "");
  const speakerLabel = req.body?.speaker_label ?? null;
  const faceClusterId = req.body?.face_cluster_id ?? null;
  const apps = personAppearances[source.id] ?? [];
  const idx = apps.findIndex(
    (a: any) =>
      a.media_id === mediaId &&
      (speakerLabel == null || a.speaker_label === speakerLabel) &&
      (faceClusterId == null || a.face_cluster_id === faceClusterId)
  );
  if (idx < 0) { res.status(404).json({ error: "Appearance not found on this person" }); return; }
  if (apps.length <= 1) {
    res.status(409).json({ error: "This is the person's only appearance — rename this person instead of splitting" });
    return;
  }
  const [app] = apps.splice(idx, 1);
  const newPerson = {
    id: `person-${Date.now()}`,
    display_name: `Person ${people.length + 1}`,
    name_source: null as string | null,
    thumbnail_url: app.thumbnail_url ?? null,
    speech_style: null as string | null,
    key_topics: [] as string[],
    summary: null as string | null,
    asset_count: 1,
    total_speaking_seconds: app.speaking_seconds ?? 0,
    segment_count: app.segment_count ?? 0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  people.push(newPerson as any);
  personAppearances[newPerson.id] = [app];
  source.asset_count = Math.max(0, source.asset_count - 1);
  source.total_speaking_seconds = Math.max(0, source.total_speaking_seconds - (app.speaking_seconds ?? 0));
  source.segment_count = Math.max(0, source.segment_count - (app.segment_count ?? 0));
  res.json(newPerson);
});

router.post("/people/:id/unmerge", (req, res) => {
  const target = people.find((x) => x.id === req.params.id);
  if (!target) { res.status(404).json({ error: "Not found" }); return; }
  const fromId = String(req.body?.merged_from_person_id ?? "");
  const apps = personAppearances[target.id] ?? [];
  const moved = apps.filter((a: any) => a.merged_from?.person_id === fromId);
  if (!moved.length) {
    res.status(404).json({ error: "No appearances from that merge remain on this person" });
    return;
  }
  personAppearances[target.id] = apps.filter((a: any) => a.merged_from?.person_id !== fromId);
  const info = moved[0].merged_from;
  const restored = {
    id: `person-${Date.now()}`,
    display_name: info.display_name ?? "Restored person",
    name_source: info.name_source ?? null,
    thumbnail_url: moved[0].thumbnail_url ?? null,
    speech_style: null as string | null,
    key_topics: [] as string[],
    summary: null as string | null,
    asset_count: new Set(moved.map((a: any) => a.media_id)).size,
    total_speaking_seconds: moved.reduce((s: number, a: any) => s + (a.speaking_seconds ?? 0), 0),
    segment_count: moved.reduce((s: number, a: any) => s + (a.segment_count ?? 0), 0),
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  people.push(restored as any);
  personAppearances[restored.id] = moved.map((a: any) => ({ ...a, merged_from: null }));
  target.asset_count = new Set((personAppearances[target.id] ?? []).map((a: any) => a.media_id)).size;
  target.total_speaking_seconds = Math.max(0, target.total_speaking_seconds - restored.total_speaking_seconds);
  target.segment_count = Math.max(0, target.segment_count - restored.segment_count);
  target.updated_at = new Date().toISOString();
  res.json(restored);
});

// ── Voice cloning ────────────────────────────────────────────────────────────
const MIN_SAMPLE_SECONDS = 10;

const voiceSamples: any[] = [
  {
    id: "vsample-001",
    person_id: "person-001",
    source: "segment",
    status: "ready",
    media_id: "asset-001",
    filename: "interview_sarah_chen.mp4",
    start_time: 125.4,
    end_time: 148.9,
    duration_seconds: 23.5,
    error_message: null,
    created_at: "2026-07-15T10:12:00Z",
  },
];
const voiceGenerations: any[] = [];

function tinyWav(res: any) {
  // 0.5s of silence, 8kHz mono 16-bit PCM
  const samples = 4000;
  const buf = Buffer.alloc(44 + samples * 2);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + samples * 2, 4); buf.write("WAVE", 8);
  buf.write("fmt ", 12); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(8000, 24); buf.writeUInt32LE(16000, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34);
  buf.write("data", 36); buf.writeUInt32LE(samples * 2, 40);
  res.setHeader("Content-Type", "audio/wav");
  res.send(buf);
}

function voiceProfile(personId: string) {
  const samples = voiceSamples.filter((s) => s.person_id === personId);
  const total = samples
    .filter((s) => s.status === "ready")
    .reduce((sum, s) => sum + (s.duration_seconds ?? 0), 0);
  return {
    person_id: personId,
    ready: total >= MIN_SAMPLE_SECONDS,
    total_sample_seconds: total,
    min_sample_seconds: MIN_SAMPLE_SECONDS,
    samples,
  };
}

router.get("/people/:id/voice", (req, res) => {
  if (!people.find((p) => p.id === req.params.id)) { res.status(404).json({ error: "Not found" }); return; }
  res.json(voiceProfile(req.params.id));
});

router.post("/people/:id/voice/samples", (req, res) => {
  const person = people.find((p) => p.id === req.params.id);
  if (!person) { res.status(404).json({ error: "Not found" }); return; }
  const mediaId = String(req.body?.media_id ?? "");
  const asset = assets.find((a: any) => a.id === mediaId);
  if (!asset) { res.status(404).json({ error: "Media not found" }); return; }
  const start = Number(req.body?.start_time);
  const end = Number(req.body?.end_time);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || start < 0) {
    res.status(400).json({ error: "Invalid segment range" }); return;
  }
  if (end - start > 60) { res.status(400).json({ error: "Segment capped at 60 seconds" }); return; }
  const sample: any = {
    id: `vsample-${Date.now()}`,
    person_id: person.id,
    source: "segment",
    status: "pending",
    media_id: mediaId,
    filename: (asset as any).filename,
    start_time: start,
    end_time: end,
    duration_seconds: null,
    error_message: null,
    created_at: new Date().toISOString(),
  };
  voiceSamples.push(sample);
  setTimeout(() => {
    sample.status = "ready";
    sample.duration_seconds = Math.round((end - start) * 10) / 10;
  }, 2500);
  res.status(202).json(sample);
});

router.post("/people/:id/voice/samples/upload", upload.single("file"), (req, res) => {
  const person = people.find((p) => p.id === req.params.id);
  if (!person) { res.status(404).json({ error: "Not found" }); return; }
  const file = req.file;
  if (!file) { res.status(400).json({ error: "No file provided" }); return; }
  if (!/\.(wav|mp3|m4a|flac|ogg)$/i.test(file.originalname)) {
    res.status(400).json({ error: "Unsupported file type — use wav, mp3, m4a, flac, or ogg" });
    return;
  }
  const sample: any = {
    id: `vsample-${Date.now()}`,
    person_id: person.id,
    source: "upload",
    status: "pending",
    media_id: null,
    filename: file.originalname,
    start_time: null,
    end_time: null,
    duration_seconds: null,
    error_message: null,
    created_at: new Date().toISOString(),
  };
  voiceSamples.push(sample);
  setTimeout(() => {
    sample.status = "ready";
    sample.duration_seconds = 14.2;
  }, 2500);
  res.status(202).json(sample);
});

router.delete("/voice/samples/:id", (req, res) => {
  const idx = voiceSamples.findIndex((s) => s.id === req.params.id);
  if (idx < 0) { res.status(404).json({ error: "Not found" }); return; }
  voiceSamples.splice(idx, 1);
  res.status(204).end();
});

router.get("/voice/samples/:id/audio", (req, res) => {
  const sample = voiceSamples.find((s) => s.id === req.params.id);
  if (!sample || sample.status !== "ready") { res.status(404).json({ error: "Not found" }); return; }
  tinyWav(res);
});

router.post("/people/:id/voice/speak", (req, res) => {
  const person = people.find((p) => p.id === req.params.id);
  if (!person) { res.status(404).json({ error: "Not found" }); return; }
  const profile = voiceProfile(person.id);
  if (!profile.ready) {
    res.status(409).json({ error: `Voice profile not ready — add at least ${MIN_SAMPLE_SECONDS}s of clean samples` });
    return;
  }
  const text = String(req.body?.text ?? "").trim();
  if (!text) { res.status(400).json({ error: "Text required" }); return; }
  const { settings: genSettings, error: settingsError } = validateVoiceSettings(req.body?.settings ?? {});
  if (settingsError) { res.status(400).json({ error: settingsError }); return; }
  const gen: any = {
    id: `vgen-${Date.now()}`,
    person_id: person.id,
    text,
    language: String(req.body?.language ?? "en"),
    status: "pending",
    progress: 0,
    duration_seconds: null,
    error_message: null,
    created_at: new Date().toISOString(),
    preset: null,
    settings: genSettings,
  };
  voiceGenerations.unshift(gen);
  simulateGen(gen, text);
  res.status(202).json(gen);
});

function simulateGen(gen: any, text: string) {
  const timer = setInterval(() => {
    gen.status = "running";
    gen.progress = Math.min(100, gen.progress + 34);
    if (gen.progress >= 100) {
      gen.status = "success";
      gen.duration_seconds = Math.max(1, Math.round(text.split(/\s+/).length / 2.5));
      clearInterval(timer);
    }
  }, 1200);
}

const VOICE_PRESETS = ["natural", "expressive", "steady", "warm"];

router.post("/people/:id/voice/tune", (req, res) => {
  const person = people.find((p) => p.id === req.params.id);
  if (!person) { res.status(404).json({ error: "Not found" }); return; }
  const profile = voiceProfile(person.id);
  if (!profile.ready) {
    res.status(409).json({ error: `Voice profile not ready — add at least ${MIN_SAMPLE_SECONDS}s of clean samples` });
    return;
  }
  const text = String(req.body?.text ?? "").trim();
  if (!text) { res.status(400).json({ error: "Text required" }); return; }
  const gens = VOICE_PRESETS.map((preset, i) => ({
    id: `vgen-${Date.now()}-${i}`,
    person_id: person.id,
    text,
    language: String(req.body?.language ?? "en"),
    status: "pending",
    progress: 0,
    duration_seconds: null,
    error_message: null,
    created_at: new Date().toISOString(),
    preset,
  }));
  for (const gen of gens) {
    voiceGenerations.unshift(gen);
    simulateGen(gen, text);
  }
  res.status(202).json(gens);
});

router.put("/people/:id/voice/preset", (req, res) => {
  const person: any = people.find((p) => p.id === req.params.id);
  if (!person) { res.status(404).json({ error: "Not found" }); return; }
  const preset = String(req.body?.preset ?? "").trim().toLowerCase();
  if (!VOICE_PRESETS.includes(preset)) {
    res.status(400).json({ error: `Unknown preset. Choose one of: ${VOICE_PRESETS.join(", ")}` });
    return;
  }
  person.voice_preset = preset;
  person.voice_settings = null;
  res.status(204).end();
});

// Mirrors SETTINGS_RANGES in services/api/app/routers/voice.py
const SETTINGS_RANGES: Record<string, [number, number]> = {
  speed: [0.7, 1.3],
  temperature: [0.2, 1.2],
  top_p: [0.3, 1.0],
  repetition_penalty: [1.5, 12],
};

function validateVoiceSettings(body: any): { settings: any | null; error?: string } {
  const settings: any = {};
  for (const [k, [lo, hi]] of Object.entries(SETTINGS_RANGES)) {
    const v = body?.[k];
    if (v === null || v === undefined) continue;
    if (typeof v !== "number" || v < lo || v > hi) {
      return { settings: null, error: `${k} must be between ${lo} and ${hi}` };
    }
    settings[k] = v;
  }
  return { settings: Object.keys(settings).length ? settings : null };
}

router.put("/people/:id/voice/settings", (req, res) => {
  const person: any = people.find((p) => p.id === req.params.id);
  if (!person) { res.status(404).json({ error: "Not found" }); return; }
  const { settings, error } = validateVoiceSettings(req.body);
  if (error) { res.status(400).json({ error }); return; }
  person.voice_settings = settings;
  res.status(204).end();
});

router.get("/people/:id/voice/generations", (req, res) => {
  res.json(voiceGenerations.filter((g) => g.person_id === req.params.id));
});

router.delete("/voice/generations/:id", (req, res) => {
  const idx = voiceGenerations.findIndex((g) => g.id === req.params.id);
  if (idx < 0) { res.status(404).json({ error: "Not found" }); return; }
  voiceGenerations.splice(idx, 1);
  res.status(204).end();
});

router.get("/voice/generations/:id/audio", (req, res) => {
  const gen = voiceGenerations.find((g) => g.id === req.params.id);
  if (!gen || gen.status !== "success") { res.status(404).json({ error: "Not found" }); return; }
  tinyWav(res);
});

const PLACEHOLDER_NAME_RE = /^person \d+$/i;

router.get("/insights", (_req, res) => {
  const d = libraryDurations();
  const named = people.filter((p) => !PLACEHOLDER_NAME_RE.test(p.display_name)).length;
  // Group raw per-asset topic tags by normalized key so casing/underscore
  // variants ("Local AI Infrastructure" vs "local_ai_infrastructure") merge.
  const rawCounts = new Map<string, number>();
  for (const a of assets) {
    for (const t of new Set(assetTopics(a).map((x) => normalizeTopicKey(x)))) {
      rawCounts.set(t, (rawCounts.get(t) ?? 0) + 1);
    }
  }
  res.json({
    generated_at: libraryInsights.generated_at,
    headline: libraryInsights.headline,
    insights: libraryInsights.insights,
    opportunities: libraryInsights.opportunities,
    coverage_gaps: libraryInsights.coverage_gaps.map((g) => ({
      key: g.key,
      label: topicLabel(g.key),
      asset_count: countAssetsWithTopic(g.key),
    })),
    stats: {
      total_assets: assets.length,
      total_duration_seconds: d.totalSeconds,
      speech_indexed_seconds: d.speechIndexedSeconds,
      total_people: people.length,
      named_people_count: named,
      unidentified_people_count: people.length - named,
      transcribed_assets: d.transcribedCount,
      total_speaking_seconds: people.reduce((s, p) => s + p.total_speaking_seconds, 0),
    },
    top_people: [...people]
      .sort((a, b) => b.asset_count - a.asset_count || b.total_speaking_seconds - a.total_speaking_seconds)
      .map((p) => ({
        person_id: p.id,
        display_name: p.display_name,
        thumbnail_url: p.thumbnail_url,
        asset_count: p.asset_count,
        speaking_seconds: p.total_speaking_seconds,
      })),
    top_topics: groupTopics(rawCounts.entries()).slice(0, 12),
  });
});

router.get("/insights/keyword-heatmap", (req, res) => {
  const monthsN = Math.min(36, Math.max(3, Number(req.query.months) || 12));
  const limit = Math.min(50, Math.max(5, Number(req.query.limit) || 20));
  const now = new Date();
  const months: string[] = [];
  for (let i = monthsN - 1; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    months.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  }
  // Mock assets are all ingested "recently", which would make a real
  // aggregation collapse into one column — synthesize a deterministic
  // per-month history per keyword so the preview shows the real UI.
  const rawCounts = new Map<string, number>();
  for (const a of assets) {
    for (const t of new Set(assetTopics(a).map((x) => normalizeTopicKey(x)))) {
      rawCounts.set(t, (rawCounts.get(t) ?? 0) + 1);
    }
  }
  const hash = (s: string) => {
    let h = 7;
    for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return h;
  };
  const rows = groupTopics(rawCounts.entries())
    .slice(0, limit)
    .map((t) => {
      const h = hash(t.key);
      const counts = months.map((_, i) => {
        const wave = Math.sin((i + (h % 7)) / (1.5 + (h % 3))) + 1;
        return Math.max(0, Math.round(wave * (((h >> 3) % 3) + t.asset_count * 0.75)) - (h % 2));
      });
      counts[counts.length - 1] = t.asset_count; // current month reflects real mock data
      return { key: t.key, label: t.topic, total: counts.reduce((s, n) => s + n, 0), counts };
    })
    .sort((a, b) => b.total - a.total);
  res.json({ months, rows });
});

router.post("/insights/refresh", (_req, res) => {
  const running = jobs.find((j: any) => j.job_type === "insights" && (j.status === "pending" || j.status === "running"));
  if (running) { res.status(202).json(running); return; }
  const job: any = {
    id: `job-insights-${Date.now()}`,
    media_id: null,
    filename: null,
    job_type: "insights",
    status: "running",
    progress: 5,
    error_message: null,
    logs: ["Aggregating library statistics..."],
    retry_count: 0,
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    finished_at: null,
  };
  jobs.unshift(job as any);
  const timer = setInterval(() => {
    job.progress = Math.min(100, (job.progress ?? 0) + 25);
    if (job.progress >= 40 && job.logs.length < 2) job.logs.push("Generating AI narrative...");
    if (job.progress >= 100) {
      job.status = "success";
      job.finished_at = new Date().toISOString();
      job.logs.push("Insights generated: 4 findings");
      libraryInsights = { ...libraryInsights, generated_at: new Date().toISOString() };
      clearInterval(timer);
    }
  }, 1500);
  res.status(202).json(job);
});

// ---------------------------------------------------------------------------
// External trends (YouTube trending + SearXNG news momentum in production)

let trendsFetchedAt = new Date(Date.now() - 45 * 60 * 1000).toISOString();

router.get("/trends", (_req, res) => {
  const rawCounts = new Map<string, number>();
  for (const a of assets) {
    for (const t of new Set(assetTopics(a).map((x) => normalizeTopicKey(x)))) {
      rawCounts.set(t, (rawCounts.get(t) ?? 0) + 1);
    }
  }
  const top = groupTopics(rawCounts.entries()).slice(0, 8);
  const matched = (key: string) => ({
    key,
    topic: topicLabel(key),
    asset_count: countAssetsWithTopic(key),
  });

  // Production searches YouTube per library topic (past week, by views), so
  // every mock entry is tied to a real library topic too.
  const channels = ["Breaking Now", "The Rundown", "Signal Desk", "Field Notes", "The Wire Room", "Deep Dive"];
  const titleShapes = [
    (t: string) => `${t}: what just changed and why it matters`,
    (t: string) => `Inside the ${t} story everyone missed`,
    (t: string) => `${t} explained in 12 minutes`,
    (t: string) => `The week ${t} went mainstream`,
    (t: string) => `${t}: the numbers behind the headlines`,
    (t: string) => `What nobody tells you about ${t}`,
  ];
  const youtube = top.slice(0, 6).map((g, i) => ({
    rank: i + 1,
    title: titleShapes[i % titleShapes.length](g.topic),
    channel: channels[i % channels.length],
    url: "https://www.youtube.com/results?search_query=" + encodeURIComponent(g.topic),
    views: 2400000 - i * 380000,
    matched_topics: [matched(g.key)],
  }));

  const web = top.map((g, i) => ({
    rank: i + 1,
    key: g.key,
    topic: g.topic,
    asset_count: g.asset_count,
    result_count: Math.max(2, 28 - i * 4),
    headlines: [
      {
        title: `${g.topic} back in the spotlight after new developments`,
        url: "https://news.example.com/" + encodeURIComponent(g.key.replace(/ /g, "-")),
      },
      {
        title: `Analysis: what the latest ${g.topic} coverage is missing`,
        url: "https://news.example.com/analysis/" + encodeURIComponent(g.key.replace(/ /g, "-")),
      },
    ],
  }));

  res.json({
    fetched_at: trendsFetchedAt,
    youtube_configured: true,
    web_configured: true,
    youtube,
    web,
  });
});

router.post("/trends/refresh", (_req, res) => {
  const running = jobs.find(
    (j: any) => j.job_type === "trends" && (j.status === "pending" || j.status === "running"),
  );
  if (running) { res.status(202).json(running); return; }
  const job: any = {
    id: `job-trends-${Date.now()}`,
    media_id: null,
    filename: null,
    job_type: "trends",
    status: "running",
    progress: 5,
    error_message: null,
    logs: ["Fetching YouTube trending chart..."],
    retry_count: 0,
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    finished_at: null,
  };
  jobs.unshift(job as any);
  const timer = setInterval(() => {
    job.progress = Math.min(100, (job.progress ?? 0) + 30);
    if (job.progress >= 50 && job.logs.length < 2) job.logs.push("Querying SearXNG for library topics...");
    if (job.progress >= 100) {
      job.status = "success";
      job.finished_at = new Date().toISOString();
      job.logs.push("Trends updated: 5 videos, 8 topics");
      trendsFetchedAt = new Date().toISOString();
      clearInterval(timer);
    }
  }, 1200);
  res.status(202).json(job);
});

// ---------------------------------------------------------------------------
// Graphics generator (ComfyUI-backed in production; simulated here)

const graphicsPresets: any[] = [
  {
    id: "flux-schnell",
    name: "FLUX Schnell — Fast Image",
    description: "4-step image generation, seconds per image. Great for drafts and iteration.",
    kind: "image",
    source: "builtin",
    available: true,
    unavailable_reason: null,
    supports_negative: false,
    supports_size: true,
    supports_steps: false,
    supports_frames: false,
    supports_seed: true,
    default_width: 1024,
    default_height: 1024,
    default_steps: 4,
    default_frames: null,
  },
  {
    id: "flux-dev",
    name: "FLUX Dev — Quality Image",
    description: "Full-quality FLUX.1-dev image generation. Slower, best detail.",
    kind: "image",
    source: "builtin",
    available: true,
    unavailable_reason: null,
    supports_negative: false,
    supports_size: true,
    supports_steps: true,
    supports_frames: false,
    supports_seed: true,
    default_width: 1024,
    default_height: 1024,
    default_steps: 20,
    default_frames: null,
  },
  {
    id: "wan22-t2v",
    name: "Wan 2.2 — Text to Video",
    description: "Wan2.2 A14B text-to-video, 720p. High quality, minutes per clip.",
    kind: "video",
    source: "builtin",
    available: true,
    unavailable_reason: null,
    supports_negative: true,
    supports_size: true,
    supports_steps: true,
    supports_frames: true,
    supports_seed: true,
    default_width: 1280,
    default_height: 720,
    default_steps: 20,
    default_frames: 81,
  },
  {
    id: "ltx2-fast",
    name: "LTX-2 — Fast Video",
    description: "LTX-2 distilled text-to-video. Fastest way to a moving draft.",
    kind: "video",
    source: "builtin",
    available: true,
    unavailable_reason: null,
    supports_negative: true,
    supports_size: true,
    supports_steps: false,
    supports_frames: true,
    supports_seed: true,
    default_width: 1216,
    default_height: 704,
    default_steps: 8,
    default_frames: 97,
  },
  {
    id: "custom-example",
    name: "my-workflow.json",
    description: "Custom ComfyUI workflow from the workflows folder.",
    kind: "image",
    source: "custom",
    available: false,
    unavailable_reason: "ComfyUI not reachable from the Replit preview",
    supports_negative: false,
    supports_size: false,
    supports_steps: false,
    supports_frames: false,
    supports_seed: true,
    default_width: null,
    default_height: null,
    default_steps: null,
    default_frames: null,
  },
];

const graphicsGenerations: any[] = [];

router.get("/graphics/presets", (_req, res) => {
  res.json(graphicsPresets);
});

router.get("/graphics/generations", (req, res) => {
  const limit = Math.min(200, Math.max(1, parseInt(String(req.query.limit ?? "50"), 10) || 50));
  const offset = Math.max(0, parseInt(String(req.query.offset ?? "0"), 10) || 0);
  res.json({
    items: graphicsGenerations.slice(offset, offset + limit),
    total: graphicsGenerations.length,
  });
});

router.post("/graphics/generations", (req, res) => {
  const presetId = String(req.body?.preset_id ?? "");
  const preset = graphicsPresets.find((p) => p.id === presetId);
  if (!preset) { res.status(400).json({ error: "Unknown preset" }); return; }
  if (!preset.available) { res.status(409).json({ error: preset.unavailable_reason || "Preset unavailable" }); return; }
  const prompt = String(req.body?.prompt ?? "").trim();
  if (!prompt) { res.status(400).json({ error: "Prompt required" }); return; }
  const gen: any = {
    id: `ggen-${Date.now()}`,
    kind: preset.kind,
    preset_id: preset.id,
    preset_name: preset.name,
    prompt,
    negative: req.body?.negative ?? null,
    status: "pending",
    progress: 0,
    queue_position: null,
    error_message: null,
    width: req.body?.width ?? preset.default_width,
    height: req.body?.height ?? preset.default_height,
    frames: preset.kind === "video" ? (req.body?.frames ?? preset.default_frames) : null,
    seed: req.body?.seed ?? null,
    duration_seconds: null,
    output_url: null,
    thumbnail_url: null,
    media_id: null,
    created_at: new Date().toISOString(),
    completed_at: null,
  };
  graphicsGenerations.unshift(gen);
  simulateGraphicsGen(gen);
  res.status(202).json(gen);
});

function simulateGraphicsGen(gen: any) {
  const stepMs = gen.kind === "video" ? 2000 : 900;
  gen.status = "queued";
  gen.queue_position = 0;
  const timer = setInterval(() => {
    if (gen.status === "cancelled") { clearInterval(timer); return; }
    if (gen.status === "queued") {
      gen.status = "running";
      gen.queue_position = null;
      if (gen.seed == null) gen.seed = Math.floor(Math.random() * 2 ** 31);
      return;
    }
    gen.progress = Math.min(100, gen.progress + (gen.kind === "video" ? 9 : 25));
    if (gen.progress >= 100) {
      gen.status = "success";
      gen.completed_at = new Date().toISOString();
      if (gen.kind === "video") gen.duration_seconds = Math.round(((gen.frames ?? 81) / 24) * 10) / 10;
      gen.output_url = `/api/graphics/generations/${gen.id}/output`;
      gen.thumbnail_url = `/api/graphics/generations/${gen.id}/thumbnail`;
      clearInterval(timer);
    }
  }, stepMs);
}

router.get("/graphics/generations/:id", (req, res) => {
  const gen = graphicsGenerations.find((g) => g.id === req.params.id);
  if (!gen) { res.status(404).json({ error: "Not found" }); return; }
  res.json(gen);
});

router.delete("/graphics/generations/:id", (req, res) => {
  const idx = graphicsGenerations.findIndex((g) => g.id === req.params.id);
  if (idx === -1) { res.status(404).json({ error: "Not found" }); return; }
  graphicsGenerations.splice(idx, 1);
  res.status(204).end();
});

router.post("/graphics/generations/:id/cancel", (req, res) => {
  const gen = graphicsGenerations.find((g) => g.id === req.params.id);
  if (!gen) { res.status(404).json({ error: "Not found" }); return; }
  if (gen.status === "success" || gen.status === "error" || gen.status === "cancelled") {
    res.status(409).json({ error: "Already finished" });
    return;
  }
  gen.status = "cancelled";
  gen.completed_at = new Date().toISOString();
  res.json(gen);
});

// Output/thumbnail intentionally 404 in the mock (no real files, same as /stream)
router.get("/graphics/generations/:id/output", (_req, res) => {
  res.status(404).json({ error: "No output in Replit preview — generation runs on the production GPU server" });
});

router.get("/graphics/generations/:id/thumbnail", (_req, res) => {
  res.status(404).json({ error: "No thumbnail in Replit preview" });
});

router.post("/graphics/generations/:id/add-to-library", (req, res) => {
  const gen = graphicsGenerations.find((g) => g.id === req.params.id);
  if (!gen) { res.status(404).json({ error: "Not found" }); return; }
  if (gen.status !== "success") { res.status(404).json({ error: "Not finished" }); return; }
  if (gen.kind !== "video") { res.status(409).json({ error: "Only video generations can be added to the library" }); return; }
  if (gen.media_id) { res.status(409).json({ error: "Already added" }); return; }
  const asset: any = {
    id: `media-gen-${Date.now()}`,
    filename: `generated-${gen.preset_id}-${gen.id.slice(-6)}.mp4`,
    original_path: `/uploads/generated-${gen.id.slice(-6)}.mp4`,
    proxy_path: null,
    thumbnail_url: null,
    duration_seconds: gen.duration_seconds,
    width: gen.width,
    height: gen.height,
    fps: 24,
    codec: "h264",
    file_size_bytes: null,
    status: "processing",
    processing_stage: "ingest",
    processing_progress: 0,
    scene_count: 0,
    speaker_count: 0,
    synopsis: null,
    key_moments: [],
    created_at: new Date().toISOString(),
  };
  assets.unshift(asset as any);
  gen.media_id = asset.id;
  res.status(202).json(asset);
});

// ---------------------------------------------------------------------------
// Ratings (provider-agnostic audience measurement; CSV import, OWN_STATIONS env
// in production — mocked here with a generated 30-day dataset)

const OWN_STATIONS = ["OBTV", "OBTV2"];

const RATINGS_STATIONS: { station: string; programs: string[] }[] = [
  { station: "OBTV", programs: ["Morning Rush", "OBTV Midday", "OBTV Evening News"] },
  { station: "OBTV2", programs: ["Daybreak 2", "City Desk", "The 614 Tonight"] },
  { station: "WKRX", programs: ["WKRX Daybreak", "WKRX at Noon", "WKRX News at 7"] },
  { station: "KTVL", programs: ["Metro This Morning", "KTVL Midday Report", "KTVL Tonight"] },
  { station: "WQBN", programs: ["Sunrise 5", "News 5 at Noon", "The Evening Desk"] },
];

const RATING_SLOTS = [
  { start: "07:00", end: "09:00" },
  { start: "12:00", end: "12:30" },
  { start: "19:00", end: "19:30" },
];

const round1 = (n: number) => Math.round(n * 10) / 10;
const ratingsNoise = (seed: number) => {
  const x = Math.sin(seed * 12.9898) * 43758.5453;
  return x - Math.floor(x);
};

const ratingsRecords: any[] = [];
const ratingsImports: any[] = [];
let ratingsSeq = 1;

(function seedRatings() {
  const seedImportId = "rimp-001";
  const today = new Date();
  for (let back = 29; back >= 0; back--) {
    const day = new Date(today.getTime() - back * 86400000);
    const airDate = day.toISOString().slice(0, 10);
    const weekend = day.getUTCDay() === 0 || day.getUTCDay() === 6;
    RATINGS_STATIONS.forEach((s, si) => {
      s.programs.forEach((program, pi) => {
        const seed = si * 997 + pi * 131 + (29 - back);
        // Own stations trend slightly upward across the month; evening slots rate highest.
        const base = 3.4 - si * 0.45 + pi * 0.9 + (si < 2 ? (29 - back) * 0.012 : 0);
        let rating = base + ratingsNoise(seed) * 1.1 - 0.55;
        if (weekend) rating *= 0.78;
        rating = Math.max(0.3, round1(rating));
        const share = round1(rating * (5.2 + ratingsNoise(seed + 7) * 1.6));
        const viewers = Math.round(rating * 12400 + ratingsNoise(seed + 13) * 3000);
        const demo =
          pi === 2
            ? { "A25-54": round1(rating * (0.45 + ratingsNoise(seed + 3) * 0.2)), "P2+": rating }
            : null;
        let asset_id: string | null = null;
        if (s.station === "OBTV" && pi === 2 && back === 2) asset_id = assets[0]?.id ?? null;
        if (s.station === "OBTV" && pi === 0 && back === 4) asset_id = assets[1]?.id ?? null;
        ratingsRecords.push({
          id: `rating-${ratingsSeq++}`,
          provider: "nielsen",
          market: "Columbus, OH",
          station: s.station,
          program_title: program,
          air_date: airDate,
          start_time: RATING_SLOTS[pi].start,
          end_time: RATING_SLOTS[pi].end,
          rating,
          share,
          viewers,
          demo,
          asset_id,
          import_id: seedImportId,
          created_at: now,
        });
      });
    });
  }
  ratingsImports.push({
    id: seedImportId,
    filename: "nielsen_overnights_seed.csv",
    provider: "nielsen",
    row_count: ratingsRecords.length,
    error_count: 0,
    errors: null,
    created_at: now,
  });
})();

const ratingIsOwn = (station: string) => OWN_STATIONS.includes(station.toUpperCase());

const ratingOut = (r: any) => ({
  ...r,
  is_own: ratingIsOwn(r.station),
  asset_filename: r.asset_id ? assets.find((a) => a.id === r.asset_id)?.filename ?? null : null,
});

router.get("/ratings", (req, res) => {
  const { from, to, station, provider, q, asset_id } = req.query as Record<string, string | undefined>;
  let rows = ratingsRecords.slice();
  if (from) rows = rows.filter((r) => r.air_date >= from);
  if (to) rows = rows.filter((r) => r.air_date <= to);
  if (station) rows = rows.filter((r) => r.station.toUpperCase() === station.toUpperCase());
  if (provider) rows = rows.filter((r) => r.provider === provider);
  if (q) {
    const needle = q.toLowerCase();
    rows = rows.filter((r) => r.program_title.toLowerCase().includes(needle));
  }
  if (asset_id) rows = rows.filter((r) => r.asset_id === asset_id);
  rows.sort((a, b) => (b.air_date + (b.start_time ?? "")).localeCompare(a.air_date + (a.start_time ?? "")) || a.station.localeCompare(b.station));
  const total = rows.length;
  const offset = Math.max(0, parseInt((req.query.offset as string) ?? "0", 10) || 0);
  const limit = Math.min(500, Math.max(1, parseInt((req.query.limit as string) ?? "50", 10) || 50));
  res.json({ items: rows.slice(offset, offset + limit).map(ratingOut), total });
});

router.get("/ratings/overview", (req, res) => {
  const to = (req.query.to as string) || new Date().toISOString().slice(0, 10);
  const from =
    (req.query.from as string) ||
    new Date(Date.now() - 29 * 86400000).toISOString().slice(0, 10);
  const inRange = ratingsRecords.filter((r) => r.air_date >= from && r.air_date <= to);
  const own = inRange.filter((r) => ratingIsOwn(r.station));

  const avg = (rows: any[], field: string) => {
    const vals = rows.map((r) => r[field]).filter((v) => v != null);
    return vals.length ? round1(vals.reduce((s, v) => s + v, 0) / vals.length) : null;
  };

  const byDate = new Map<string, any[]>();
  for (const r of own) {
    if (!byDate.has(r.air_date)) byDate.set(r.air_date, []);
    byDate.get(r.air_date)!.push(r);
  }
  const trend = [...byDate.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([date, rows]) => ({
      date,
      avg_rating: avg(rows, "rating"),
      avg_share: avg(rows, "share"),
      total_viewers: rows.some((r) => r.viewers != null)
        ? rows.reduce((s, r) => s + (r.viewers ?? 0), 0)
        : null,
    }));

  const byStation = new Map<string, any[]>();
  for (const r of inRange) {
    if (!byStation.has(r.station)) byStation.set(r.station, []);
    byStation.get(r.station)!.push(r);
  }
  const station_shares = [...byStation.entries()]
    .map(([st, rows]) => ({
      station: st,
      is_own: ratingIsOwn(st),
      avg_rating: avg(rows, "rating"),
      avg_share: avg(rows, "share"),
      record_count: rows.length,
    }))
    .sort((a, b) => (b.avg_share ?? -1) - (a.avg_share ?? -1));

  const byProgram = new Map<string, any[]>();
  for (const r of own) {
    const key = `${r.program_title}\u0000${r.station}`;
    if (!byProgram.has(key)) byProgram.set(key, []);
    byProgram.get(key)!.push(r);
  }
  const top_programs = [...byProgram.entries()]
    .map(([key, rows]) => {
      const [program_title, st] = key.split("\u0000");
      const ratings = rows.map((r) => r.rating).filter((v: number | null) => v != null);
      return {
        program_title,
        station: st,
        airings: rows.length,
        avg_rating: avg(rows, "rating"),
        avg_share: avg(rows, "share"),
        best_rating: ratings.length ? Math.max(...ratings) : null,
      };
    })
    .sort((a, b) => (b.avg_rating ?? -1) - (a.avg_rating ?? -1))
    .slice(0, 10);

  const viewersVals = own.map((r) => r.viewers).filter((v) => v != null);
  res.json({
    own_stations: OWN_STATIONS,
    kpis: {
      record_count: own.length,
      program_count: new Set(own.map((r) => r.program_title)).size,
      avg_rating: avg(own, "rating"),
      avg_share: avg(own, "share"),
      peak_viewers: viewersVals.length ? Math.max(...viewersVals) : null,
    },
    trend,
    station_shares,
    top_programs,
  });
});

const RATINGS_HEADER_ALIASES: Record<string, string> = {
  date: "air_date", air_date: "air_date", airdate: "air_date",
  station: "station", channel: "station", call_letters: "station",
  program: "program_title", program_title: "program_title", program_name: "program_title", title: "program_title",
  start: "start_time", start_time: "start_time", time: "start_time",
  end: "end_time", end_time: "end_time",
  rating: "rating", hh_rtg: "rating", hh_rating: "rating", rtg: "rating",
  share: "share", hh_share: "share", shr: "share",
  viewers: "viewers", impressions: "viewers", impressions_000: "viewers", avg_audience: "viewers", aa_000: "viewers",
  market: "market", dma: "market",
};

const normalizeCsvHeader = (h: string) => h.trim().toLowerCase().replace(/[^a-z0-9+-]+/g, "_").replace(/^_+|_+$/g, "");

const splitCsvLine = (line: string): string[] => {
  const out: string[] = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quoted) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (c === '"') quoted = false;
      else cur += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { out.push(cur); cur = ""; }
    else cur += c;
  }
  out.push(cur);
  return out.map((v) => v.trim());
};

const parseCsvDate = (v: string): string | null => {
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return v;
  const us = v.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (us) return `${us[3]}-${us[1].padStart(2, "0")}-${us[2].padStart(2, "0")}`;
  return null;
};

router.post("/ratings/import", upload.single("file"), (req, res) => {
  const file = (req as any).file as { originalname: string; buffer: Buffer } | undefined;
  if (!file) { res.status(400).json({ error: "No file uploaded" }); return; }
  const provider = (req.body?.provider as string) || "manual";
  const defaultMarket = (req.body?.market as string) || null;
  const text = file.buffer.toString("utf-8").replace(/^\uFEFF/, "");
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (lines.length < 2) { res.status(400).json({ error: "CSV has no data rows" }); return; }

  const rawHeaders = splitCsvLine(lines[0]).map(normalizeCsvHeader);
  const fields = rawHeaders.map((h) =>
    h.startsWith("demo_") ? { kind: "demo" as const, key: h.slice(5) } :
    RATINGS_HEADER_ALIASES[h] ? { kind: "field" as const, key: RATINGS_HEADER_ALIASES[h] } :
    { kind: "skip" as const, key: h },
  );
  if (!fields.some((f) => f.kind === "field" && f.key === "air_date") ||
      !fields.some((f) => f.kind === "field" && f.key === "station") ||
      !fields.some((f) => f.kind === "field" && f.key === "program_title")) {
    res.status(400).json({ error: "CSV must include date, station, and program columns" });
    return;
  }

  const errors: string[] = [];
  const inserted: any[] = [];
  const importId = `rimp-${Date.now()}`;
  for (let i = 1; i < lines.length; i++) {
    const cells = splitCsvLine(lines[i]);
    const row: any = { demo: null as Record<string, number> | null };
    fields.forEach((f, ci) => {
      const v = cells[ci]?.trim() ?? "";
      if (!v) return;
      if (f.kind === "demo") {
        const n = parseFloat(v.replace(/,/g, ""));
        if (!isNaN(n)) { row.demo = row.demo ?? {}; row.demo[f.key] = n; }
      } else if (f.kind === "field") {
        row[f.key] = v;
      }
    });
    const airDate = row.air_date ? parseCsvDate(row.air_date) : null;
    if (!airDate || !row.station || !row.program_title) {
      if (errors.length < 5) errors.push(`Row ${i + 1}: missing/invalid date, station, or program`);
      continue;
    }
    const num = (v: string | undefined) => {
      if (v == null) return null;
      const n = parseFloat(String(v).replace(/,/g, ""));
      return isNaN(n) ? null : n;
    };
    const viewersNum = num(row.viewers);
    inserted.push({
      id: `rating-${ratingsSeq++}`,
      provider,
      market: row.market ?? defaultMarket,
      station: String(row.station).toUpperCase(),
      program_title: row.program_title,
      air_date: airDate,
      start_time: row.start_time ?? null,
      end_time: row.end_time ?? null,
      rating: num(row.rating),
      share: num(row.share),
      viewers: viewersNum != null ? Math.round(viewersNum) : null,
      demo: row.demo,
      asset_id: null,
      import_id: importId,
      created_at: new Date().toISOString(),
    });
  }
  const errorCount = lines.length - 1 - inserted.length;
  if (inserted.length === 0) {
    res.status(400).json({ error: `No valid rows (${errorCount} skipped)`, errors });
    return;
  }
  ratingsRecords.push(...inserted);
  const imp = {
    id: importId,
    filename: file.originalname,
    provider,
    row_count: inserted.length,
    error_count: errorCount,
    errors: errors.length ? errors : null,
    created_at: new Date().toISOString(),
  };
  ratingsImports.unshift(imp);
  res.status(201).json(imp);
});

router.get("/ratings/imports", (_req, res) => {
  res.json(ratingsImports);
});

router.delete("/ratings/imports/:id", (req, res) => {
  const idx = ratingsImports.findIndex((i) => i.id === req.params.id);
  if (idx < 0) { res.status(404).json({ error: "Not found" }); return; }
  for (let i = ratingsRecords.length - 1; i >= 0; i--) {
    if (ratingsRecords[i].import_id === req.params.id) ratingsRecords.splice(i, 1);
  }
  ratingsImports.splice(idx, 1);
  res.status(204).end();
});

router.patch("/ratings/:id", (req, res) => {
  const rec = ratingsRecords.find((r) => r.id === req.params.id);
  if (!rec) { res.status(404).json({ error: "Not found" }); return; }
  if ("asset_id" in (req.body ?? {})) {
    const assetId = req.body.asset_id;
    if (assetId != null) {
      const asset = assets.find((a) => a.id === assetId);
      if (!asset) { res.status(404).json({ error: "Asset not found" }); return; }
      rec.asset_id = assetId;
    } else {
      rec.asset_id = null;
    }
  }
  res.json(ratingOut(rec));
});

export default router;
