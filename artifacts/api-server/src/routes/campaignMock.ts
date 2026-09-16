import { Router, type Request } from "express";
import { randomUUID } from "node:crypto";

type CampaignStatus = "draft" | "active" | "completed" | "archived";
type CampaignKind = "promo" | "reel" | "thumbnail" | "social_copy";
type DeliverableStatus =
  | "pending"
  | "queued"
  | "running"
  | "draft_ready"
  | "ready"
  | "failed"
  | "dispatch_unknown";

export type CampaignClip = {
  media_id: string;
  start_time: number;
  end_time: number;
  filename?: string;
  snippet?: string;
};

type CampaignProject = {
  id: string;
  name: string;
  description: string | null;
  script: string | null;
  status: string;
  media_ids: string[];
  media_ranges?: Record<string, { in: number; out: number }> | null;
  target_runtime_seconds: number | null;
  created_at: string;
  updated_at: string | null;
};

type CampaignMedia = {
  id: string;
  filename?: string;
  duration_seconds?: number | null;
};

type SourceJob = {
  id: string;
  status: string;
  progress?: number | null;
  error_message?: string | null;
  output_url?: string | null;
  [key: string]: unknown;
};

export type CampaignMockAdapters = {
  listProjects: () => CampaignProject[];
  getProject: (id: string) => CampaignProject | undefined;
  createProject: (name: string) => CampaignProject;
  syncProjectSelection: (projectId: string, clips: CampaignClip[]) => void;
  getMedia: (id: string) => CampaignMedia | undefined;
  createStory: (input: {
    projectId: string;
    assetIds: string[];
    prompt: string;
    targetDurationSeconds: number | null;
  }) => SourceJob;
  getStory: (id: string) => SourceJob | undefined;
  createReel: (input: {
    projectId: string;
    prompt: string;
    targetDurationSeconds: number | null;
    aspectRatio: string;
    clips: CampaignClip[];
  }) => SourceJob;
  getReel: (id: string) => SourceJob | undefined;
  createGraphics: (input: { prompt: string; aspectRatio: string }) => SourceJob;
  getGraphics: (id: string) => SourceJob | undefined;
};

type CampaignDeliverable = {
  id: string;
  campaign_id: string;
  kind: CampaignKind;
  label: string;
  channel: string;
  language: string;
  target_duration_seconds: number | null;
  aspect_ratio: string;
  notes: string | null;
  status: DeliverableStatus;
  job_status: string | null;
  progress: number | null;
  job_id: string | null;
  job_type: string | null;
  job_reference: { id: string; type: string; retry_of?: string } | null;
  output: Record<string, unknown> | null;
  error_message: string | null;
  created_by: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
};

type Campaign = {
  id: string;
  project_id: string;
  name: string;
  brief: string;
  objective: string;
  audience: string;
  key_message: string;
  tone: string;
  call_to_action: string;
  channels: string[];
  languages: string[];
  due_date: string | null;
  status: CampaignStatus;
  selected_clips: CampaignClip[];
  deliverables: CampaignDeliverable[];
  created_by: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
};

type UserRequest = Request & { user?: { id?: string; username?: string } };

const CAMPAIGN_STATUSES = new Set<CampaignStatus>(["draft", "active", "completed", "archived"]);
const CAMPAIGN_KINDS = new Set<CampaignKind>(["promo", "reel", "thumbnail", "social_copy"]);
const CAMPAIGN_FIELDS = [
  "name", "brief", "objective", "audience", "key_message", "tone", "call_to_action",
  "channels", "languages", "due_date", "status", "selected_clips",
] as const;
const DELIVERABLE_FIELDS = [
  "kind", "label", "channel", "language", "target_duration_seconds", "aspect_ratio", "notes",
] as const;

function nowIso() {
  return new Date().toISOString();
}

function currentUserId(req: Request): string | null {
  const user = (req as UserRequest).user;
  return user?.id || user?.username || null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function errorResponse(
  res: { status: (status: number) => { json: (body: unknown) => unknown } },
  status: number,
  code: string,
  message: string,
  details?: unknown,
) {
  const error: { code: string; message: string; details?: unknown } = { code, message };
  if (details !== undefined) error.details = details;
  res.status(status).json({ error });
}

function requireBody(req: Request, res: Parameters<typeof errorResponse>[0]): Record<string, unknown> | null {
  if (!isRecord(req.body)) {
    errorResponse(res, 400, "invalid_request", "Request body must be a JSON object");
    return null;
  }
  return req.body;
}

function stringField(
  body: Record<string, unknown>,
  field: string,
  required: boolean,
  maxLength?: number,
): { value?: string; error?: string } {
  const value = body[field];
  if (value === undefined) {
    return required ? { error: `${field} is required` } : {};
  }
  if (typeof value !== "string" || !value.trim()) return { error: `${field} must be a non-empty string` };
  if (maxLength !== undefined && value.trim().length > maxLength) {
    return { error: `${field} must be at most ${maxLength} characters` };
  }
  return { value: value.trim() };
}

function validateStringArray(body: Record<string, unknown>, field: string): { value?: string[]; error?: string } {
  const value = body[field];
  if (!Array.isArray(value)) return { error: `${field} must be an array of strings` };
  if (!value.length) return { error: `${field} must contain at least one string` };
  const result: string[] = [];
  for (const item of value) {
    if (typeof item !== "string" || !item.trim()) return { error: `${field} must contain only non-empty strings` };
    result.push(item.trim());
  }
  return { value: result };
}

function validateDate(value: unknown): { value?: string | null; error?: string } {
  if (value === null) return { value: null };
  if (typeof value !== "string") return { error: "due_date must be an ISO-8601 string or null" };
  // Date.parse accepts values such as "tomorrow" and silently normalizes
  // impossible-looking input. Campaign dates are persisted as explicit UTC ISO.
  const iso = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?Z$/;
  const match = iso.exec(value);
  const parsed = new Date(value);
  const milliseconds = Number((match?.[7] || "").padEnd(3, "0") || 0);
  const dateIsExact = match !== null &&
    !Number.isNaN(parsed.getTime()) &&
    parsed.getUTCFullYear() === Number(match[1]) &&
    parsed.getUTCMonth() + 1 === Number(match[2]) &&
    parsed.getUTCDate() === Number(match[3]) &&
    parsed.getUTCHours() === Number(match[4]) &&
    parsed.getUTCMinutes() === Number(match[5]) &&
    parsed.getUTCSeconds() === Number(match[6]) &&
    parsed.getUTCMilliseconds() === milliseconds;
  if (!dateIsExact) {
    return { error: "due_date must be a valid ISO-8601 UTC timestamp" };
  }
  return { value };
}

function validateClips(
  value: unknown,
  adapters: CampaignMockAdapters,
): { value?: CampaignClip[]; error?: string; details?: unknown } {
  if (!Array.isArray(value)) return { error: "selected_clips must be an array" };
  const clips: CampaignClip[] = [];
  for (let i = 0; i < value.length; i += 1) {
    const raw = value[i];
    if (!isRecord(raw)) return { error: `selected_clips[${i}] must be an object` };
    if (typeof raw.media_id !== "string" || !raw.media_id.trim()) {
      return { error: `selected_clips[${i}].media_id must be a non-empty string` };
    }
    if (typeof raw.start_time !== "number" || !Number.isFinite(raw.start_time) ||
        typeof raw.end_time !== "number" || !Number.isFinite(raw.end_time)) {
      return { error: `selected_clips[${i}] times must be finite numbers` };
    }
    const media = adapters.getMedia(raw.media_id);
    if (!media) {
      return { error: `Selected media ${raw.media_id} was not found`, details: { index: i, media_id: raw.media_id } };
    }
    const duration = media.duration_seconds;
    if (typeof duration !== "number" || !Number.isFinite(duration) || duration < 0) {
      return { error: `Selected media ${raw.media_id} has no usable duration`, details: { index: i, media_id: raw.media_id } };
    }
    if (raw.start_time < 0 || raw.start_time >= raw.end_time || raw.end_time > duration) {
      return {
        error: `selected_clips[${i}] must satisfy 0 <= start_time < end_time <= media duration`,
        details: { index: i, media_id: raw.media_id, duration_seconds: duration },
      };
    }
    if ("filename" in raw && (typeof raw.filename !== "string" || !raw.filename.trim())) {
      return { error: `selected_clips[${i}].filename must be a non-empty string when provided` };
    }
    if ("snippet" in raw && (typeof raw.snippet !== "string" || !raw.snippet.trim())) {
      return { error: `selected_clips[${i}].snippet must be a non-empty string when provided` };
    }
    const clip: CampaignClip = {
      media_id: raw.media_id,
      start_time: raw.start_time,
      end_time: raw.end_time,
    };
    if (typeof raw.filename === "string") clip.filename = raw.filename.trim();
    else if (media.filename) clip.filename = media.filename;
    if (typeof raw.snippet === "string") clip.snippet = raw.snippet.trim();
    clips.push(clip);
  }
  return { value: clips };
}

function validateTargetDuration(value: unknown): { value?: number | null; error?: string } {
  if (value === null) return { value: null };
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return { error: "target_duration_seconds must be a positive number or null" };
  }
  return { value };
}

function unknownFields(body: Record<string, unknown>, allowed: readonly string[]): string[] {
  const set = new Set(allowed);
  return Object.keys(body).filter((key) => !set.has(key));
}

function simulatedOutput(
  kind: CampaignKind,
  job: SourceJob,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    simulated: true,
    preview: true,
    is_final: false,
    kind,
    source_job_id: job.id,
    source_status: job.status,
    output_url: null,
    message: "Simulated preview output — production generation has not run and no final media file exists.",
    ...extra,
  };
}

function sourceStatus(rawStatus: string, kind: CampaignKind): DeliverableStatus {
  // The preview adapters do not synthesize ambiguous queue publishes, but
  // preserve this backend terminal/non-retryable state if an injected source
  // job reports it.
  if (rawStatus === "dispatch_unknown") return "dispatch_unknown";
  if (rawStatus === "pending" || rawStatus === "queued") return "queued";
  if (rawStatus === "selecting") return "running";
  if (rawStatus === "running") return "running";
  if (rawStatus === "success" || rawStatus === "completed" || rawStatus === "ready") {
    // Story and reel jobs produce an editable draft in the preview. They do
    // not produce a final render, so never call those outputs ready.
    return kind === "social_copy" ? "ready" : "draft_ready";
  }
  if (rawStatus === "draft") return kind === "reel" ? "draft_ready" : "pending";
  return "failed";
}

function jobTypeFor(kind: CampaignKind): "story_job" | "reel_job" | "graphics_generation" | "llm_generation" {
  if (kind === "promo") return "story_job";
  if (kind === "reel") return "reel_job";
  if (kind === "thumbnail") return "graphics_generation";
  return "llm_generation";
}

function createSocialCopy(campaign: Campaign, deliverable: CampaignDeliverable): Record<string, unknown> {
  const firstChannel = deliverable.channel || campaign.channels[0] || "social";
  const text = `[Simulated preview] ${`${campaign.key_message} ${campaign.call_to_action}`.trim()}`;
  return simulatedOutput("social_copy", { id: deliverable.id, status: "success" }, {
    text,
    content: text,
    channel: firstChannel,
    language: deliverable.language,
  });
}

export function createCampaignRouter(adapters: CampaignMockAdapters) {
  const router = Router();
  const campaigns: Campaign[] = [];

  function deliverableOut(deliverable: CampaignDeliverable) {
    const outputText = typeof deliverable.output?.text === "string" ? deliverable.output.text : null;
    return {
      id: deliverable.id,
      campaign_id: deliverable.campaign_id,
      kind: deliverable.kind,
      label: deliverable.label,
      channel: deliverable.channel,
      language: deliverable.language,
      target_duration_seconds: deliverable.target_duration_seconds,
      aspect_ratio: deliverable.aspect_ratio,
      notes: deliverable.notes,
      status: deliverable.status,
      job_reference: deliverable.job_reference
        ? { type: deliverable.job_reference.type, id: deliverable.job_reference.id }
        : null,
      output_url: null,
      output_text: outputText,
      error: deliverable.error_message,
      created_at: deliverable.created_at,
      updated_at: deliverable.updated_at,
    };
  }

  function campaignOut(campaign: Campaign) {
    refreshDeliverables(campaign);
    return {
      id: campaign.id,
      project_id: campaign.project_id,
      name: campaign.name,
      brief: campaign.brief,
      objective: campaign.objective,
      audience: campaign.audience,
      key_message: campaign.key_message,
      tone: campaign.tone,
      call_to_action: campaign.call_to_action,
      channels: campaign.channels,
      languages: campaign.languages,
      due_date: campaign.due_date,
      status: campaign.status,
      selected_clips: campaign.selected_clips,
      deliverables: campaign.deliverables.map(deliverableOut),
      created_at: campaign.created_at,
      updated_at: campaign.updated_at,
    };
  }

  function refreshDeliverable(campaign: Campaign, deliverable: CampaignDeliverable) {
    if (!deliverable.job_id || !deliverable.job_type) return;
    let job: SourceJob | undefined;
    if (deliverable.job_type === "story_job") job = adapters.getStory(deliverable.job_id);
    else if (deliverable.job_type === "reel_job") job = adapters.getReel(deliverable.job_id);
    else if (deliverable.job_type === "graphics_generation") job = adapters.getGraphics(deliverable.job_id);
    else if (deliverable.job_type === "llm_generation") {
      // Social copy is persisted directly by the preview helper; there is no
      // separate source-job store to poll.
      deliverable.status = "ready";
      deliverable.job_status = "success";
      deliverable.progress = 100;
      return;
    }
    if (!job) {
      deliverable.status = "failed";
      deliverable.job_status = "missing";
      deliverable.error_message = "The referenced preview job no longer exists";
      deliverable.output = null;
      deliverable.progress = null;
      return;
    }
    let nextStatus = sourceStatus(job.status, deliverable.kind);
    if (deliverable.kind === "thumbnail" &&
        (job.status === "success" || job.status === "completed" || job.status === "ready")) {
      // The existing preview graphics route intentionally has no image bytes.
      // Do not expose its placeholder URL as a ready production asset.
      nextStatus = "failed";
      deliverable.error_message = "Graphics generation completed without an image output in the preview";
    }
    deliverable.status = nextStatus;
    deliverable.job_status = job.status;
    deliverable.progress = typeof job.progress === "number" ? job.progress : null;
    if (nextStatus !== "failed") {
      deliverable.error_message = typeof job.error_message === "string" ? job.error_message : null;
    }
    if (nextStatus === "dispatch_unknown") {
      deliverable.output = null;
      deliverable.error_message ||= "Dispatch outcome is unknown; inspect the referenced job before taking action";
    } else if (nextStatus === "draft_ready" || nextStatus === "ready") {
      deliverable.output = simulatedOutput(campaignDeliverableKind(campaign, deliverable), job);
    } else if (nextStatus === "failed") {
      deliverable.output = null;
      if (!deliverable.error_message) deliverable.error_message = `Preview ${deliverable.job_type} failed`;
    } else {
      deliverable.output = null;
    }
  }

  function campaignDeliverableKind(_campaign: Campaign, deliverable: CampaignDeliverable): CampaignKind {
    return deliverable.kind;
  }

  function refreshDeliverables(campaign: Campaign) {
    for (const deliverable of campaign.deliverables) refreshDeliverable(campaign, deliverable);
  }

  function findCampaign(req: Request, res: Parameters<typeof errorResponse>[0]): Campaign | null {
    const campaign = campaigns.find((item) => item.id === req.params.campaign_id);
    if (!campaign) {
      errorResponse(res, 404, "campaign_not_found", "Campaign not found");
      return null;
    }
    return campaign;
  }

  function findDeliverable(
    req: Request,
    res: Parameters<typeof errorResponse>[0],
  ): { campaign: Campaign; deliverable: CampaignDeliverable } | null {
    const campaign = findCampaign(req, res);
    if (!campaign) return null;
    const deliverable = campaign.deliverables.find((item) => item.id === req.params.deliverable_id);
    if (!deliverable) {
      errorResponse(res, 404, "deliverable_not_found", "Deliverable not found");
      return null;
    }
    refreshDeliverable(campaign, deliverable);
    return { campaign, deliverable };
  }

  function parseCampaignFields(
    body: Record<string, unknown>,
    required: boolean,
  ): { values?: Partial<Campaign>; clips?: CampaignClip[]; error?: string; details?: unknown } {
    const allowed = required
      ? [...CAMPAIGN_FIELDS, "project_id", "project_action"]
      : [...CAMPAIGN_FIELDS];
    const extra = unknownFields(body, allowed);
    if (extra.length) return { error: `Unknown campaign field(s): ${extra.join(", ")}` };
    const values: Partial<Campaign> = {};
    for (const field of ["name", "brief", "objective", "audience", "key_message", "tone", "call_to_action"]) {
      const parsed = stringField(body, field, required, field === "name" ? 200 : undefined);
      if (parsed.error) return { error: parsed.error };
      if (parsed.value !== undefined) (values as Record<string, unknown>)[field] = parsed.value;
    }
    for (const field of ["channels", "languages"]) {
      if (required || field in body) {
        const parsed = validateStringArray(body, field);
        if (parsed.error) return { error: parsed.error };
        (values as Record<string, unknown>)[field] = parsed.value;
      }
    }
    if ("due_date" in body) {
      const parsed = validateDate(body.due_date);
      if (parsed.error) return { error: parsed.error };
      values.due_date = parsed.value ?? null;
    } else if (required) {
      values.due_date = null;
    }
    if ("status" in body) {
      if (typeof body.status !== "string" || !CAMPAIGN_STATUSES.has(body.status as CampaignStatus)) {
        return { error: "status must be draft, active, completed, or archived" };
      }
      values.status = body.status as CampaignStatus;
    } else if (required) {
      values.status = "draft";
    }
    if ("selected_clips" in body) {
      const parsed = validateClips(body.selected_clips, adapters);
      if (parsed.error) return { error: parsed.error, details: parsed.details };
      values.selected_clips = parsed.value;
    } else if (required) {
      // The production request schema defaults omitted selections to an empty
      // list. An explicit null still fails validation above.
      values.selected_clips = [];
    }
    return { values, clips: values.selected_clips };
  }

  function parseDeliverableFields(
    body: Record<string, unknown>,
    required: boolean,
  ): { values?: Partial<CampaignDeliverable>; error?: string } {
    const extra = unknownFields(body, DELIVERABLE_FIELDS);
    if (extra.length) return { error: `Unknown deliverable field(s): ${extra.join(", ")}` };
    const values: Partial<CampaignDeliverable> = {};
    if (required || "kind" in body) {
      if (typeof body.kind !== "string" || !CAMPAIGN_KINDS.has(body.kind as CampaignKind)) {
        return { error: "kind must be promo, reel, thumbnail, or social_copy" };
      }
      values.kind = body.kind as CampaignKind;
    }
    for (const field of ["label", "channel", "language", "aspect_ratio"]) {
      const maxLength = field === "label" ? 200 : field === "channel" ? 100 : field === "language" ? 40 : 40;
      const parsed = stringField(body, field, required, maxLength);
      if (parsed.error) return { error: parsed.error };
      if (parsed.value !== undefined) (values as Record<string, unknown>)[field] = parsed.value;
    }
    if ("target_duration_seconds" in body) {
      const parsed = validateTargetDuration(body.target_duration_seconds);
      if (parsed.error) return { error: parsed.error };
      values.target_duration_seconds = parsed.value ?? null;
    } else if (required) {
      values.target_duration_seconds = null;
    }
    if ("notes" in body) {
      if (body.notes !== null && (typeof body.notes !== "string" || !body.notes.trim())) {
        return { error: "notes must be a non-empty string or null" };
      }
      values.notes = body.notes === null ? null : (body.notes as string).trim();
    }
    return { values };
  }

  function dispatch(
    campaign: Campaign,
    deliverable: CampaignDeliverable,
    retryOf?: string,
  ): SourceJob {
    const prompt = [
      campaign.brief,
      campaign.objective,
      campaign.key_message,
      deliverable.notes || "",
    ].filter(Boolean).join(". ");
    let job: SourceJob;
    if (deliverable.kind === "promo") {
      const assetIds = [...new Set(campaign.selected_clips.map((clip) => clip.media_id))];
      if (!assetIds.length) throw new Error("Select at least one source clip before executing a promo");
      job = adapters.createStory({
        projectId: campaign.project_id,
        assetIds,
        prompt,
        targetDurationSeconds: deliverable.target_duration_seconds,
      });
    } else if (deliverable.kind === "reel") {
      if (!campaign.selected_clips.length) throw new Error("Select at least one source clip before executing a reel");
      job = adapters.createReel({
        projectId: campaign.project_id,
        prompt,
        targetDurationSeconds: deliverable.target_duration_seconds,
        aspectRatio: deliverable.aspect_ratio,
        clips: campaign.selected_clips,
      });
    } else if (deliverable.kind === "thumbnail") {
      job = adapters.createGraphics({ prompt: prompt || campaign.name, aspectRatio: deliverable.aspect_ratio });
    } else {
      job = {
        id: `social-copy-${randomUUID()}`,
        status: "success",
        progress: 100,
      };
    }
    deliverable.job_id = job.id;
    deliverable.job_type = jobTypeFor(deliverable.kind);
    deliverable.job_reference = {
      id: job.id,
      type: deliverable.job_type,
      ...(retryOf ? { retry_of: retryOf } : {}),
    };
    deliverable.job_status = job.status;
    deliverable.status = deliverable.kind === "social_copy" ? "ready" : sourceStatus(job.status, deliverable.kind);
    deliverable.progress = typeof job.progress === "number" ? job.progress : (deliverable.status === "ready" || deliverable.status === "draft_ready" ? 100 : null);
    deliverable.error_message = deliverable.status === "dispatch_unknown"
      ? "Dispatch outcome is unknown; inspect the referenced job before taking action"
      : null;
    deliverable.output = deliverable.kind === "social_copy" ? createSocialCopy(campaign, deliverable) : null;
    deliverable.updated_at = nowIso();
    return job;
  }

  router.get("/", (req, res) => {
    const status = req.query.status;
    if (status !== undefined && (typeof status !== "string" || !CAMPAIGN_STATUSES.has(status as CampaignStatus))) {
      errorResponse(res, 400, "invalid_filter", "status must be draft, active, completed, or archived");
      return;
    }
    const projectId = req.query.project_id;
    if (projectId !== undefined && (typeof projectId !== "string" || !projectId.trim())) {
      errorResponse(res, 400, "invalid_filter", "project_id must be a non-empty string");
      return;
    }
    const queryValue = req.query.q ?? req.query.search;
    if (queryValue !== undefined && (typeof queryValue !== "string" || !queryValue.trim())) {
      errorResponse(res, 400, "invalid_filter", "q/search must be a non-empty string");
      return;
    }
    const q = typeof queryValue === "string" ? queryValue.trim().toLowerCase() : null;
    let list = campaigns;
    if (typeof status === "string") list = list.filter((campaign) => campaign.status === status);
    if (typeof projectId === "string") list = list.filter((campaign) => campaign.project_id === projectId);
    if (q) {
      list = list.filter((campaign) => {
        const project = adapters.getProject(campaign.project_id)?.name || "";
        return [
          campaign.name, campaign.brief, campaign.objective, campaign.audience, campaign.key_message,
          campaign.tone, campaign.call_to_action, project, ...campaign.channels, ...campaign.languages,
        ].some((value) => value.toLowerCase().includes(q));
      });
    }
    res.json({ data: list.map(campaignOut) });
  });

  router.post("/", (req, res) => {
    const body = requireBody(req, res);
    if (!body) return;
    const parsed = parseCampaignFields(body, true);
    if (parsed.error) {
      errorResponse(res, 400, "invalid_campaign", parsed.error, parsed.details);
      return;
    }
    const hasProjectId = "project_id" in body;
    const hasProjectAction = "project_action" in body;
    if (hasProjectId === hasProjectAction) {
      errorResponse(res, 400, "invalid_project_link", "Provide exactly one of project_id or project_action");
      return;
    }
    let projectId: string;
    if (hasProjectId) {
      if (typeof body.project_id !== "string" || !body.project_id.trim()) {
        errorResponse(res, 400, "invalid_project_link", "project_id must be a non-empty string");
        return;
      }
      const project = adapters.getProject(body.project_id);
      if (!project || project.status === "asset") {
        errorResponse(res, 404, "project_not_found", "Project not found");
        return;
      }
      projectId = body.project_id;
    } else {
      if (!isRecord(body.project_action) || unknownFields(body.project_action, ["name"]).length) {
        errorResponse(res, 400, "invalid_project_link", "project_action must contain only a name");
        return;
      }
      const name = stringField(body.project_action, "name", true, 200);
      if (name.error) {
        errorResponse(res, 400, "invalid_project_link", name.error);
        return;
      }
      projectId = adapters.createProject(name.value as string).id;
    }
    const userId = currentUserId(req);
    const created = nowIso();
    const campaignId = `campaign-${randomUUID()}`;
    const values = parsed.values as Required<Pick<Campaign, "name" | "brief" | "objective" | "audience" | "key_message" | "tone" | "call_to_action" | "channels" | "languages" | "selected_clips" | "status">> & { due_date: string | null };
    adapters.syncProjectSelection(projectId, values.selected_clips);
    const campaign: Campaign = {
      id: campaignId,
      project_id: projectId,
      name: values.name,
      brief: values.brief,
      objective: values.objective,
      audience: values.audience,
      key_message: values.key_message,
      tone: values.tone,
      call_to_action: values.call_to_action,
      channels: values.channels,
      languages: values.languages,
      due_date: values.due_date,
      status: values.status,
      selected_clips: values.selected_clips,
      deliverables: [],
      created_by: userId,
      updated_by: userId,
      created_at: created,
      updated_at: created,
    };
    campaigns.unshift(campaign);
    res.status(201).json({ data: campaignOut(campaign) });
  });

  router.get("/:campaign_id", (req, res) => {
    const campaign = findCampaign(req, res);
    if (!campaign) return;
    res.json({ data: campaignOut(campaign) });
  });

  router.patch("/:campaign_id", (req, res) => {
    const campaign = findCampaign(req, res);
    if (!campaign) return;
    if (!adapters.getProject(campaign.project_id)) {
      errorResponse(res, 409, "project_not_found", "Linked project no longer exists");
      return;
    }
    const body = requireBody(req, res);
    if (!body) return;
    if ("project_id" in body || "project_action" in body) {
      errorResponse(res, 400, "immutable_project_link", "The linked project cannot be changed");
      return;
    }
    const parsed = parseCampaignFields(body, false);
    if (parsed.error) {
      errorResponse(res, 400, "invalid_campaign", parsed.error, parsed.details);
      return;
    }
    const values = parsed.values || {};
    if ("selected_clips" in values) {
      adapters.syncProjectSelection(campaign.project_id, values.selected_clips || []);
    }
    Object.assign(campaign, values);
    campaign.updated_by = currentUserId(req);
    campaign.updated_at = nowIso();
    res.json({ data: campaignOut(campaign) });
  });

  router.delete("/:campaign_id", (req, res) => {
    const index = campaigns.findIndex((campaign) => campaign.id === req.params.campaign_id);
    if (index < 0) {
      errorResponse(res, 404, "campaign_not_found", "Campaign not found");
      return;
    }
    campaigns.splice(index, 1);
    res.status(204).send();
  });

  router.post("/:campaign_id/deliverables", (req, res) => {
    const campaign = findCampaign(req, res);
    if (!campaign) return;
    const body = requireBody(req, res);
    if (!body) return;
    const parsed = parseDeliverableFields(body, true);
    if (parsed.error) {
      errorResponse(res, 400, "invalid_deliverable", parsed.error);
      return;
    }
    const values = parsed.values as Required<Pick<CampaignDeliverable, "kind" | "label" | "channel" | "language" | "aspect_ratio">> & { target_duration_seconds: number | null; notes: string | null };
    const created = nowIso();
    const userId = currentUserId(req);
    const deliverable: CampaignDeliverable = {
      id: `deliverable-${randomUUID()}`,
      campaign_id: campaign.id,
      kind: values.kind,
      label: values.label,
      channel: values.channel,
      language: values.language,
      target_duration_seconds: values.target_duration_seconds,
      aspect_ratio: values.aspect_ratio,
      notes: values.notes ?? null,
      status: "pending",
      job_status: null,
      progress: null,
      job_id: null,
      job_type: null,
      job_reference: null,
      output: null,
      error_message: null,
      created_by: userId,
      updated_by: userId,
      created_at: created,
      updated_at: created,
    };
    campaign.deliverables.push(deliverable);
    campaign.updated_by = userId;
    campaign.updated_at = created;
    res.status(201).json({ data: deliverableOut(deliverable) });
  });

  router.patch("/:campaign_id/deliverables/:deliverable_id", (req, res) => {
    const found = findDeliverable(req, res);
    if (!found) return;
    const body = requireBody(req, res);
    if (!body) return;
    const parsed = parseDeliverableFields(body, false);
    if (parsed.error) {
      errorResponse(res, 400, "invalid_deliverable", parsed.error);
      return;
    }
    const values = parsed.values || {};
    if (found.deliverable.job_id && "kind" in values) {
      errorResponse(res, 409, "deliverable_executed", "The kind cannot change after execution has created a job");
      return;
    }
    Object.assign(found.deliverable, values);
    const userId = currentUserId(req);
    found.deliverable.updated_by = userId;
    found.deliverable.updated_at = nowIso();
    found.campaign.updated_by = userId;
    found.campaign.updated_at = found.deliverable.updated_at;
    res.json({ data: deliverableOut(found.deliverable) });
  });

  router.delete("/:campaign_id/deliverables/:deliverable_id", (req, res) => {
    const campaign = findCampaign(req, res);
    if (!campaign) return;
    const index = campaign.deliverables.findIndex((item) => item.id === req.params.deliverable_id);
    if (index < 0) {
      errorResponse(res, 404, "deliverable_not_found", "Deliverable not found");
      return;
    }
    campaign.deliverables.splice(index, 1);
    res.status(204).send();
  });

  router.post("/:campaign_id/deliverables/:deliverable_id/execute", (req, res) => {
    const found = findDeliverable(req, res);
    if (!found) return;
    const body = req.body === undefined ? {} : requireBody(req, res);
    if (!body) return;
    const extra = unknownFields(body, ["retry"]);
    if (extra.length || ("retry" in body && typeof body.retry !== "boolean")) {
      errorResponse(res, 400, "invalid_execution", "execute accepts only a boolean retry field");
      return;
    }
    const retry = body.retry === true;
    const deliverable = found.deliverable;
    if (deliverable.status === "dispatch_unknown") {
      errorResponse(
        res,
        409,
        "dispatch_unknown",
        "Dispatch outcome is unknown; inspect the referenced job before taking action",
      );
      return;
    }
    if ((deliverable.status === "queued" || deliverable.status === "running") && deliverable.job_id) {
      errorResponse(res, 409, "execution_in_progress", "Deliverable execution is already queued or running");
      return;
    }
    if (deliverable.status === "ready" || deliverable.status === "draft_ready") {
      errorResponse(res, 409, "already_completed", "Deliverable has already completed; edit a draft-ready deliverable before executing it again");
      return;
    }
    if (deliverable.status === "failed" && !retry) {
      errorResponse(res, 409, "retry_required", "Only an explicitly failed execution may be retried with retry=true");
      return;
    }
    if (retry && deliverable.status !== "failed") {
      errorResponse(res, 409, "retry_not_allowed", "Only failed deliverables can be retried");
      return;
    }
    const previousJobId = deliverable.status === "failed" ? deliverable.job_id || undefined : undefined;
    try {
      dispatch(found.campaign, deliverable, previousJobId);
    } catch (error) {
      errorResponse(res, 422, "execution_failed", error instanceof Error ? error.message : "Unable to dispatch preview execution");
      return;
    }
    deliverable.updated_by = currentUserId(req);
    found.campaign.updated_by = currentUserId(req);
    found.campaign.updated_at = deliverable.updated_at;
    res.status(202).json({ data: deliverableOut(deliverable) });
  });

  return router;
}
