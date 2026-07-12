from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel


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
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


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


# ── Jobs ──────────────────────────────────────────────────────────────────────

class ProcessingJobOut(BaseModel):
    id: str
    media_id: str
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
    clips: List[ClipInput] = []


class ClipListUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    clips: Optional[List[ClipInput]] = None


class ClipExportInput(BaseModel):
    format: str


class ClipExportResult(BaseModel):
    format: str
    content: str
    filename: str
