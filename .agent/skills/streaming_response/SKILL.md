---
name: Streaming Response Support
description: Enable streaming responses for Chat API.
---

# Streaming Response Support

This skill enables Server-Sent Events (SSE) or chunked transfer for Chat responses to improve User Experience (UX).

## Implementation Guide

1.  **Update `ChatService`**: Add `chat_stream` generator method.
2.  **Update `ILLMProvider`**: Ensure LLM supports streaming (yield chunks).
3.  **Update API Endpoint**: Use `StreamingResponse`.

### Service Layer

```python
# app/services/chat_service.py

async def chat_stream(self, post_id: str, user_message: str, ...) -> AsyncGenerator[str, None]:
    # ... Validation logic ...
    
    # RAG Retrieval
    result = await self._rag.retrieve_with_context(...)
    
    prompt = self._build_prompt(user_message, result.context)
    
    # Stream from LLM
    async for chunk in self._llm.generate_stream(prompt):
        yield chunk
```

### API Layer

```python
# app/api/endpoints.py
from fastapi.responses import StreamingResponse

@router.post("/api/chat/stream")
async def chat_stream_endpoint(request: ChatRequest):
    return StreamingResponse(
        chat_service.chat_stream(
            post_id=request.post_id,
            user_message=request.message,
            ...
        ),
        media_type="text/event-stream"
    )
```
