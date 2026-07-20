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
    graphics_dir: str = "/artifacts/graphics"
    comfyui_url: str = "http://host.docker.internal:8188"
    # Separate instances per output kind; empty = fall back to comfyui_url.
    comfyui_url_image: str = ""
    comfyui_url_video: str = ""
    comfy_workflows_dir: str = "/workflows"
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    embeddings_model: str = "BAAI/bge-m3"
    # Must match the worker's VISION_MODEL default — text queries and scene
    # images have to be embedded by the SAME vision model or scores are noise.
    vision_model: str = "google/siglip2-so400m-patch14-384"
    whisper_model: str = "medium"
    cors_origins: list[str] = ["*"]
    # First-run admin bootstrap (used only when the users table is empty).
    admin_username: str = "admin"
    admin_password: str = ""  # empty = random password printed once to the API log
    # Shared secret for internal services (watcher) calling the API.
    internal_api_token: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
