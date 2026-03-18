# AI Agent Service Refactoring Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace deprecated `app/agent/` folder with modern `app/agents/` and remove legacy service providers from container and dependencies.

**Architecture:** Modern agent yapısı zaten mevcut - sadece deprecated kodları kaldıracağız. `agent_use_langgraph` ayarına göre LangGraph veya legacy processor kullanılıyor. Legacy processor zaten deprecated, tamamen kaldırılabilir.

**Tech Stack:** Python, FastAPI, LangGraph, Ollama

---

## Task 1: Update messaging/processor.py

**Files:**
- Modify: `src/services/ai-agent-service/app/messaging/processor.py:1-30`
- Modify: `src/services/ai-agent-service/app/messaging/processor.py:445-470`

**Step 1: Read processor.py to understand current usage**

Run: Read lines 1-50 and 440-480 of `src/services/ai-agent-service/app/messaging/processor.py`

**Step 2: Remove legacy imports**

Find and remove:
```python
from app.agent.rag_chat_handler import ChatMessage
from app.api.dependencies import (
    get_simple_blog_agent,
    get_article_indexer,
    get_rag_chat_handler,
    get_rag_retriever,
    get_web_search_tool
)
```

**Step 3: Remove legacy agent initialization**

Find the section around line 451-465 where `self._agent`, `self._indexer`, `self._rag_chat_handler` are initialized and remove or replace with modern services.

Note: This processor is already deprecated (marked in docstring), but we need to ensure it still works or is properly removed if `agent_use_langgraph=False`.

**Step 4: Commit**

```bash
git add src/services/ai-agent-service/app/messaging/processor.py
git commit -m "refactor: remove legacy agent imports from processor.py"
```

---

## Task 2: Update container.py - Remove Legacy Providers

**Files:**
- Modify: `src/services/ai-agent-service/app/container.py:390-425`

**Step 1: Read the Legacy Compatibility section**

Run: Read lines 390-425 of `src/services/ai-agent-service/app/container.py`

**Step 2: Remove Legacy Compatibility section**

Delete the entire "Legacy compatibility" section including:
- `text_chunker`
- `legacy_embedding_service`
- `legacy_retriever`
- `article_indexer`

**Step 3: Commit**

```bash
git add src/services/ai-agent-service/app/container.py
git commit -m "refactor: remove legacy providers from container.py"
```

---

## Task 3: Update dependencies.py - Remove Legacy Getters

**Files:**
- Modify: `src/services/ai-agent-service/app/api/dependencies.py:90-130`

**Step 1: Read dependencies.py to find legacy getters**

Run: Read lines 90-140 of `src/services/ai-agent-service/app/api/dependencies.py`

**Step 2: Remove legacy getter functions**

Remove these functions:
- `get_text_chunker()` (lines ~94-96)
- `get_legacy_embedding_service()` (lines ~99-101)
- `get_legacy_retriever()` (lines ~104-106)
- `get_simple_blog_agent()` (lines ~109-114)
- `get_article_indexer()` (lines ~117-125)
- `get_rag_chat_handler()` (lines ~128-135)

**Step 3: Commit**

```bash
git add src/services/ai-agent-service/app/api/dependencies.py
git commit -m "refactor: remove legacy getters from dependencies.py"
```

---

## Task 4: Delete app/agent/ Folder

**Files:**
- Delete: `src/services/ai-agent-service/app/agent/__init__.py`
- Delete: `src/services/ai-agent-service/app/agent/simple_blog_agent.py`
- Delete: `src/services/ai-agent-service/app/agent/rag_chat_handler.py`
- Delete: `src/services/ai-agent-service/app/agent/indexer.py`

**Step 1: Verify no remaining imports**

Run:
```bash
grep -r "from app\.agent\." src/services/ai-agent-service/app/ || echo "No imports found"
```

Expected: "No imports found"

**Step 2: Delete the folder**

```bash
rm -rf src/services/ai-agent-service/app/agent/
```

**Step 3: Commit**

```bash
git add -A
git commit -m "refactor: remove deprecated app/agent/ folder"
```

---

## Task 5: Verify Build and Test

**Step 1: Check for syntax errors**

Run:
```bash
cd src/services/ai-agent-service && python -m py_compile app/container.py app/api/dependencies.py app/messaging/processor.py
```

Expected: No output (success)

**Step 2: Check imports work**

Run:
```bash
cd src/services/ai-agent-service && python -c "from app.container import container; print('Container OK')"
```

Expected: "Container OK"

**Step 3: Verify FastAPI app can be created**

Run:
```bash
cd src/services/ai-agent-service && python -c "from app.api.routes import create_app; app = create_app(); print('App OK')"
```

Expected: "App OK"

---

## Execution Options

**Plan complete and saved to `docs/plans/2026-03-11-ai-agent-refactor.md`. Two execution options:**

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**
