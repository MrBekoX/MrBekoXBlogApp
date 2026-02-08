# AI Agent Service Guidelines

## Security
- Debug mode (`settings.debug`) MUST NOT bypass authentication or grant elevated scopes
- All API endpoints MUST require authentication — use `Depends(require_scope(...))` on every route
- Exception messages MUST NOT be sent to clients — use generic `detail="Internal server error"` in HTTPException
- `core/auth.py` and `core/security.py` MUST contain actual implementations, not empty placeholder files
- Kill switch `EMERGENCY_SHUTDOWN` state MUST NOT auto-expire — remove TTL (`ex=3600`) for emergency states

## ChromaDB / Vector Store
- `allow_reset=True` MUST be removed in production ChromaDB settings
- ChromaDB calls are synchronous and block the event loop — wrap in `asyncio.to_thread()` or use async alternatives
- Consolidate duplicate VectorStore implementations (`rag/vector_store.py` and `infrastructure/vector_store/chroma_adapter.py`) into a single source

## Configuration
- `rabbitmq_url` property MUST NOT embed plaintext passwords in connection strings — use URL-safe encoding or separate connection parameters
- Default `guest:guest` credentials MUST be rejected (already done via validator, maintain this)

## Code Quality
- All `except` blocks MUST specify the exception type — no bare `except:` clauses
- Module-level singletons (`anomaly_detector`, `data_classifier`, `vector_store`) SHOULD be replaced with proper DI via FastAPI's dependency injection
- `AnomalyDetector.user_requests` dictionary grows unbounded — implement TTL-based cleanup or max user limit
- TCKN regex `r"\b[1-9]\d{10}\b"` has high false-positive rate — implement TCKN checksum validation (Luhn-like algorithm)

## Rate Limiting
- Consolidate the 3 separate rate limiting systems (config-based, slowapi, anomaly detector) into a unified approach
- Rate limits MUST be applied consistently across all endpoint versions

## RAG Data Integrity
- Implement hash-based integrity checks for stored vector chunks
- Validate chunk content before serving to LLM to prevent data poisoning
