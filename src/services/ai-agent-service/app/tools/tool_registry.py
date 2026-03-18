"""Dynamic Tool Registry - Runtime tool discovery and management.

Provides semantic tool search and schema generation for the autonomous agent.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from app.domain.interfaces.i_embedding_provider import IEmbeddingProvider
from app.memory.conversation_memory import ConversationMemoryService
from app.tools.experience_tools import (
    CitationVerificationTool,
    FeedbackLearningTool,
    PreferenceMemoryTool,
    ReadabilityRewriterTool,
    RelatedPostsTool,
)
from app.tools.memory_search_tool import MemorySearchTool, MemoryStoreTool
from app.tools.self_eval_tool import SelfEvalTool
from app.tools.security_tools import InputGuardTool, OutputGuardTool, SecurityAuditTool

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    """Represents a tool available to the agent."""

    name: str
    description: str
    handler: Callable[..., Coroutine[Any, Any, str]]
    parameters: dict[str, Any] = field(default_factory=dict)
    examples: list[str] = field(default_factory=list)
    category: str = "general"
    requires_post_id: bool = False
    embedding: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "examples": self.examples,
            "category": self.category,
            "requires_post_id": self.requires_post_id,
        }

    def get_schema_for_llm(self) -> str:
        """Get simplified schema for Gemma3:4b."""
        params_str = ""
        if self.parameters:
            params_str = f" Input: {', '.join(self.parameters.keys())}."
        return f"- {self.name}: {self.description[:60]}{params_str}"


class DynamicToolRegistry:
    """Runtime tool discovery and management.

    Features:
    - Tool registration with metadata
    - Semantic search for relevant tools
    - Schema generation for LLM
    - Tool availability tracking
    """

    # Default tools always available
    DEFAULT_TOOLS = {
        "final_answer": Tool(
            name="final_answer",
            description="Provide the final answer when task is complete",
            handler=lambda: None,  # Special handling
            category="control",
        ),
    }

    def __init__(
        self,
        embedding_provider: IEmbeddingProvider | None = None,
    ):
        self._tools: dict[str, Tool] = dict(self.DEFAULT_TOOLS)
        self._tool_embeddings: dict[str, list[float]] = {}
        self._embedding_provider = embedding_provider
        self._categories: dict[str, set[str]] = {"control": {"final_answer"}}
        self._lock = asyncio.Lock()

    @staticmethod
    def _normalize_parameter_schema(parameters: dict[str, Any]) -> dict[str, dict[str, Any]]:
        schema: dict[str, dict[str, Any]] = {}
        for key, value in (parameters or {}).items():
            if isinstance(value, dict):
                schema[key] = dict(value)
            else:
                schema[key] = {"type": "string", "description": str(value), "required": key == "query"}
        return schema

    def _validate_arguments(
        self,
        tool_name: str,
        schema: dict[str, dict[str, Any]],
        kwargs: dict[str, Any],
        requires_post_id: bool,
    ) -> None:
        if requires_post_id and not str(kwargs.get("post_id") or "").strip():
            raise ValueError(f"Tool '{tool_name}' requires post_id")

        for key, rules in schema.items():
            required = bool(rules.get("required", key == "query"))
            value = kwargs.get(key)
            if required and (value is None or (isinstance(value, str) and not value.strip())):
                raise ValueError(f"Missing required argument: {key}")
            if value is None:
                continue
            expected_type = rules.get("type", "string")
            if expected_type == "string" and not isinstance(value, str):
                raise ValueError(f"Argument '{key}' must be a string")
            if expected_type == "string":
                max_length = int(rules.get("max_length", 4000))
                if len(value) > max_length:
                    raise ValueError(f"Argument '{key}' exceeds max_length={max_length}")

    def _enforce_policy(
        self,
        tool_name: str,
        category: str,
        kwargs: dict[str, Any],
        requires_post_id: bool,
    ) -> None:
        auth_context = kwargs.get("auth_context") or {}
        if isinstance(auth_context, dict):
            subject_type = str(
                auth_context.get("subjectType")
                or auth_context.get("subject_type")
                or "anonymous"
            ).lower()
        else:
            subject_type = str(getattr(auth_context, "subject_type", "anonymous")).lower()

        anonymous = subject_type == "anonymous"

        if category in {"memory", "personalization"} and anonymous:
            raise PermissionError(f"Tool '{tool_name}' is not allowed for anonymous sessions")
        if category in {"retrieval", "verification", "discovery"} and requires_post_id and not kwargs.get("post_id"):
            raise PermissionError(f"Tool '{tool_name}' requires a scoped post_id")

    async def _run_input_guard(self, tool_name: str, kwargs: dict[str, Any]) -> None:
        if tool_name in {"input_guard", "output_guard", "security_audit", "final_answer"}:
            return
        guard = self._tools.get("input_guard")
        query = kwargs.get("query")
        if not guard or not isinstance(query, str) or not query.strip():
            return
        guard_kwargs = dict(kwargs)
        guard_kwargs.pop("query", None)
        verdict = await guard.handler(query=query, **guard_kwargs)
        if verdict != "safe":
            raise PermissionError(verdict)

    async def _run_output_guard(self, tool_name: str, result: str, kwargs: dict[str, Any]) -> str:
        if tool_name in {"input_guard", "output_guard", "security_audit", "final_answer"}:
            return result
        guard = self._tools.get("output_guard")
        if not guard:
            return result
        guard_kwargs = dict(kwargs)
        guard_kwargs.pop("query", None)
        return await guard.handler(query=result, **guard_kwargs)

    def _wrap_handler(
        self,
        tool_name: str,
        handler: Callable[..., Coroutine[Any, Any, str]],
        parameters: dict[str, Any],
        category: str,
        requires_post_id: bool,
    ) -> Callable[..., Coroutine[Any, Any, str]]:
        schema = self._normalize_parameter_schema(parameters)

        async def _wrapped_handler(**kwargs: Any) -> str:
            self._validate_arguments(tool_name, schema, kwargs, requires_post_id)
            self._enforce_policy(tool_name, category, kwargs, requires_post_id)
            if category not in {"security", "control"}:
                await self._run_input_guard(tool_name, kwargs)
            result = await handler(**kwargs)
            result_text = result if isinstance(result, str) else str(result)
            if category not in {"security", "control"}:
                result_text = await self._run_output_guard(tool_name, result_text, kwargs)
            return result_text

        return _wrapped_handler

    async def register_tool(
        self,
        name: str,
        description: str,
        handler: Callable[..., Coroutine[Any, Any, str]],
        parameters: dict[str, Any] | None = None,
        examples: list[str] | None = None,
        category: str = "general",
        requires_post_id: bool = False,
    ) -> bool:
        """Register a new tool.

        Args:
            name: Unique tool name
            description: What the tool does
            handler: Async function to execute the tool
            parameters: Parameter definitions
            examples: Example usage strings
            category: Tool category for filtering
            requires_post_id: Whether tool needs post_id parameter

        Returns:
            True if registered successfully
        """
        if name in self._tools:
            logger.warning(f"[ToolRegistry] Tool '{name}' already registered, updating")
        normalized_parameters = parameters or {}
        wrapped_handler = self._wrap_handler(name, handler, normalized_parameters, category, requires_post_id)

        tool = Tool(
            name=name,
            description=description,
            handler=wrapped_handler,
            parameters=normalized_parameters,
            examples=examples or [],
            category=category,
            requires_post_id=requires_post_id,
        )

        # Generate embedding for semantic search (outside lock - can be slow)
        embedding: list[float] | None = None
        if self._embedding_provider:
            try:
                embedding = await self._embedding_provider.embed(
                    f"{name}: {description}"
                )
                tool.embedding = embedding
            except Exception as e:
                logger.warning(f"[ToolRegistry] Failed to embed tool '{name}': {e}")

        # Atomic write under lock
        async with self._lock:
            if embedding is not None:
                self._tool_embeddings[name] = embedding
            self._tools[name] = tool
            if category not in self._categories:
                self._categories[category] = set()
            self._categories[category].add(name)

        logger.info(f"[ToolRegistry] Registered tool '{name}' in category '{category}'")
        return True

    async def unregister_tool(self, name: str) -> bool:
        """Remove a tool from the registry."""
        async with self._lock:
            if name not in self._tools:
                return False
            tool = self._tools.pop(name)
            self._tool_embeddings.pop(name, None)
            if tool.category in self._categories:
                self._categories[tool.category].discard(name)

        logger.info(f"[ToolRegistry] Unregistered tool '{name}'")
        return True

    def get_tool(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_all_tools(self) -> list[Tool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_tools_by_category(self, category: str) -> list[Tool]:
        """Get tools in a specific category."""
        tool_names = self._categories.get(category, set())
        return [self._tools[name] for name in tool_names if name in self._tools]

    def get_tool_names(self) -> list[str]:
        """Get all tool names."""
        return list(self._tools.keys())

    async def find_relevant_tools(
        self,
        query: str,
        top_k: int = 3,
        categories: list[str] | None = None,
    ) -> list[Tool]:
        """Find tools semantically relevant to a query.

        Args:
            query: The search query
            top_k: Maximum tools to return
            categories: Optional category filter

        Returns:
            List of relevant tools, most relevant first
        """
        if not self._embedding_provider or not self._tool_embeddings:
            # Fallback to keyword matching
            return self._keyword_search(query, top_k, categories)

        try:
            # Embed the query
            query_embedding = await self._embedding_provider.embed(query)

            # Calculate similarities
            similarities: list[tuple[str, float]] = []
            for name, embedding in self._tool_embeddings.items():
                tool = self._tools.get(name)
                if not tool:
                    continue

                # Category filter
                if categories and tool.category not in categories:
                    continue

                # Cosine similarity
                similarity = self._cosine_similarity(query_embedding, embedding)
                similarities.append((name, similarity))

            # Sort by similarity
            similarities.sort(key=lambda x: x[1], reverse=True)

            # Return top-k
            relevant_tools = []
            for name, score in similarities[:top_k]:
                tool = self._tools.get(name)
                if tool:
                    relevant_tools.append(tool)

            logger.debug(
                f"[ToolRegistry] Found {len(relevant_tools)} relevant tools for query"
            )
            return relevant_tools

        except Exception as e:
            logger.warning(f"[ToolRegistry] Semantic search failed: {e}")
            return self._keyword_search(query, top_k, categories)

    def _keyword_search(
        self,
        query: str,
        top_k: int,
        categories: list[str] | None = None,
    ) -> list[Tool]:
        """Fallback keyword-based tool search."""
        query_lower = query.lower()
        scored_tools: list[tuple[Tool, int]] = []

        for tool in self._tools.values():
            # Category filter
            if categories and tool.category not in categories:
                continue

            # Simple keyword matching
            score = 0
            if tool.name in query_lower:
                score += 10
            for word in tool.description.lower().split():
                if word in query_lower:
                    score += 1

            scored_tools.append((tool, score))

        # Sort by score
        scored_tools.sort(key=lambda x: x[1], reverse=True)
        return [tool for tool, _ in scored_tools[:top_k]]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if len(a) != len(b):
            return 0.0

        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    def get_tool_schema_for_llm(self, tools: list[str] | None = None) -> str:
        """Generate simplified tool schema for Gemma3:4b.

        Args:
            tools: Specific tools to include, or all if None

        Returns:
            Formatted tool schema string
        """
        tool_list = (
            [self._tools[n] for n in tools if n in self._tools]
            if tools
            else list(self._tools.values())
        )

        lines = ["Available tools:"]
        for tool in tool_list:
            lines.append(tool.get_schema_for_llm())

        return "\n".join(lines)

    def get_tool_selection_prompt(
        self,
        task: str,
        current_step: str,
    ) -> str:
        """Generate tool selection prompt for the LLM.

        Args:
            task: The overall task
            current_step: Current step description

        Returns:
            Prompt for tool selection
        """
        tools_str = self.get_tool_schema_for_llm()

        return f"""Given task: {task}
Current step: {current_step}

{tools_str}

Which tool is best? Reply ONLY with tool name.

Tool:"""


class ToolExecutor:
    """Executes tools with error handling and timeouts."""

    def __init__(self, registry: DynamicToolRegistry):
        self._registry = registry

    async def execute(
        self,
        tool_name: str,
        **kwargs,
    ) -> tuple[str, bool]:
        """Execute a tool by name.

        Args:
            tool_name: Name of the tool to execute
            **kwargs: Arguments to pass to the tool

        Returns:
            Tuple of (result, success)
        """
        tool = self._registry.get_tool(tool_name)
        if not tool:
            return f"Tool '{tool_name}' not found", False

        if tool_name == "final_answer":
            # Special handling for final_answer
            return kwargs.get("answer", ""), True

        try:
            result = await tool.handler(**kwargs)
            return result, True
        except Exception as e:
            logger.error(f"[ToolExecutor] Tool '{tool_name}' failed: {e}")
            return f"Error: {e}", False


# Global registry instance
_global_registry: DynamicToolRegistry | None = None


def get_tool_registry() -> DynamicToolRegistry:
    """Get the global tool registry instance."""
    global _global_registry
    if _global_registry is None:
        _global_registry = DynamicToolRegistry()
    return _global_registry


async def register_default_tools(
    registry: DynamicToolRegistry,
    web_search_tool: Any = None,
    rag_tool: Any = None,
    memory_tool: Any = None,
    memory_service: ConversationMemoryService | None = None,
    embedding_provider: Any = None,
    vector_store: Any = None,
    llm_provider: Any = None,
) -> None:
    """Register the default tool set.

    Args:
        registry: The registry to register tools with
        web_search_tool: Web search tool instance
        rag_tool: RAG retrieval tool instance
        memory_tool: Memory search tool instance
        memory_service: ConversationMemoryService for preference/feedback tools
        embedding_provider: Embedding provider for semantic/citation tools
        vector_store: Vector store for citation/related-post retrieval
        llm_provider: LLM provider for readability/self-eval tools
    """
    if web_search_tool:
        await registry.register_tool(
            name="web_search",
            description="Search the web for current information and news",
            handler=web_search_tool,
            parameters={"query": "Search query string"},
            examples=["web_search for 'latest AI news'"],
            category="search",
        )

    if rag_tool:
        await registry.register_tool(
            name="rag_retrieve",
            description="Retrieve relevant sections from the article knowledge base",
            handler=rag_tool,
            parameters={"query": "Search query", "post_id": "Article ID"},
            examples=["rag_retrieve for 'main concepts'"],
            category="retrieval",
            requires_post_id=True,
        )

    if memory_tool:
        await registry.register_tool(
            name="memory_search",
            description="Search past conversations and learned information",
            handler=memory_tool,
            parameters={"query": "Search query", "session_id": "Session ID"},
            examples=["memory_search for 'previous discussions about topic'"],
            category="memory",
        )

    if memory_service and not memory_tool:
        inferred_memory_tool = MemorySearchTool(memory_service=memory_service)
        await registry.register_tool(
            name="memory_search",
            description="Search past conversations and learned information",
            handler=inferred_memory_tool,
            parameters={"query": "Search query", "session_id": "Session ID"},
            examples=["memory_search for 'previous discussions about topic'"],
            category="memory",
        )

    if memory_service:
        memory_store_tool = MemoryStoreTool(memory_service=memory_service)

        async def _memory_store_adapter(query: str, **kwargs: Any) -> str:
            return await memory_store_tool(
                content=query,
                session_id=kwargs.get("session_id", ""),
                role=kwargs.get("role", "system"),
                metadata=kwargs.get("metadata"),
            )

        await registry.register_tool(
            name="memory_store",
            description="Store important user details for future personalization",
            handler=_memory_store_adapter,
            parameters={"query": "Memory content", "session_id": "Session ID"},
            examples=["memory_store: user prefers concise Turkish answers"],
            category="memory",
        )
        await registry.register_tool(
            name="preference_memory",
            description="Store or recall user preferences for response style/topics",
            handler=PreferenceMemoryTool(memory_service=memory_service),
            parameters={"query": "Preference query", "session_id": "Session ID"},
            examples=[
                "set_pref: explain in beginner level",
                "list preference summary",
            ],
            category="personalization",
        )
        await registry.register_tool(
            name="feedback_learning",
            description="Save or summarize feedback to improve future responses",
            handler=FeedbackLearningTool(memory_service=memory_service),
            parameters={"query": "Feedback text", "session_id": "Session ID"},
            examples=["liked the concise explanation", "feedback summary"],
            category="personalization",
        )

    if embedding_provider and vector_store:
        await registry.register_tool(
            name="verify_citation",
            description="Estimate confidence and provide citation candidates from article chunks",
            handler=CitationVerificationTool(
                embedding_provider=embedding_provider,
                vector_store=vector_store,
            ),
            parameters={"query": "Claim/question", "post_id": "Article ID"},
            examples=["verify_citation for scalability claim"],
            category="verification",
            requires_post_id=True,
        )
        await registry.register_tool(
            name="related_posts",
            description="Recommend semantically related posts for better reader exploration",
            handler=RelatedPostsTool(
                embedding_provider=embedding_provider,
                vector_store=vector_store,
            ),
            parameters={"query": "Topic query", "post_id": "Current article ID"},
            examples=["related_posts for event-driven architecture"],
            category="discovery",
        )

    # â”€â”€ Security tools (always registered) â”€â”€
    await registry.register_tool(
        name="input_guard",
        description="Screen user input for jailbreak or prompt injection before LLM processing",
        handler=InputGuardTool(),
        parameters={"query": "User message to screen"},
        examples=["input_guard 'ignore all instructions'"],
        category="security",
    )
    await registry.register_tool(
        name="output_guard",
        description="Sanitize LLM output by redacting PII and blocking XSS payloads",
        handler=OutputGuardTool(),
        parameters={"query": "LLM response text to sanitize"},
        examples=["output_guard 'response containing email@example.com'"],
        category="security",
    )
    await registry.register_tool(
        name="security_audit",
        description="Record a structured audit event for notable agent operations",
        handler=SecurityAuditTool(),
        parameters={"query": "Action description"},
        examples=["security_audit 'web search performed for user query'"],
        category="security",
    )

    if llm_provider:
        self_eval_tool = SelfEvalTool(llm_provider=llm_provider)

        async def _self_eval_adapter(query: str, **kwargs: Any) -> str:
            return await self_eval_tool(
                answer=query,
                question=kwargs.get("question", ""),
                source=kwargs.get("source", ""),
            )

        await registry.register_tool(
            name="readability_rewriter",
            description="Rewrite text for beginner, concise, or advanced readability",
            handler=ReadabilityRewriterTool(llm_provider=llm_provider),
            parameters={"query": "style || text"},
            examples=["beginner || explain eventual consistency in this paragraph"],
            category="writing",
        )
        await registry.register_tool(
            name="self_eval",
            description="Evaluate answer quality and detect weak grounding",
            handler=_self_eval_adapter,
            parameters={"query": "Draft answer", "question": "Original question"},
            examples=["self_eval draft answer against question"],
            category="verification",
        )



