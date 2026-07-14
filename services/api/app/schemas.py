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
    topics: Optional[List[str]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TranslateRequest(BaseModel):
    target_language: str


class DubRequest(BaseModel):
    target_language: str


class MediaListResponse(BaseModel):
    items: List[MediaAssetOut]
    total: int


class MediaIngestInput(BaseModel):
    file_path: str
    title: Optional[str] = None


class LibraryStats(BaseModel):
    total_assets: int
    total_duration_seconds: float
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
    status: str
    progress: float
    output_url: Optional[str] = None
    error_message: Optional[str] = None
    publish_status: Optional[str] = None
    publish_url: Optional[str] = None
    publish_error: Optional[str] = None
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
    project_id: Optional[str] = None
    preset: Literal["original", "vertical"] = "original"
    burn_captions: bool = False
    max_clips: int = Field(default=6, ge=1, le=12)


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
    preset: str
    burn_captions: bool
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

    model_config = {"from_attributes": True}


class ClipListOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    project_id: Optional[str] = None
    created_at: datetime
    clips: List[ClipOut] = []

    model_config = {"from_attributes": True}


class ClipInput(BaseModel):
    media_id: str
    start_time: float
    end_time: float
    label: Optional[str] = None


class ClipListInput(BaseModel):
    name: str
    description: Optional[str] = None
    project_id: Optional[str] = None
    clips: List[ClipInput] = []


class ClipListUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    project_id: Optional[str] = None
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


class PersonDetailOut(PersonOut):
    appearances: List[PersonAppearanceOut] = []


class PersonUpdateIn(BaseModel):
    display_name: str


class PersonMergeIn(BaseModel):
    source_person_id: str


class PersonSplitIn(BaseModel):
    media_id: str
    speaker_label: str | None = None
    face_cluster_id: str | None = None


class ReanalyzeOut(BaseModel):
    assets_queued: int
    jobs_created: int


class PeoplePageOut(BaseModel):
    items: list["PersonOut"]
    total: int


# ── Insights ──────────────────────────────────────────────────────────────────

class InsightItemOut(BaseModel):
    title: str
    detail: str


class TopPersonOut(BaseModel):
    person_id: str
    display_name: str
    thumbnail_url: Optional[str] = None
    asset_count: int
    speaking_seconds: float


class TopTopicOut(BaseModel):
    topic: str
    asset_count: int


class LibraryInsightsStatsOut(BaseModel):
    total_assets: int
    total_duration_seconds: float
    total_people: int
    transcribed_assets: int
    total_speaking_seconds: float


class LibraryInsightsOut(BaseModel):
    generated_at: Optional[datetime] = None
    headline: Optional[str] = None
    insights: List[InsightItemOut] = []
    stats: LibraryInsightsStatsOut
    top_people: List[TopPersonOut] = []
    top_topics: List[TopTopicOut] = []


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
