import { Router } from "express";
import multer from "multer";

const router = Router();

const VIDEO_EXTENSIONS = new Set([
  ".mp4", ".mov", ".mkv", ".avi", ".mxf", ".ts", ".m2ts", ".wmv", ".flv", ".webm",
]);

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 100 * 1024 * 1024 },
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
    created_at: new Date(Date.now() - 86400000 * 3).toISOString(),
    updated_at: new Date(Date.now() - 86400000 * 3 + 7200000).toISOString(),
  },
];

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

const clipLists = [
  {
    id: "cl-001",
    name: "Infrastructure Interview Highlights",
    description: "Key moments from the Sarah Chen infrastructure interview",
    created_at: new Date(Date.now() - 7200000).toISOString(),
    clips: [
      { id: "clip-001", media_id: "asset-001", filename: "interview_sarah_chen.mp4", start_time: 15.5, end_time: 71.3, label: "On local AI infrastructure", notes: null },
      { id: "clip-002", media_id: "asset-001", filename: "interview_sarah_chen.mp4", start_time: 127.8, end_time: 180.0, label: "Q3 results discussion", notes: null },
    ],
  },
];

// ── Media ────────────────────────────────────────────────────────────────────
router.get("/media/stats/summary", (_req, res) => {
  res.json({
    total_assets: assets.length,
    total_duration_seconds: assets.reduce((s, a) => s + (a.duration_seconds || 0), 0),
    status_counts: { ready: 2, processing: 1, pending: 1, error: 1 },
    storage_bytes: assets.reduce((s, a) => s + (a.file_size_bytes || 0), 0),
    recent_activity: assets.slice(0, 5),
  });
});

router.get("/media", (_req, res) => {
  res.json({ items: assets, total: assets.length });
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

router.get("/media/:id/faces", (req, res) => {
  res.json([]);
});

// ── Search ────────────────────────────────────────────────────────────────────
router.post("/search", (req, res) => {
  const query = (req.body.query || "").toLowerCase();
  const results = transcript
    .filter((s) => s.text.toLowerCase().includes(query.split(" ")[0] || query))
    .map((s) => {
      const asset = assets.find((a) => a.id === s.media_id);
      return {
        media_id: s.media_id,
        filename: asset?.filename || "unknown",
        thumbnail_url: null,
        start_time: s.start_time,
        end_time: s.end_time,
        score: 0.72 + Math.random() * 0.25,
        match_type: "transcript",
        snippet: s.text,
      };
    });
  setTimeout(() => res.json({ results, query: req.body.query, took_ms: 42 + Math.random() * 80 }), 150);
});

router.get("/search/history", (_req, res) => {
  res.json(searchHistory);
});

// ── Jobs ─────────────────────────────────────────────────────────────────────
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

router.get("/jobs", (_req, res) => {
  res.json(jobs);
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
    logs: [`Target language: ${lang}`, `Loading TTS model: facebook/mms-tts-${lang}`],
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

router.get("/ai/conversations/:id/messages", (req, res) => {
  const msgs = conversationMessages[req.params.id];
  if (!msgs) {
    res.status(404).json({ detail: "Conversation not found" });
    return;
  }
  res.json(msgs);
});

// ── Clips ─────────────────────────────────────────────────────────────────────
router.get("/clips", (_req, res) => {
  res.json(clipLists);
});

router.post("/clips", (req, res) => {
  const newList = {
    id: `cl-${Date.now()}`,
    name: req.body.name,
    description: req.body.description || null,
    created_at: new Date().toISOString(),
    clips: (req.body.clips || []).map((c: any, i: number) => ({
      id: `clip-${Date.now()}-${i}`,
      media_id: c.media_id,
      filename: assets.find((a) => a.id === c.media_id)?.filename || "unknown",
      start_time: c.start_time,
      end_time: c.end_time,
      label: c.label || null,
      notes: null,
    })),
  };
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
  res.json({ ...cl, ...req.body });
});

router.delete("/clips/:id", (_req, res) => {
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
    : `TITLE: ${cl.name}\nFCM: NON-DROP FRAME\n`;
  res.json({ format: fmt, content, filename: `${cl.name.replace(/ /g, "_")}.${fmt}` });
});

// ── Renders & publishing ─────────────────────────────────────────────────────

type MockRender = {
  id: string; media_id: string; filename: string | null; clip_list_id: string | null;
  label: string | null; start_time: number; end_time: number;
  preset: string; burn_captions: boolean; status: string; progress: number;
  output_url: string | null; error_message: string | null;
  publish_status: string | null; publish_url: string | null; publish_error: string | null;
  created_at: string; finished_at: string | null;
  _startedAt: number; _publishStartedAt: number | null;
};

const renders: MockRender[] = [];

function makeRender(mediaId: string, start: number, end: number, preset: string, burnCaptions: boolean, label: string | null, clipListId: string | null): MockRender {
  return {
    id: `render-${Date.now()}-${Math.floor(Math.random() * 10000)}`,
    media_id: mediaId,
    filename: assets.find((a) => a.id === mediaId)?.filename || null,
    clip_list_id: clipListId,
    label,
    start_time: start,
    end_time: end,
    preset,
    burn_captions: burnCaptions,
    status: "pending",
    progress: 0,
    output_url: null,
    error_message: null,
    publish_status: null,
    publish_url: null,
    publish_error: null,
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
  const created = cl.clips.map((c) => makeRender(c.media_id, c.start_time, c.end_time, preset, burn, c.label, cl.id));
  renders.unshift(...created);
  res.status(202).json(created.map(renderOut));
});

router.get("/renders", (req, res) => {
  renders.forEach(tickRender);
  let out = renders;
  if (req.query.clip_list_id) out = out.filter((r) => r.clip_list_id === req.query.clip_list_id);
  res.json(out.map(renderOut));
});

router.post("/renders", (req, res) => {
  const asset = assets.find((a) => a.id === req.body.media_id);
  if (!asset) { res.status(404).json({ detail: "Media not found" }); return; }
  const r = makeRender(
    req.body.media_id, req.body.start_time, req.body.end_time,
    req.body.preset || "original", !!req.body.burn_captions,
    req.body.label || null, req.body.clip_list_id || null,
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
  id: string; prompt: string; preset: string; burn_captions: boolean;
  clips: { media_id: string; filename: string; start_time: number; end_time: number; snippet: string | null }[];
  status: string; progress: number;
  output_url: string | null; error_message: string | null;
  created_at: string; finished_at: string | null;
  _startedAt: number;
};

const reels: MockReel[] = [];

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

router.get("/reels", (_req, res) => {
  reels.forEach(tickReel);
  res.json(reels.map(reelOut));
});

router.post("/reels", (req, res) => {
  const prompt: string = (req.body.prompt || "").trim();
  if (prompt.length < 3) { res.status(400).json({ detail: "Prompt is too short" }); return; }
  const preset = req.body.preset || "original";
  const burn = !!req.body.burn_captions;
  const maxClips = Math.min(Math.max(req.body.max_clips || 6, 1), 12);

  // Same keyword scoring the mock script-match uses.
  const words = prompt.toLowerCase().split(/\W+/).filter((w) => w.length > 3);
  const scored = transcript
    .map((seg) => {
      const text = seg.text.toLowerCase();
      const hits = words.filter((w) => text.includes(w)).length;
      return { seg, score: words.length ? hits / words.length : 0 };
    })
    .filter((s) => s.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, maxClips);

  const picked = scored.length ? scored.map((s) => s.seg) : transcript.slice(0, Math.min(maxClips, 4));
  if (!picked.length) {
    res.status(404).json({ detail: "No moments in the library match that prompt — try different wording" });
    return;
  }

  const clips = picked
    .map((seg) => {
      const asset = assets.find((a) => a.id === seg.media_id);
      const start = Math.max(0, seg.start_time - 1);
      const end = Math.max(start + 6, seg.end_time);
      return {
        media_id: seg.media_id,
        filename: asset?.filename || "unknown.mp4",
        start_time: start,
        end_time: Math.min(end, start + 30),
        snippet: seg.text,
      };
    })
    .sort((a, b) => a.media_id.localeCompare(b.media_id) || a.start_time - b.start_time);

  const reel: MockReel = {
    id: `reel-${Date.now()}-${Math.floor(Math.random() * 10000)}`,
    prompt,
    preset,
    burn_captions: burn,
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

// ── Script match ─────────────────────────────────────────────────────────────

router.post("/search/script-match", (req, res) => {
  const script: string = req.body.script || "";
  const perLine = Math.min(Math.max(req.body.matches_per_line || 3, 1), 10);
  const lines = script
    .split("\n")
    .map((l: string) => l.trim())
    .filter((l: string) => l.length >= 3)
    .slice(0, 50);

  const out = lines.map((line: string) => {
    const words = line.toLowerCase().split(/\W+/).filter((w: string) => w.length > 3);
    const scored = transcript
      .map((seg) => {
        const text = seg.text.toLowerCase();
        const hits = words.filter((w: string) => text.includes(w)).length;
        return { seg, score: words.length ? hits / words.length : 0 };
      })
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, perLine);
    const matches = (scored.length ? scored : transcript.slice(0, 1).map((seg) => ({ seg, score: 0.42 })))
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
  },
];

const personAppearances: Record<string, any[]> = {
  "person-001": [
    { media_id: "asset-001", filename: "interview_sarah_chen.mp4", thumbnail_url: null, duration_seconds: 1122.5, speaker_label: "SPEAKER_00", face_cluster_id: "cluster-001", speaking_seconds: 812.4, segment_count: 96, first_spoken_at: 2.1 },
    { media_id: "asset-003", filename: "documentary_rough_cut_v3.mkv", thumbnail_url: null, duration_seconds: 5406.0, speaker_label: "SPEAKER_02", face_cluster_id: null, speaking_seconds: 734.5, segment_count: 84, first_spoken_at: 341.8 },
    { media_id: "asset-004", filename: "press_conference_may15.mp4", thumbnail_url: null, duration_seconds: 1863.2, speaker_label: "SPEAKER_01", face_cluster_id: "cluster-004", speaking_seconds: 298.3, segment_count: 34, first_spoken_at: 122.6 },
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

let libraryInsights: { generated_at: string | null; headline: string | null; insights: { title: string; detail: string }[] } = {
  generated_at: new Date(Date.now() - 86400000).toISOString(),
  headline:
    "An interview-heavy technology archive anchored by Sarah Chen, with growing but under-processed civic and documentary footage.",
  insights: [
    {
      title: "Sarah Chen is the library's central figure",
      detail:
        "She appears in 3 of 5 assets and accounts for over 30 minutes of speaking time — more than any other person. Her recurring themes (local AI infrastructure, GPU computing) effectively define the archive's editorial identity.",
    },
    {
      title: "Interview format dominates the collection",
      detail:
        "Most speech content comes from two-person interview setups hosted by Marcus Webb. Consider tagging B-roll and civic footage more aggressively, since search quality currently skews toward interview content.",
    },
    {
      title: "Civic footage is a single point of coverage",
      detail:
        "All municipal government content traces to one council meeting featuring Councilwoman Rivera. If civic coverage matters to the library, this is a significant gap.",
    },
    {
      title: "One speaker remains unidentified",
      detail:
        "A speaker in the May 15 press conference could not be matched to any known person or named from context. Reviewing and naming them would improve cross-asset tracking.",
    },
  ],
};

router.get("/people", (req, res) => {
  const limit = Math.min(Math.max(parseInt(String(req.query.limit ?? "48"), 10) || 48, 1), 200);
  const offset = Math.max(parseInt(String(req.query.offset ?? "0"), 10) || 0, 0);
  res.json({ items: people.slice(offset, offset + limit), total: people.length });
});

router.get("/people/:id", (req, res) => {
  const p = people.find((x) => x.id === req.params.id);
  if (!p) { res.status(404).json({ error: "Not found" }); return; }
  res.json({ ...p, appearances: personAppearances[p.id] ?? [] });
});

router.patch("/people/:id", (req, res) => {
  const p = people.find((x) => x.id === req.params.id);
  if (!p) { res.status(404).json({ error: "Not found" }); return; }
  const name = String(req.body?.display_name ?? "").trim();
  if (!name) { res.status(422).json({ error: "display_name must not be empty" }); return; }
  p.display_name = name;
  p.name_source = "manual";
  p.updated_at = new Date().toISOString();
  res.json(p);
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
  personAppearances[target.id] = [...(personAppearances[target.id] ?? []), ...(personAppearances[sourceId] ?? [])];
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

router.get("/insights", (_req, res) => {
  res.json({
    generated_at: libraryInsights.generated_at,
    headline: libraryInsights.headline,
    insights: libraryInsights.insights,
    stats: {
      total_assets: assets.length,
      total_duration_seconds: assets.reduce((s, a: any) => s + (a.duration_seconds || 0), 0),
      total_people: people.length,
      transcribed_assets: 4,
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
    top_topics: [
      { topic: "local AI infrastructure", asset_count: 3 },
      { topic: "GPU computing", asset_count: 2 },
      { topic: "video processing", asset_count: 2 },
      { topic: "zoning policy", asset_count: 1 },
      { topic: "budget allocation", asset_count: 1 },
      { topic: "urban development", asset_count: 1 },
    ],
  });
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

export default router;
