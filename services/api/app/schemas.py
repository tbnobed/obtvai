from datetime import datetime
from typing import Optional, List, Any, Literal
from pydantic import BaseModel, Field


class HealthStatus(BaseModel):
    status: str


# ── Media ─────────────────────────────────────────────────────────────────────

class MediaAssetOut(BaseModel):
    id: str
    filename: str
    original_path: Optional[str] = None
    proxy_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    codec: Optional[str] = None
    file_size_bytes: Optional[int] = None
    status: str
    processing_stage: Optional[str] = None
    processing_progress: Optional[float] = None
    scene_count: Optional[int] = None
    speaker_count: Optional[int] = None
    highlight_url: Optional[str] = None
    social_scores: Optional[List[Any]] = None
    translated_languages: Optional[List[str]] = None
    dubbed_languages: Optional[List[str]] = None
    synopsis: Optional[str] = None
    creative: Optional[Any] = None
    key_moments: Optional[List[Any]] = None
    qc_flags: Optional[dict] = None
    topics: Optional[List[str]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TranslateRequest(BaseModel):
    target_language: str


class DubRequest(BaseModel):
    target_language: str
    use_cloned_voices: bool = False


class MediaListResponse(BaseModel):
    items: List[MediaAssetOut]
    total: int


class MediaIngestInput(BaseModel):
    file_path: str
    title: Optional[str] = None


class LibraryStats(BaseModel):
    total_assets: int
    total_duration_seconds: float
    speech_indexed_seconds: float
    status_counts: dict[str, int]
    storage_bytes: int
    recent_activity: List[MediaAssetOut]


# ── Scenes / Transcript / Faces ───────────────────────────────────────────────

class SceneOut(BaseModel):
    id: str
    media_id: str
    start_time: float
    end_time: float
    thumbnail_url: Optional[str] = None
    description: Optional[str] = None
    embedding_id: Optional[str] = None

    model_config = {"from_attributes": True}


class TranscriptSegmentOut(BaseModel):
    id: str
    media_id: str
    start_time: float
    end_time: float
    text: str
    speaker: Optional[str] = None
    confidence: Optional[float] = None

    model_config = {"from_attributes": True}


class FaceAppearance(BaseModel):
    start_time: float
    end_time: float


class FaceClusterOut(BaseModel):
    cluster_id: str
    media_id: str
    label: Optional[str] = None
    thumbnail_url: Optional[str] = None
    appearances: List[FaceAppearance] = []

    model_config = {"from_attributes": True}


# ── Search ────────────────────────────────────────────────────────────────────

class SearchQuery(BaseModel):
    query: str
    media_id: Optional[str] = None
    media_ids: Optional[List[str]] = None
    search_type: str = "combined"
    limit: int = 20


class SearchResultOut(BaseModel):
    media_id: str
    filename: str
    thumbnail_url: Optional[str] = None
    start_time: float
    end_time: float
    score: float
    match_type: str
    snippet: Optional[str] = None


class SearchResponse(BaseModel):
    results: List[SearchResultOut]
    query: str
    took_ms: float


class SearchHistoryItemOut(BaseModel):
    id: str
    query: str
    result_count: int
    searched_at: datetime

    model_config = {"from_attributes": True}


class ScriptMatchRequest(BaseModel):
    script: str
    media_id: Optional[str] = None
    media_ids: Optional[List[str]] = None
    matches_per_line: int = 3


class ScriptMatchLineOut(BaseModel):
    line: str
    matches: List[SearchResultOut] = []


class ScriptMatchResponse(BaseModel):
    lines: List[ScriptMatchLineOut]
    took_ms: float


# ── Renders & publishing ──────────────────────────────────────────────────────

class RenderPresetInput(BaseModel):
    preset: str = "original"
    burn_captions: bool = False


class RenderRequestIn(BaseModel):
    media_id: str
    start_time: float
    end_time: float
    label: Optional[str] = None
    clip_list_id: Optional[str] = None
    project_id: Optional[str] = None
    preset: str = "original"
    burn_captions: bool = False


class RenderJobOut(BaseModel):
    id: str
    media_id: str
    filename: Optional[str] = None
    clip_list_id: Optional[str] = None
    project_id: Optional[str] = None
    label: Optional[str] = None
    start_time: float
    end_time: float
    preset: str
    burn_captions: bool
    unreviewed: Optional[bool] = None
    status: str
    progress: float
    output_url: Optional[str] = None
    error_message: Optional[str] = None
    publish_status: Optional[str] = None
    publish_url: Optional[str] = None
    publish_error: Optional[str] = None
    publish_stats: Optional[dict] = None
    created_at: datetime
    finished_at: Optional[datetime] = None


class PublishRequestIn(BaseModel):
    platform: str = "youtube"
    title: str
    description: Optional[str] = None
    tags: List[str] = []
    privacy: str = "unlisted"


class PublishPlatformsOut(BaseModel):
    youtube: bool


# ── Reels ─────────────────────────────────────────────────────────────────────

class ReelRequestIn(BaseModel):
    prompt: str = Field(min_length=3, max_length=500)
    media_id: Optional[str] = None
    media_ids: Optional[List[str]] = None
    project_id: Optional[str] = None
    target_duration_seconds: Optional[float] = Field(default=None, ge=30, le=14400)
    preset: Literal["original", "vertical"] = "original"
    burn_captions: bool = False
    max_clips: int = Field(default=6, ge=1, le=500)


class ReelClipOut(BaseModel):
    media_id: str
    filename: str
    start_time: float
    end_time: float
    snippet: Optional[str] = None
    thumbnail_url: Optional[str] = None


class ReelJobOut(BaseModel):
    id: str
    prompt: str
    media_id: Optional[str] = None
    project_id: Optional[str] = None
    target_duration_seconds: Optional[float] = None
    preset: str
    burn_captions: bool
    unreviewed: Optional[bool] = None
    clips: List[ReelClipOut] = []
    status: str
    progress: float
    output_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None


class SocialCutsRequestIn(BaseModel):
    platform: Optional[Literal["youtube", "instagram", "x", "facebook", "tiktok"]] = None


# ── Jobs ──────────────────────────────────────────────────────────────────────

class ProcessingJobOut(BaseModel):
    id: str
    media_id: Optional[str] = None
    filename: Optional[str] = None
    job_type: str
    status: str
    progress: Optional[float] = None
    error_message: Optional[str] = None
    logs: List[str] = []
    retry_count: int = 0
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── AI ────────────────────────────────────────────────────────────────────────

class AIQuestion(BaseModel):
    question: str
    conversation_id: Optional[str] = None
    media_id: Optional[str] = None


class AICitationOut(BaseModel):
    media_id: str
    filename: str
    start_time: float
    end_time: float
    snippet: Optional[str] = None


class AIAnswerOut(BaseModel):
    answer: str
    conversation_id: str
    citations: List[AICitationOut] = []


class ConversationOut(BaseModel):
    id: str
    title: Optional[str] = None
    created_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class AIMessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    citations: Optional[List[AICitationOut]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Clips ──────────────────────────────────────────────────────────────────────

class ClipOut(BaseModel):
    id: str
    media_id: str
    filename: Optional[str] = None
    start_time: float
    end_time: float
    label: Optional[str] = None
    notes: Optional[str] = None
    approved: bool = False
    match_reason: Optional[str] = None
    thumbnail_url: Optional[str] = None

    model_config = {"from_attributes": True}


class MarkerOut(BaseModel):
    id: str
    media_id: str
    time: float
    end_time: Optional[float] = None
    kind: str
    note: Optional[str] = None
    source: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MarkerInput(BaseModel):
    time: float
    end_time: Optional[float] = None
    kind: str = "marker"
    note: Optional[str] = None


class ClipListOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    project_id: Optional[str] = None
    locked: bool = False
    created_at: datetime
    clips: List[ClipOut] = []

    model_config = {"from_attributes": True}


class ClipInput(BaseModel):
    media_id: str
    start_time: float
    end_time: float
    label: Optional[str] = None
    notes: Optional[str] = None
    approved: bool = False
    match_reason: Optional[str] = None


class ClipListInput(BaseModel):
    name: str
    description: Optional[str] = None
    project_id: Optional[str] = None
    clips: List[ClipInput] = []


class ClipListUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    project_id: Optional[str] = None
    locked: Optional[bool] = None
    clips: Optional[List[ClipInput]] = None


class ClipExportInput(BaseModel):
    format: str


class ClipExportResult(BaseModel):
    format: str
    content: str
    filename: str


class TightenInput(BaseModel):
    silence_threshold: float = 1.25
    remove_fillers: bool = True


class TightenCut(BaseModel):
    start: float
    end: float
    reason: str  # silence | filler


class TightenResult(BaseModel):
    media_id: str
    clip_list_id: str
    kept_segments: int
    cuts: List[TightenCut] = []
    removed_seconds: float
    original_duration: float


class RoughCutInput(BaseModel):
    preset: str = "original"
    burn_captions: bool = False


class StoryRequestIn(BaseModel):
    asset_ids: List[str]
    prompt: Optional[str] = None
    project_id: Optional[str] = None


class StoryJobOut(BaseModel):
    id: str
    prompt: Optional[str] = None
    project_id: Optional[str] = None
    asset_ids: List[str] = []
    status: str
    progress: float
    title: Optional[str] = None
    narrative: Optional[str] = None
    clip_list_id: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None


# ── People ────────────────────────────────────────────────────────────────────

class PersonOut(BaseModel):
    id: str
    display_name: str
    name_source: Optional[str] = None
    thumbnail_url: Optional[str] = None
    speech_style: Optional[str] = None
    key_topics: List[str] = []
    summary: Optional[str] = None
    asset_count: int = 0
    total_speaking_seconds: float = 0
    segment_count: int = 0
    updated_at: Optional[datetime] = None
    voice_preset: Optional[str] = None
    voice_settings: Optional[dict] = None
    face_search: Optional[dict] = None


class PersonAppearanceOut(BaseModel):
    media_id: str
    filename: str
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    speaker_label: Optional[str] = None
    face_cluster_id: Optional[str] = None
    speaking_seconds: Optional[float] = None
    segment_count: Optional[int] = None
    first_spoken_at: Optional[float] = None
    merged_from: Optional[dict] = None


class PersonDetailOut(PersonOut):
    appearances: List[PersonAppearanceOut] = []


class SpeakingMomentOut(BaseModel):
    start_time: float
    end_time: float
    text: str


class OnCameraRangeOut(BaseModel):
    start_time: float
    end_time: float


class PersonAssetMomentsOut(BaseModel):
    media_id: str
    speaking: List[SpeakingMomentOut] = []
    on_camera: List[OnCameraRangeOut] = []


class AssetPersonOut(BaseModel):
    person_id: str
    display_name: str
    thumbnail_url: Optional[str] = None
    speaker_label: Optional[str] = None
    speaking_seconds: Optional[float] = None
    speaking: List[SpeakingMomentOut] = []
    on_camera: List[OnCameraRangeOut] = []


class PersonUpdateIn(BaseModel):
    display_name: str | None = None
    summary: str | None = None


class ReprofileIn(BaseModel):
    use_web: bool = False


class PersonMergeIn(BaseModel):
    source_person_id: str


class PersonSplitIn(BaseModel):
    media_id: str
    speaker_label: str | None = None
    face_cluster_id: str | None = None


class PersonUnmergeIn(BaseModel):
    merged_from_person_id: str


class VoiceSampleOut(BaseModel):
    id: str
    person_id: str
    source: str
    status: str
    media_id: Optional[str] = None
    filename: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None
    created_at: datetime


class VoiceProfileOut(BaseModel):
    person_id: str
    ready: bool
    total_sample_seconds: float
    min_sample_seconds: float
    samples: List[VoiceSampleOut] = []


class VoiceSampleFromSegmentIn(BaseModel):
    media_id: str
    start_time: float
    end_time: float


class VoiceSettingsIn(BaseModel):
    speed: Optional[float] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    repetition_penalty: Optional[float] = None


class VoiceSpeakIn(BaseModel):
    text: str
    language: str = "en"
    settings: Optional[VoiceSettingsIn] = None


class VoiceTuneIn(BaseModel):
    text: str
    language: str = "en"


class VoicePresetIn(BaseModel):
    preset: str


class VoiceGenerationOut(BaseModel):
    id: str
    person_id: str
    text: str
    language: str
    status: str
    progress: float
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None
    created_at: datetime
    preset: Optional[str] = None
    settings: Optional[dict] = None


class ResumeStalledOut(BaseModel):
    assets_resumed: int
    jobs_created: int
    assets_marked_ready: int


class ReanalyzeOut(BaseModel):
    assets_queued: int
    jobs_created: int


class PeoplePageOut(BaseModel):
    items: list["PersonOut"]
    total: int


class PersonMatchOut(BaseModel):
    person_id: str
    display_name: str
    thumbnail_url: Optional[str] = None
    asset_count: int
    similarity: float
    strong: bool


class PersonEnrollOut(BaseModel):
    person: "PersonOut"
    matches: List[PersonMatchOut] = []


class CoAppearanceNodeOut(BaseModel):
    person_id: str
    display_name: str
    thumbnail_url: Optional[str] = None
    asset_count: int


class CoAppearancePairOut(BaseModel):
    person_a_id: str
    person_b_id: str
    shared_assets: int
    together_seconds: float


class CoAppearanceGraphOut(BaseModel):
    nodes: List[CoAppearanceNodeOut] = []
    pairs: List[CoAppearancePairOut] = []


# ── Insights ──────────────────────────────────────────────────────────────────

class InsightPersonRefOut(BaseModel):
    person_id: Optional[str] = None
    display_name: str


class InsightTopicRefOut(BaseModel):
    key: str
    label: str


class InsightItemOut(BaseModel):
    title: str
    detail: str
    related_people: Optional[List[InsightPersonRefOut]] = None
    related_topics: Optional[List[InsightTopicRefOut]] = None


class StoryOpportunityOut(BaseModel):
    title: str
    rationale: str
    asset_ids: List[str]
    people: List[InsightPersonRefOut] = []
    total_duration_seconds: float


class CoverageGapOut(BaseModel):
    key: str
    label: str
    asset_count: int


class TopPersonOut(BaseModel):
    person_id: str
    display_name: str
    thumbnail_url: Optional[str] = None
    asset_count: int
    speaking_seconds: float


class TopTopicOut(BaseModel):
    key: str
    topic: str
    asset_count: int


class KeywordHeatmapRowOut(BaseModel):
    key: str
    label: str
    total: int
    counts: List[int]


class KeywordHeatmapOut(BaseModel):
    months: List[str]
    rows: List[KeywordHeatmapRowOut]


class LibraryInsightsStatsOut(BaseModel):
    total_assets: int
    total_duration_seconds: float
    speech_indexed_seconds: float
    total_people: int
    named_people_count: int
    unidentified_people_count: int
    transcribed_assets: int
    total_speaking_seconds: float


class LibraryInsightsOut(BaseModel):
    generated_at: Optional[datetime] = None
    headline: Optional[str] = None
    insights: List[InsightItemOut] = []
    opportunities: List[StoryOpportunityOut] = []
    coverage_gaps: List[CoverageGapOut] = []
    stats: LibraryInsightsStatsOut
    top_people: List[TopPersonOut] = []
    top_topics: List[TopTopicOut] = []


# ── Trends ────────────────────────────────────────────────────────────────────

class TrendHeadlineOut(BaseModel):
    title: str
    url: Optional[str] = None


class TrendMatchedTopicOut(BaseModel):
    key: str
    topic: str
    asset_count: int


class YoutubeTrendOut(BaseModel):
    rank: int
    title: str
    channel: Optional[str] = None
    url: Optional[str] = None
    views: Optional[int] = None
    matched_topics: List[TrendMatchedTopicOut] = []


class WebTrendOut(BaseModel):
    rank: int
    key: str
    topic: str
    asset_count: int
    result_count: int
    headlines: List[TrendHeadlineOut] = []


class TrendsOut(BaseModel):
    fetched_at: Optional[datetime] = None
    youtube_configured: bool
    web_configured: bool
    youtube: List[YoutubeTrendOut] = []
    web: List[WebTrendOut] = []


# ── Projects ──────────────────────────────────────────────────────────────────

class ProjectCounts(BaseModel):
    clip_lists: int = 0
    stories: int = 0
    reels: int = 0
    renders: int = 0


class ProjectOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    script: Optional[str] = None
    status: str = "active"
    media_ids: List[str] = []
    created_at: datetime
    updated_at: Optional[datetime] = None
    counts: ProjectCounts


class ProjectInput(BaseModel):
    name: str = Field(min_length=1)
    description: Optional[str] = None
    script: Optional[str] = None
    media_ids: Optional[List[str]] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    description: Optional[str] = None
    script: Optional[str] = None
    status: Optional[Literal["active", "archived"]] = None
    media_ids: Optional[List[str]] = None


class JobCleanupIn(BaseModel):
    statuses: Optional[List[str]] = None


class JobCleanupOut(BaseModel):
    deleted: int


class RetryFailedOut(BaseModel):
    retried: int


class JobStageStatsOut(BaseModel):
    job_type: str
    pending: int
    running: int
    success: int
    error: int


class JobStatsOut(BaseModel):
    assets_total: int
    assets_ready: int
    assets_processing: int
    assets_error: int
    jobs_pending: int
    jobs_running: int
    jobs_error: int
    stages: List[JobStageStatsOut]


# ── Graphics generator ────────────────────────────────────────────────────────

class GraphicsPresetOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    kind: str  # image | video
    source: str  # builtin | custom
    available: bool
    unavailable_reason: Optional[str] = None
    supports_negative: bool = False
    supports_size: bool = False
    supports_steps: bool = False
    supports_frames: bool = False
    supports_seed: bool = False
    default_width: Optional[int] = None
    default_height: Optional[int] = None
    default_steps: Optional[int] = None
    default_frames: Optional[int] = None


class GraphicsGenerateIn(BaseModel):
    preset_id: str
    prompt: str
    negative: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    steps: Optional[int] = None
    frames: Optional[int] = None
    seed: Optional[int] = None


class GraphicsGenerationOut(BaseModel):
    id: str
    kind: str
    preset_id: str
    preset_name: Optional[str] = None
    prompt: str
    negative: Optional[str] = None
    status: str
    progress: float
    queue_position: Optional[int] = None
    error_message: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    frames: Optional[int] = None
    seed: Optional[int] = None
    duration_seconds: Optional[float] = None
    output_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    media_id: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class GraphicsGenerationListOut(BaseModel):
    items: list[GraphicsGenerationOut]
    total: int


# ── Auth & users ──────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    username: str
    password: str


class SessionUserOut(BaseModel):
    id: str
    username: str
    display_name: Optional[str] = None
    role: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=72)


class UserOut(BaseModel):
    id: str
    username: str
    display_name: Optional[str] = None
    role: str
    disabled: bool
    created_at: datetime
    last_seen: Optional[datetime] = None


class UserCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-z0-9._-]+$")
    password: str = Field(min_length=8, max_length=72)
    role: Literal["admin", "user", "viewer"]
    display_name: Optional[str] = None


class UserUpdateIn(BaseModel):
    role: Optional[Literal["admin", "user", "viewer"]] = None
    display_name: Optional[str] = None
    disabled: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=72)


# ── Ratings ───────────────────────────────────────────────────────────────────

class RatingRecordOut(BaseModel):
    id: str
    provider: str
    market: Optional[str] = None
    station: str
    program_title: str
    air_date: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    rating: Optional[float] = None
    share: Optional[float] = None
    viewers: Optional[int] = None
    demo: Optional[dict] = None
    is_own: bool
    asset_id: Optional[str] = None
    asset_filename: Optional[str] = None
    import_id: Optional[str] = None


class RatingsListOut(BaseModel):
    items: List[RatingRecordOut]
    total: int


class RatingsKpisOut(BaseModel):
    record_count: int
    program_count: int
    avg_rating: Optional[float] = None
    avg_share: Optional[float] = None
    peak_viewers: Optional[int] = None


class RatingsTrendPointOut(BaseModel):
    date: str
    avg_rating: Optional[float] = None
    avg_share: Optional[float] = None
    total_viewers: Optional[int] = None


class RatingsStationShareOut(BaseModel):
    station: str
    is_own: bool
    avg_rating: Optional[float] = None
    avg_share: Optional[float] = None
    record_count: int


class RatingsTopProgramOut(BaseModel):
    program_title: str
    station: str
    airings: int
    avg_rating: Optional[float] = None
    avg_share: Optional[float] = None
    best_rating: Optional[float] = None


class RatingsOverviewOut(BaseModel):
    own_stations: List[str]
    kpis: RatingsKpisOut
    trend: List[RatingsTrendPointOut]
    station_shares: List[RatingsStationShareOut]
    top_programs: List[RatingsTopProgramOut]


class RatingsImportOut(BaseModel):
    id: str
    filename: str
    provider: str
    row_count: int
    error_count: int
    errors: Optional[List[str]] = None
    created_at: str


class RatingUpdateIn(BaseModel):
    # asset_id is tri-state: absent = no change, null = unlink, value = link.
    asset_id: Optional[str] = None
    model_config = {"extra": "forbid"}
