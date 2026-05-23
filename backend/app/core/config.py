"""
Application configuration using Pydantic Settings.

All values are read from environment variables (.env file).
Follows 12-Factor App methodology: config from environment, never hardcoded.
"""

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Application ---
    app_name: str = "Nexus AI"
    app_env: str = "development"
    app_version: str = "1.0.0"
    debug: bool = True
    secret_key: str = Field(..., min_length=32)

    # --- API Keys ---
    # Groq is FREE and fast — get key at console.groq.com
    groq_api_key: str = ""
    # OpenAI optional — add later when you have a key
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # --- Database ---
    database_url: str

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # --- Vector Database ---
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection_name: str = "nexus_documents"
    pinecone_api_key: str = ""
    pinecone_environment: str = ""
    pinecone_index_name: str = "nexus-production"

    # --- Authentication ---
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # --- Embedding ---
    # LOCAL (free, no API key): sentence-transformers model runs on your machine
    # CLOUD (paid): switch to "text-embedding-3-small" with OpenAI key
    embedding_model: str = "all-MiniLM-L6-v2"   # HuggingFace local model
    embedding_dimension: int = 384               # MiniLM output size (OpenAI = 1536)
    embedding_provider: str = "huggingface"      # "huggingface" | "openai"

    # --- LLM ---
    # Groq is FREE and 250 tokens/sec — same OpenAI-compatible interface
    llm_provider: str = "groq"                   # "groq" | "openai" | "anthropic"
    llm_model: str = "llama-3.3-70b-versatile"  # Groq's best free model
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2000

    # --- RAG ---
    chunk_size: int = 1000
    chunk_overlap: int = 200
    retrieval_top_k: int = 5
    reranking_enabled: bool = True

    # --- Monitoring ---
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # --- CORS ---
    allowed_origins: List[str] = ["http://localhost:3000"]

    # --- File Upload ---
    max_file_size_mb: int = 50
    allowed_file_types: List[str] = ["pdf", "docx", "txt", "md", "csv"]
    upload_dir: str = "./uploads"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# lru_cache ensures Settings is only instantiated ONCE
# (expensive: reads files, validates all fields)
@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
