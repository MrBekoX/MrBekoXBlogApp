"""Application configuration using Pydantic Settings."""

from functools import lru_cache

from pydantic import Field, validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
        default="phi4-mini",
        description="Ollama model name (phi4-mini, qwen3.5:2b for 4GB VRAM, qwen3.5:4b for 6GB VRAM, qwen3.5:7b for 10GB+ VRAM)"
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

    # Worker Resilience Configuration
    worker_operation_timeout_seconds: int = Field(
        default=300,
        ge=1,
        description="Timeout for async worker operations (analysis/chat/indexing)"
    )
    broker_publish_timeout_seconds: int = Field(
        default=10,
        ge=1,
        description="Timeout for publishing completion events to broker"
    )
    worker_operation_retention_seconds: int = Field(
        default=604800,
        ge=3600,
        le=2592000,
        description="Retention window for operation idempotency state and processed markers"
    )
    worker_stage_cache_ttl_seconds: int = Field(
        default=86400,
        ge=300,
        le=604800,
        description="TTL for stage-level cache entries used to skip repeated expensive work"
    )
    worker_retry_attempts: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Maximum retry attempts for transient worker failures (reduced from 3 to prevent chain retries)"
    )
    worker_retry_base_delay_seconds: float = Field(
        default=0.25,
        ge=0.01,
        le=30,
        description="Base delay for exponential backoff retry"
    )
    worker_retry_max_backoff_seconds: float = Field(
        default=2.0,
        ge=0.05,
        le=120,
        description="Max backoff delay for worker retries"
    )
    broker_message_max_retries: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Max broker redelivery attempts before quarantine/DLQ"
    )
    broker_lock_retry_delay_seconds: float = Field(
        default=2.0,
        ge=0.1,
        le=30.0,
        description="Delay before requeue when entity lock contention occurs"
    )
    broker_quarantine_preview_bytes: int = Field(
        default=4096,
        ge=256,
        le=65536,
        description="Max message body bytes stored in quarantine payload preview"
    )
    broker_quarantine_store_body_max_bytes: int = Field(
        default=262144,
        ge=1024,
        le=4194304,
        description="Max original message body bytes persisted in quarantine envelope for replay"
    )
    enable_poison_runbook_hook: bool = Field(
        default=True,
        description="Enable incident runbook hook when poison message is quarantined"
    )
    broker_consumer_prefetch_count: int = Field(
        default=4,
        ge=1,
        le=2048,
        description="RabbitMQ consumer prefetch count for broker backpressure tuning"
    )
    broker_consumer_concurrency: int = Field(
        default=2,
        ge=1,
        le=512,
        description="Max in-flight messages processed concurrently by the consumer loop"
    )
    broker_backlog_warn_threshold: int = Field(
        default=5000,
        ge=0,
        le=5000000,
        description="Backlog threshold for readiness degradation and alerts"
    )

    # Priority Queue Configuration
    queue_chat_name: str = Field(
        default="q.chat.requests",
        description="High-priority chat queue name"
    )
    queue_authoring_name: str = Field(
        default="q.ai.authoring",
        description="Medium-priority authoring queue name"
    )
    queue_background_name: str = Field(
        default="q.ai.background",
        description="Low-priority background queue name"
    )
    queue_chat_ttl_ms: int = Field(
        default=60000,
        ge=10000,
        le=300000,
        description="Chat queue message TTL in milliseconds"
    )
    queue_authoring_ttl_ms: int = Field(
        default=300000,
        ge=30000,
        le=600000,
        description="Authoring queue message TTL in milliseconds"
    )
    queue_background_ttl_ms: int = Field(
        default=1800000,
        ge=60000,
        le=3600000,
        description="Background queue message TTL in milliseconds"
    )
    queue_chat_prefetch: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Chat queue prefetch count"
    )
    queue_authoring_prefetch: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Authoring queue prefetch count"
    )
    queue_background_prefetch: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Background queue prefetch count"
    )
    scheduler_total_slots: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Total concurrent processing slots"
    )
    scheduler_chat_slots: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Dedicated chat processing slots"
    )
    scheduler_low_priority_slots: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Shared slot for authoring + background"
    )
    chat_max_retries: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Max retry attempts for chat messages"
    )
    authoring_max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Max retry attempts for authoring messages"
    )
    background_max_retries: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Max retry attempts for background messages"
    )
    retry_budget_max_inflight: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Max concurrent retry messages across all queues"
    )
    retry_backoff_base_seconds: float = Field(
        default=2.0,
        ge=0.5,
        le=10.0,
        description="Base delay for retry exponential backoff"
    )
    retry_backoff_max_seconds: float = Field(
        default=30.0,
        ge=5.0,
        le=120.0,
        description="Max delay cap for retry backoff"
    )
    queue_stats_redis_ttl_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="TTL for queue stats published to Redis"
    )
    circuit_breaker_failure_threshold: int = Field(
        default=3,
        ge=2,
        le=10,
        description="Failures before circuit opens (out of last 5 requests)"
    )
    circuit_breaker_recovery_timeout: int = Field(
        default=30,
        ge=10,
        le=120,
        description="Seconds before circuit transitions to half-open"
    )
    chat_fallback_message: str = Field(
        default="AI asistanı şu an yoğun, lütfen biraz sonra tekrar deneyin.",
        description="Fallback message when circuit is open for chat"
    )

    # Tool Orchestration Budgets (Chat/RAG Pipeline)
    tool_default_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Default timeout budget for tool invocations"
    )
    tool_rag_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Timeout budget for RAG retrieval tool calls"
    )
    tool_web_search_timeout_seconds: int = Field(
        default=20,
        ge=1,
        le=300,
        description="Timeout budget for web-search tool calls"
    )
    tool_llm_timeout_seconds: int = Field(
        default=90,
        ge=1,
        le=600,
        description="Timeout budget for LLM inference tool calls"
    )
    tool_retry_attempts: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Retry attempts for retryable tool failures (reduced from 2 to prevent chain retries)"
    )
    rag_expand_timeout_seconds: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Timeout for query expansion in RAG pipeline"
    )
    tool_retry_base_delay_seconds: float = Field(
        default=0.2,
        ge=0.01,
        le=30,
        description="Base delay for tool retry exponential backoff"
    )
    tool_retry_max_backoff_seconds: float = Field(
        default=2.0,
        ge=0.05,
        le=120,
        description="Maximum backoff delay for tool retries"
    )

    # Reasoning / Planning Policy
    reasoning_critique_enabled: bool = Field(
        default=True,
        description="Enable explicit critique/groundedness verification loop"
    )
    reasoning_critique_max_repairs: int = Field(
        default=1,
        ge=0,
        le=5,
        description="Maximum repair attempts after critique failure"
    )
    reasoning_code_request_min_overlap: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description="Minimum query/context term overlap ratio for source-bound code requests"
    )

    # Backend integration for internal authorization decisions
    backend_api_url: str = Field(
        default="http://localhost:8080/api/v1",
        description="Backend API base URL used to derive internal authorization endpoint"
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
    chroma_force_reset: bool = Field(
        default=False,
        description="Force reset all ChromaDB collections on startup (nuclear option for dimension mismatch)"
    )

    # Ollama Embedding Model
    ollama_embedding_model: str = Field(
        default="nomic-embed-text",
        description="Ollama model for embeddings (nomic-embed-text: 768 boyut)"
    )

    # Hugging Face Settings
    hf_token: str | None = Field(
        default=None,
        description="Hugging Face API token to avoid rate limits during model downloads"
    )

    # OAuth 2.0 Configuration for M2M Auth
    oauth_introspection_url: str | None = Field(
        default=None,
        description="OAuth 2.0 Token Introspection URL (optional)"
    )
    oauth_client_id: str | None = Field(
        default=None,
        description="OAuth 2.0 Client ID"
    )
    oauth_client_secret: str | None = Field(
        default=None,
        description="OAuth 2.0 Client Secret"
    )

    internal_service_auth_header_name: str = Field(
        default="X-Service-Key",
        description="Header name used for backend internal service authentication"
    )
    internal_service_auth_key: str | None = Field(
        default=None,
        description="Shared internal service key used for backend authorization decisions"
    )

    # LangGraph Multi-Agent Configuration
    agent_use_langgraph: bool = Field(
        default=True,
        description="Enable LangGraph-based message processing with Supervisor and Autonomous agents"
    )
    agent_checkpoint_ttl: int = Field(
        default=86400,
        ge=300,
        le=604800,
        description="LangGraph checkpoint TTL in seconds (default 24h)"
    )
    agent_max_react_steps: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum ReAct reasoning iterations"
    )

    # Autonomous Agent Configuration
    agent_autonomous_enabled: bool = Field(
        default=True,
        description="Enable autonomous agent with planning capabilities"
    )
    agent_hybrid_mode: bool = Field(
        default=True,
        description="Use hybrid mode: ReAct for simple, Autonomous for complex queries"
    )
    agent_max_plan_steps: int = Field(
        default=4,
        ge=2,
        le=6,
        description="Maximum steps in an execution plan (optimized for Gemma3:4b)"
    )
    agent_max_total_iterations: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Maximum total iterations for autonomous execution"
    )
    agent_max_time_seconds: int = Field(
        default=120,
        ge=10,
        le=300,
        description="Maximum time for autonomous execution in seconds"
    )
    agent_max_llm_calls: int = Field(
        default=15,
        ge=1,
        le=30,
        description="Maximum LLM calls per autonomous execution"
    )
    agent_verification_timeout_seconds: int = Field(
        default=20,
        ge=5,
        le=120,
        description="Hard timeout for VerificationAgent LLM call; on timeout the original response is returned unmodified"
    )
    agent_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for early termination"
    )
    agent_episodic_memory_enabled: bool = Field(
        default=True,
        description="Enable episodic memory for learning from past executions"
    )
    
    # Memory Configuration
    memory_stm_max_messages: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Maximum messages in short-term memory (Redis)"
    )
    memory_stm_ttl_seconds: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Short-term memory TTL in seconds (default 24h)"
    )
    memory_ltm_max_episodes: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Maximum episodes in long-term memory"
    )
    memory_checkpoint_enabled: bool = Field(
        default=True,
        description="Enable LangGraph checkpoint persistence"
    )
    memory_checkpoint_ttl_seconds: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="Checkpoint TTL in seconds (default 24h)"
    )
    agent_dynamic_routing: bool = Field(
        default=False,
        description="Enable LLM-based dynamic routing instead of hardcoded mapping"
    )

    # Jailbreak / Security Configuration
    enable_semantic_detection: bool = True
    jailbreak_confidence_threshold: float = 0.50
    jailbreak_log_only: bool = False
    enable_red_team_mode: bool = False

        # Idle standby configuration (cost optimization without container control-plane access)
    idle_shutdown_enabled: bool = Field(
        default=True,
        description="Enable automatic shutdown after idle timeout (cost optimization)"
    )
    idle_timeout_seconds: int = Field(
        default=1800,  # 30 minutes
        ge=60,
        le=86400,  # Max 24 hours
        description="Seconds of inactivity before container shutdown"
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





