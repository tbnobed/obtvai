import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, Text, DateTime, ForeignKey, JSON, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, ARRAY, JSONB
from .database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    original_path: Mapped[str | None] = mapped_column(String, nullable=True)
    proxy_path: Mapped[str | None] = mapped_column(String, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    codec: Mapped[str | None] = mapped_column(String, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    processing_stage: Mapped[str | None] = mapped_column(String, nullable=True)
    processing_progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    scene_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speaker_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    highlight_url: Mapped[str | None] = mapped_column(String, nullable=True)
    social_scores: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    translated_languages: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    dubbed_languages: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    speaker_embeddings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    qc_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    synopsis: Mapped[str | None] = mapped_column(Text, nullable=True)
    creative: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    key_moments: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    topics: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, onupdate=datetime.utcnow)

    scenes: Mapped[list["Scene"]] = relationship("Scene", back_populates="asset", cascade="all, delete-orphan")
    transcript_segments: Mapped[list["TranscriptSegment"]] = relationship("TranscriptSegment", back_populates="asset", cascade="all, delete-orphan")
    face_clusters: Mapped[list["FaceCluster"]] = relationship("FaceCluster", back_populates="asset", cascade="all, delete-orphan")
    jobs: Mapped[list["ProcessingJob"]] = relationship("ProcessingJob", back_populates="asset", cascade="all, delete-orphan")


class Marker(Base):
    """Editor selects/rejects and timecoded notes (plus AI-suggested beats)."""
    __tablename__ = "markers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    media_id: Mapped[str] = mapped_column(String, ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False)
    time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    kind: Mapped[str] = mapped_column(String, default="marker")  # select | reject | marker
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String, default="editor")  # editor | ai
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    media_id: Mapped[str] = mapped_column(String, ForeignKey("media_assets.id"), nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(String, nullable=True)

    asset: Mapped["MediaAsset"] = relationship("MediaAsset", back_populates="scenes")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    media_id: Mapped[str] = mapped_column(String, ForeignKey("media_assets.id"), nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    speaker: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(String, nullable=True)
    translations: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    asset: Mapped["MediaAsset"] = relationship("MediaAsset", back_populates="transcript_segments")


class FaceCluster(Base):
    __tablename__ = "face_clusters"

    cluster_id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    media_id: Mapped[str] = mapped_column(String, ForeignKey("media_assets.id"), nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String, nullable=True)
    appearances: Mapped[list] = mapped_column(JSONB, default=list)
    embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    asset: Mapped["MediaAsset"] = relationship("MediaAsset", back_populates="face_clusters")


class Person(Base):
    __tablename__ = "people"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    name_source: Mapped[str | None] = mapped_column(String, nullable=True)  # auto | manual
    thumbnail_url: Mapped[str | None] = mapped_column(String, nullable=True)
    face_embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    voice_embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    speech_style: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_preset: Mapped[str | None] = mapped_column(String, nullable=True)
    voice_settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    key_topics: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, onupdate=datetime.utcnow)

    appearances: Mapped[list["PersonAppearance"]] = relationship(
        "PersonAppearance", back_populates="person", cascade="all, delete-orphan"
    )


class PersonAppearance(Base):
    __tablename__ = "person_appearances"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    person_id: Mapped[str] = mapped_column(String, ForeignKey("people.id", ondelete="CASCADE"), nullable=False)
    media_id: Mapped[str] = mapped_column(String, ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False)
    speaker_label: Mapped[str | None] = mapped_column(String, nullable=True)
    face_cluster_id: Mapped[str | None] = mapped_column(String, nullable=True)
    speaking_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    segment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_spoken_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    person: Mapped["Person"] = relationship("Person", back_populates="appearances")
    asset: Mapped["MediaAsset"] = relationship("MediaAsset")


class VoiceSample(Base):
    __tablename__ = "voice_samples"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    person_id: Mapped[str] = mapped_column(String, ForeignKey("people.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)  # segment | upload
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | ready | error
    media_id: Mapped[str | None] = mapped_column(String, ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True)
    filename: Mapped[str | None] = mapped_column(String, nullable=True)
    start_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(String, nullable=True)  # normalized wav (ready)
    raw_path: Mapped[str | None] = mapped_column(String, nullable=True)  # original upload awaiting normalization
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VoiceGeneration(Base):
    __tablename__ = "voice_generations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    person_id: Mapped[str] = mapped_column(String, ForeignKey("people.id", ondelete="CASCADE"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String, default="en")
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | running | success | error
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    preset: Mapped[str | None] = mapped_column(String, nullable=True)
    settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class GraphicsGeneration(Base):
    __tablename__ = "graphics_generations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    preset_id: Mapped[str] = mapped_column(String, nullable=False)
    preset_name: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # image | video
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frames: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | queued | running | success | error | cancelled
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    queue_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comfy_prompt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    output_path: Mapped[str | None] = mapped_column(String, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    media_id: Mapped[str | None] = mapped_column(String, ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LibraryInsight(Base):
    __tablename__ = "library_insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    headline: Mapped[str | None] = mapped_column(Text, nullable=True)
    insights: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    opportunities: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    coverage_gaps: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    media_id: Mapped[str | None] = mapped_column(String, ForeignKey("media_assets.id"), nullable=True)
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")
    progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    logs: Mapped[list] = mapped_column(JSONB, default=list)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    celery_task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    asset: Mapped["MediaAsset"] = relationship("MediaAsset", back_populates="jobs")


class RenderJob(Base):
    __tablename__ = "render_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    media_id: Mapped[str] = mapped_column(String, ForeignKey("media_assets.id"), nullable=False)
    clip_list_id: Mapped[str | None] = mapped_column(String, nullable=True)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    preset: Mapped[str] = mapped_column(String, default="original")
    burn_captions: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="pending")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    output_path: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    publish_status: Mapped[str | None] = mapped_column(String, nullable=True)
    publish_url: Mapped[str | None] = mapped_column(String, nullable=True)
    publish_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    publish_stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    asset: Mapped["MediaAsset"] = relationship("MediaAsset")


class ReelJob(Base):
    __tablename__ = "reel_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    media_id: Mapped[str | None] = mapped_column(String, nullable=True)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    preset: Mapped[str] = mapped_column(String, default="original")
    burn_captions: Mapped[bool] = mapped_column(Boolean, default=False)
    clips: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String, default="pending")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    output_path: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class StoryJob(Base):
    __tablename__ = "story_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    asset_ids: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String, default="pending")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    clip_list_id: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SearchHistory(Base):
    __tablename__ = "search_history"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    searched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    messages: Mapped[list["AIMessage"]] = relationship("AIMessage", back_populates="conversation", cascade="all, delete-orphan")


class AIMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    conversation_id: Mapped[str] = mapped_column(String, ForeignKey("ai_conversations.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversation: Mapped["AIConversation"] = relationship("AIConversation", back_populates="messages")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    script: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active", server_default="active")
    media_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, onupdate=datetime.utcnow)


class ClipList(Base):
    __tablename__ = "clip_lists"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    clips: Mapped[list["Clip"]] = relationship("Clip", back_populates="clip_list", cascade="all, delete-orphan", order_by="Clip.position")


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_uuid)
    clip_list_id: Mapped[str] = mapped_column(String, ForeignKey("clip_lists.id"), nullable=False)
    media_id: Mapped[str] = mapped_column(String, ForeignKey("media_assets.id"), nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    match_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    clip_list: Mapped["ClipList"] = relationship("ClipList", back_populates="clips")
    asset: Mapped["MediaAsset"] = relationship("MediaAsset")
