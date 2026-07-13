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

const transcript = [
  { id: "seg-001", media_id: "asset-001", start_time: 2.1, end_time: 8.4, text: "Thank you for having me. I'm really excited to talk about what we've been building.", speaker: "SPEAKER_00", confidence: 0.94 },
  { id: "seg-002", media_id: "asset-001", start_time: 9.0, end_time: 14.2, text: "So Sarah, can you tell us about the new infrastructure initiative?", speaker: "SPEAKER_01", confidence: 0.91 },
  { id: "seg-003", media_id: "asset-001", start_time: 15.5, end_time: 32.0, text: "Absolutely. We've been working on a distributed processing pipeline that can handle petabyte-scale video archives. The key insight was that you don't need cloud infrastructure to do this at scale.", speaker: "SPEAKER_00", confidence: 0.96 },
  { id: "seg-004", media_id: "asset-001", start_time: 33.1, end_time: 48.7, text: "That's fascinating. Most organizations assume you need AWS or Google Cloud for anything at this scale.", speaker: "SPEAKER_01", confidence: 0.88 },
  { id: "seg-005", media_id: "asset-001", start_time: 50.0, end_time: 71.3, text: "Right, and that's exactly the misconception we're challenging. With modern GPU hardware and the right software architecture, you can build a fully local AI inference stack that outperforms cloud solutions on throughput.", speaker: "SPEAKER_00", confidence: 0.97 },
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
  res.json(transcript.filter((s) => s.media_id === req.params.id));
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

export default router;
