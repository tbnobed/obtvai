import os


DATABASE_URL = os.getenv("DATABASE_URL_SYNC", "postgresql://obtv:obtv@postgres:5432/obtv")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/media")
ARTIFACTS_ROOT = os.getenv("ARTIFACTS_ROOT", "/artifacts")
PROXIES_DIR = os.getenv("PROXIES_DIR", "/artifacts/proxies")
THUMBNAILS_DIR = os.getenv("THUMBNAILS_DIR", "/artifacts/thumbnails")
AUDIO_DIR = os.getenv("AUDIO_DIR", "/artifacts/audio")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
VISION_MODEL = os.getenv("VISION_MODEL", "openai/clip-vit-large-patch14")
