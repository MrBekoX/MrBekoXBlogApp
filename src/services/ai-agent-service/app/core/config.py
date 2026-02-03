"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Ollama Configuration
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API base URL"
    )
    ollama_model: str = Field(
        default="gemma3:4b",
        description="Ollama model name (gemma3:4b for 6GB VRAM, gemma3:12b for 16GB+ VRAM)"
    )
    ollama_timeout: int = Field(
        default=120,
        description="Ollama request timeout in seconds"
    )
    ollama_num_ctx: int = Field(
        default=4096,
        description="Ollama context window size (4096 for speed, 8192 for longer content)"
    )
    ollama_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="LLM temperature"
    )

    # Redis Configuration
    redis_url: str = "redis://localhost:6379/0"

    # RabbitMQ Configuration
    rabbitmq_host: str = Field(
        default="localhost",
        description="RabbitMQ host (required)"
    )
    rabbitmq_port: int = 5672
    rabbitmq_user: str = Field(
        ...,
        description="RabbitMQ username (required, cannot use default guest)"
    )
    rabbitmq_pass: str = Field(
        ...,
        min_length=8,
        description="RabbitMQ password (required, minimum 8 characters)"
    )
    rabbitmq_vhost: str = "/"
    
    @validator('rabbitmq_user')
    def validate_rabbitmq_user(cls, v):
        if v == "guest":
            raise ValueError('Default "guest" user is not allowed for security reasons')
        return v

    # NOTE: backend_api_url removed - AI Agent now uses RabbitMQ for event-driven communication
    # Results are published to "ai.analysis.completed" routing key

    # API Key for HTTP endpoint protection (optional, for future plugins)
    api_key: str = Field(
        default="",
        description="API Key for HTTP endpoint authentication (min 32 chars if set)"
    )

    # Server Settings
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Chroma (Vector Store) Configuration
    chroma_persist_dir: str = Field(
        default="./chroma_data",
        description="Directory for Chroma persistent storage"
    )

    # Ollama Embedding Model
    ollama_embedding_model: str = Field(
        default="nomic-embed-text",
        description="Ollama model for embeddings"
    )

    @property
    def rabbitmq_url(self) -> str:
        """Generate RabbitMQ connection URL."""
        return (
            f"amqp://{self.rabbitmq_user}:{self.rabbitmq_pass}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}{self.rabbitmq_vhost}"
        )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
