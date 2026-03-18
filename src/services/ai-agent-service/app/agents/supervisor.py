"""Supervisor agent — routes messages to specialized agents via LangGraph.



Supports both:

- Static routing via ROUTING_MAP (default, backward compatible)

- Dynamic LLM-based routing (enabled via config.agent_dynamic_routing)

"""



import asyncio
import logging

from typing import Any, TypedDict



from langgraph.graph import StateGraph, END



from app.agents.base_agent import BaseSpecializedAgent

from app.core.config import settings



logger = logging.getLogger(__name__)



# Optional — wired in Phase 4

_VerificationAgentType = None

try:

    from app.agents.verification_agent import VerificationAgent as _VerificationAgentType  # type: ignore[assignment]

except ImportError:

    pass



# Event type → agent name routing (static fallback)

ROUTING_MAP: dict[str, str] = {

    "chat": "chat",

    "article": "analyzer",

    "article_published": "analyzer",

    "title": "content",

    "excerpt": "content",

    "tags": "content",

    "seo": "seo",

    "content": "content",

}



# Dynamic routing prompt for Gemma3:4b

ROUTING_PROMPT = """You are a routing assistant. Choose the best agent for this task.



Agents:

- chat: For Q&A, conversations about articles

- analyzer: For article analysis, summaries, keywords

- content: For generating titles, excerpts, tags

- seo: For SEO optimization

- autonomous: For complex multi-step tasks requiring planning



Event type: {event_type}

Task preview: {task_preview}



Reply ONLY with agent name (one word).



Agent:"""





class SupervisorState(TypedDict, total=False):

    """Supervisor graph state."""



    event_type: str

    payload: dict[str, Any]

    language: str

    assigned_agent: str

    agent_result: dict[str, Any] | None

    final_response: dict[str, Any] | None

    error: str | None

    # Phase 4: verification
    verification_passed: bool | None

    verification_result: dict[str, Any] | None

    # Retrieved chunks for citation verification
    retrieved_chunks: list[dict[str, Any]] | None

    # Dynamic routing

    routing_method: str  # "static" or "dynamic"

    complexity: str  # "simple" or "complex"





class SupervisorAgent:

    """Orchestrates specialized agents using a LangGraph workflow.



    Workflow: START → supervisor_route → agent_execute → (verify →) END



    The supervisor selects the appropriate agent based on ``event_type``,

    delegates execution, optionally runs verification (Phase 4), and returns

    the final result.



    Features:

    - Static routing via ROUTING_MAP (backward compatible)

    - Dynamic LLM-based routing (when enabled)

    - Hybrid mode: ReAct for simple, Autonomous for complex queries

    """



    def __init__(

        self,

        agents: dict[str, BaseSpecializedAgent],

        verification_agent: Any | None = None,

        llm_provider: Any | None = None,

    ):

        """

        Args:

            agents: Map of agent name → agent instance.

            verification_agent: Optional VerificationAgent for post-execution checks.

            llm_provider: Optional LLM provider for dynamic routing.

        """

        self._agents = agents

        self._verifier = verification_agent

        self._llm = llm_provider

        self._graph = self._build_graph()



    def _build_graph(self) -> Any:

        builder = StateGraph(SupervisorState)



        builder.add_node("route", self._route_node)

        builder.add_node("execute", self._execute_node)

        builder.add_node("finalize", self._finalize_node)



        builder.set_entry_point("route")

        builder.add_edge("route", "execute")

        builder.add_edge("execute", "finalize")

        builder.add_edge("finalize", END)



        return builder.compile()



    async def _route_node(self, state: SupervisorState) -> dict:

        """Select the target agent based on event_type.



        Supports:

        - Static routing via ROUTING_MAP (default)

        - Dynamic LLM-based routing (when agent_dynamic_routing enabled)

        - Hybrid mode for chat events (simple → chat, complex → autonomous)

        """

        event_type = state.get("event_type", "")

        payload = state.get("payload", {})



        # Default to static routing

        assigned = ROUTING_MAP.get(event_type, "analyzer")

        routing_method = "static"

        complexity = "simple"



        # Check if dynamic routing is enabled

        if settings.agent_dynamic_routing and self._llm:

            # For chat events, assess complexity for hybrid mode

            if event_type == "chat" and settings.agent_hybrid_mode:

                user_message = payload.get("userMessage", "")

                complexity = await self._assess_complexity(user_message)



                if complexity == "complex" and "autonomous" in self._agents:

                    assigned = "autonomous"

                    routing_method = "hybrid"

                    logger.info(

                        f"[Supervisor:route] Complex query detected, "

                        f"routing to autonomous agent"

                    )

                else:

                    # Simple chat → use static "chat" agent directly

                    assigned = "chat"

                    routing_method = "static"

            elif event_type != "chat":

                # Use LLM-based routing only for non-chat events WITHOUT static mapping

                # Skip dynamic routing if event_type has explicit static mapping

                if event_type in ROUTING_MAP:

                    logger.info(

                        f"[Supervisor:route] Using static routing for known event_type={event_type}"

                    )

                else:

                    assigned = await self._dynamic_route(event_type, payload)

                    routing_method = "dynamic"



        logger.info(

            f"[Supervisor:route] event_type={event_type} → agent={assigned} "

            f"(method={routing_method}, complexity={complexity})"

        )



        return {

            "assigned_agent": assigned,

            "routing_method": routing_method,

            "complexity": complexity,

        }



    async def _assess_complexity(self, message: str) -> str:

        """Assess query complexity for hybrid routing.



        Simple heuristics optimized for Gemma3:4b efficiency.

        """

        if not message:

            return "simple"



        lower = message.lower().strip()



        # Multi-part questions

        if lower.count("?") > 1:

            return "complex"



        # Comparison / contrast signals

        complex_markers = [

            "karsilastir", "compare", "fark", "difference", "vs",

            "neden", "why", "nasil", "how does", "explain",

            "analiz", "analyze", "evaluate", "avantaj", "pros and cons",

        ]

        if any(m in lower for m in complex_markers):

            return "complex"



        # Multi-step indicators

        multi_step_markers = [

            "ve sonra", "and then", "ayrica", "also", "sonra",

            "ardindan", "after that", "hem de", "as well as",

        ]

        if any(m in lower for m in multi_step_markers):

            return "complex"



        # Long queries likely need reasoning

        if len(lower.split()) > 20:

            return "complex"



        return "simple"



    async def _dynamic_route(self, event_type: str, payload: dict[str, Any]) -> str:

        """Use LLM for dynamic routing decisions."""

        if not self._llm:

            return ROUTING_MAP.get(event_type, "analyzer")



        # Get task preview from payload

        task_preview = (

            payload.get("userMessage", "")

            or payload.get("content", "")

            or payload.get("articleContent", "")

        )[:200]



        try:

            prompt = ROUTING_PROMPT.format(

                event_type=event_type,

                task_preview=task_preview,

            )

            response = await self._llm.generate_text(prompt)



            # Extract agent name from response

            agent_name = response.strip().lower().split()[0]



            # Validate agent exists

            if agent_name in self._agents:

                return agent_name



            # Fallback to static routing

            return ROUTING_MAP.get(event_type, "analyzer")



        except Exception as e:

            logger.warning(f"[Supervisor:dynamic_route] LLM routing failed: {e}")

            return ROUTING_MAP.get(event_type, "analyzer")



    async def _execute_node(self, state: SupervisorState) -> dict:

        """Execute the assigned agent."""

        agent_name = state.get("assigned_agent", "")

        logger.info(f"[Supervisor:execute] START agent={agent_name}")

        agent = self._agents.get(agent_name)

        if not agent:

            error = f"No agent registered for '{agent_name}'. Available: {list(self._agents.keys())}"

            logger.error(f"[Supervisor:execute] {error}")

            return {"error": error, "agent_result": None}



        payload = state.get("payload", {})

        language = state.get("language", "tr")



        # Inject event_type hint for ContentAgent

        payload_with_hint = {**payload, "_event_type": state.get("event_type", "")}



        try:

            logger.info(f"[Supervisor:execute] Calling agent.execute() for {agent_name}")

            result = await agent.execute(payload_with_hint, language)

            logger.info(

                f"[Supervisor:execute] agent={agent_name} completed, "

                f"result_keys={list(result.keys()) if result else 'None'}"

            )

            # Extract retrieved_chunks from agent_result for verification
            retrieved_chunks = result.get("retrieved_chunks") if result else None

            return {"agent_result": result, "retrieved_chunks": retrieved_chunks}

        except Exception as e:

            error_text = str(e).strip() or type(e).__name__

            logger.exception(f"[Supervisor:execute] agent={agent_name} failed: {error_text}")

            return {"error": error_text, "agent_result": None}



    async def _finalize_node(self, state: SupervisorState) -> dict:

        """Build the final response, optionally running verification."""

        if state.get("error"):

            return {"final_response": None}



        result = state.get("agent_result", {})

        # Get retrieved_chunks for citation verification
        retrieved_chunks = state.get("retrieved_chunks", [])

        # Phase 4: Verification — check generated text for hallucinations and citations

        if self._verifier and result:

            generated_text = (

                result.get("response")

                or result.get("summary")

                or result.get("description")

                or result.get("title")

                or result.get("excerpt")

                or result.get("improvedContent")

                or ""

            )

            original_content = state.get("payload", {}).get(

                "content", state.get("payload", {}).get("articleContent", "")

            )



            if generated_text and original_content:

                try:

                    v_result = await asyncio.wait_for(
                        self._verifier.verify(

                            original_content=original_content,

                            generated_output=generated_text,

                            retrieved_chunks=retrieved_chunks,

                            language=state.get("language", "tr"),

                        ),
                        timeout=settings.agent_verification_timeout_seconds,
                    )

                    passed = v_result.get("passed", True)



                    if not passed and v_result.get("corrections"):

                        logger.info("[Supervisor:verify] Applying corrections")

                        # Replace the generated text with the corrected version

                        corrected = v_result["corrections"]

                        for key in ("response", "summary", "description", "title", "excerpt", "improvedContent"):

                            if key in result and result[key]:

                                result[key] = corrected

                                break



                    return {

                        "final_response": result,

                        "verification_passed": passed,

                        "verification_result": v_result.get("verification_result"),

                    }

                except asyncio.TimeoutError:

                    logger.warning(
                        f"[Supervisor:verify] Timed out after "
                        f"{settings.agent_verification_timeout_seconds}s — returning original response"
                    )

                except Exception as e:

                    logger.warning(f"[Supervisor:verify] Verification failed (non-fatal): {e}")



        return {"final_response": result}



    async def run(

        self,

        event_type: str,

        payload: dict[str, Any],

        language: str = "tr",

    ) -> dict[str, Any]:

        """Public entry point for supervisor execution.



        Returns:

            The final agent result dict, or empty dict on failure.

        """

        initial: SupervisorState = {

            "event_type": event_type,

            "payload": payload,

            "language": language,

        }

        final = await self._graph.ainvoke(initial)



        if final.get("error"):

            error_text = str(final["error"]).strip() or "Supervisor pipeline failed"
            logger.error(f"[Supervisor] Pipeline error: {error_text}")
            raise RuntimeError(error_text)

        return final.get("final_response") or {}

