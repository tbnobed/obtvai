from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://obtv:obtv@postgres:5432/obtv"
    database_url_sync: str = "postgresql://obtv:obtv@postgres:5432/obtv"
    redis_url: str = "redis://redis:6379/0"
    qdrant_url: str = "http://qdrant:6333"
    media_root: str = "/media"
    upload_dir: str = "/uploads"
    max_upload_bytes: int = 10 * 1024 * 1024 * 1024  # keep aligned with nginx client_max_body_size
    artifacts_root: str = "/artifacts"
    proxies_dir: str = "/artifacts/proxies"
    thumbnails_dir: str = "/artifacts/thumbnails"
    audio_dir: str = "/artifacts/audio"
    renders_dir: str = "/artifacts/renders"
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    embeddings_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    vision_model: str = "openai/clip-vit-base-patch32"
    whisper_model: str = "medium"
    cors_origins: list[str] = ["*"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
