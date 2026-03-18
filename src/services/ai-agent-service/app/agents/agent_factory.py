"""Agent Factory - Factory functions for creating configured agents.

Provides easy setup for the autonomous agent system with all dependencies.
"""

import logging
from typing import Any

from app.agents.autonomous_agent import AutonomousAgent, ExecutionMode
from app.agents.planner_agent import PlannerAgent
from app.agents.plan_validator import PlanValidator
from app.agents.react_chat_agent import ReActChatAgent
from app.agents.chat_agent import ChatAgent
from app.agents.supervisor import SupervisorAgent
from app.core.config import settings
from app.core.autonomy_guardrails import AutonomyGuardrails
from app.tools.tool_registry import DynamicToolRegistry, register_default_tools
from app.memory.episodic_memory import EpisodicMemory
from app.memory.conversation_memory import ConversationMemoryService
from app.services.chat_service import ChatService
from app.services.analysis_service import AnalysisService

logger = logging.getLogger(__name__)


async def create_autonomous_agent(
    llm_provider: Any,
    vector_store: Any | None = None,
    embedding_provider: Any | None = None,
    memory_service: ConversationMemoryService | None = None,
    web_search_tool: Any | None = None,
    rag_tool: Any | None = None,
    mode: ExecutionMode = ExecutionMode.HYBRID,
    episodic_memory: EpisodicMemory | None = None,
) -> AutonomousAgent:
    """Create a fully configured AutonomousAgent.

    Args:
        llm_provider: LLM provider instance
        vector_store: Vector store for episodic memory
        embedding_provider: Embedding provider for semantic search
        memory_service: Conversation memory service
        web_search_tool: Web search tool instance
        rag_tool: RAG retrieval tool instance
        mode: Execution mode (HYBRID, AUTONOMOUS, REACTIVE)
        episodic_memory: Optional pre-configured episodic memory

    Returns:
        Configured AutonomousAgent instance
    """
    # Create tool registry
    registry = DynamicToolRegistry(embedding_provider=embedding_provider)
    await register_default_tools(
        registry=registry,
        web_search_tool=web_search_tool,
        rag_tool=rag_tool,
        memory_service=memory_service,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        llm_provider=llm_provider,
    )

    # Build tool dict for agent
    tools = {name: tool.handler for name, tool in registry._tools.items() if tool.handler}

    # Create episodic memory if not provided
    if not episodic_memory and vector_store and embedding_provider:
        episodic_memory = EpisodicMemory(
            vector_store=vector_store,
            embedding_provider=embedding_provider,
        )

    # Create planner with episodic memory for learning from past plans
    planner = PlannerAgent(
        llm_provider=llm_provider,
        available_tools=list(tools.keys()),
        max_plan_steps=settings.agent_max_plan_steps,
        episodic_memory=episodic_memory,
    )

    # Create validator
    validator = PlanValidator(
        available_tools=list(tools.keys()),
        max_iterations=settings.agent_max_total_iterations,
    )

    # Create guardrails
    guardrails = AutonomyGuardrails(
        max_iterations=settings.agent_max_total_iterations,
        max_time_seconds=settings.agent_max_time_seconds,
        max_llm_calls=settings.agent_max_llm_calls,
        confidence_threshold=settings.agent_confidence_threshold,
    )

    # Create autonomous agent
    agent = AutonomousAgent(
        llm_provider=llm_provider,
        tools=tools,
        mode=mode,
        planner=planner,
        validator=validator,
        guardrails=guardrails,
        episodic_memory=episodic_memory,
    )

    logger.info(f"[AgentFactory] Created AutonomousAgent with mode={mode.value}")
    return agent


async def create_chat_agent(
    llm_provider: Any,
    chat_service: ChatService,
    analysis_service: AnalysisService,
    memory_service: ConversationMemoryService | None = None,
    web_search_tool: Any | None = None,
    rag_tool: Any | None = None,
    vector_store: Any | None = None,
    embedding_provider: Any | None = None,
    enable_autonomous: bool = True,
) -> ChatAgent:
    """Create a fully configured ChatAgent with optional autonomous capabilities.

    Args:
        llm_provider: LLM provider instance
        chat_service: Chat service for basic responses
        analysis_service: Analysis service for summaries
        memory_service: Conversation memory service
        web_search_tool: Web search tool instance
        rag_tool: RAG retrieval tool instance
        vector_store: Vector store for episodic memory
        embedding_provider: Embedding provider
        enable_autonomous: Whether to enable autonomous agent for complex queries

    Returns:
        Configured ChatAgent instance
    """
    # Create ReAct agent for medium complexity
    react_agent = None
    if web_search_tool or rag_tool:
        react_agent = ReActChatAgent(
            llm_provider=llm_provider,
            web_search_tool=web_search_tool,
            rag_tool=rag_tool,
        )

    # Create autonomous agent for high complexity
    autonomous_agent = None
    if enable_autonomous and settings.agent_autonomous_enabled:
        autonomous_agent = await create_autonomous_agent(
            llm_provider=llm_provider,
            vector_store=vector_store,
            embedding_provider=embedding_provider,
            memory_service=memory_service,
            web_search_tool=web_search_tool,
            rag_tool=rag_tool,
            mode=ExecutionMode.HYBRID if settings.agent_hybrid_mode else ExecutionMode.AUTONOMOUS,
        )

    chat_agent = ChatAgent(
        chat_service=chat_service,
        analysis_service=analysis_service,
        memory_service=memory_service,
        react_agent=react_agent,
        autonomous_agent=autonomous_agent,
    )

    logger.info(
        f"[AgentFactory] Created ChatAgent with "
        f"react={react_agent is not None}, autonomous={autonomous_agent is not None}"
    )
    return chat_agent


async def create_supervisor(
    agents: dict[str, Any],
    llm_provider: Any | None = None,
    verification_agent: Any | None = None,
) -> SupervisorAgent:
    """Create a SupervisorAgent with optional dynamic routing.

    Args:
        agents: Dict of agent name to agent instance
        llm_provider: LLM provider for dynamic routing
        verification_agent: Optional verification agent

    Returns:
        Configured SupervisorAgent instance
    """
    supervisor = SupervisorAgent(
        agents=agents,
        verification_agent=verification_agent,
        llm_provider=llm_provider if settings.agent_dynamic_routing else None,
    )

    logger.info(
        f"[AgentFactory] Created Supervisor with "
        f"dynamic_routing={settings.agent_dynamic_routing}, "
        f"agents={list(agents.keys())}"
    )
    return supervisor


def create_episodic_memory(
    vector_store: Any | None = None,
    embedding_provider: Any | None = None,
) -> EpisodicMemory:
    """Create an EpisodicMemory instance.

    Args:
        vector_store: Vector store for persistence
        embedding_provider: Embedding provider for semantic search

    Returns:
        Configured EpisodicMemory instance
    """
    memory = EpisodicMemory(
        vector_store=vector_store,
        embedding_provider=embedding_provider,
    )

    logger.info(
        f"[AgentFactory] Created EpisodicMemory with "
        f"vector_store={vector_store is not None}"
    )
    return memory
