"""Autonomous Agent - Plan-Execute-Reflect-Adapt loop for fully autonomous operation.

Implements the core autonomous execution loop with:
1. PLAN: Create execution plan
2. EXECUTE: Follow plan steps
3. REFLECT: Evaluate results
4. ADAPT: Replan if needed
5. FINALIZE: Synthesize final answer
"""

import logging
import time
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, TYPE_CHECKING

from langgraph.graph import StateGraph, END

from app.agents.base_agent import BaseSpecializedAgent
from app.agents.planner_agent import (
    PlannerAgent,
    Plan,
    PlanStep,
    StepType,
    PlanStatus,
)
from app.agents.plan_validator import PlanValidator, ValidationResult
from app.core.autonomy_guardrails import (
    AutonomyGuardrails,
    GracefulTerminator,
    TerminationReason,
)
from app.core.config import settings
from app.memory.checkpointer import get_memory_saver
from app.domain.interfaces.i_llm_provider import ILLMProvider

if TYPE_CHECKING:
    from app.memory.episodic_memory import EpisodicMemory

logger = logging.getLogger(__name__)


class ExecutionMode(Enum):
    """Agent execution modes."""

    HYBRID = "hybrid"  # Use ReAct for simple, Autonomous for complex
    AUTONOMOUS = "autonomous"  # Always use planning + execution
    REACTIVE = "reactive"  # Simple reactive mode without planning


@dataclass
class AutonomousState(dict):
    """State for the autonomous agent graph."""

    # Input
    task: str = ""
    post_id: str = ""
    session_id: str = ""
    conversation_history: str = ""
    language: str = "tr"
    context: dict[str, Any] | None = None

    # Planning
    plan: Plan | None = None
    plan_validation: ValidationResult | None = None

    # Execution
    current_step: PlanStep | None = None
    step_result: str = ""
    observations: list[str] = None
    executed_steps: list[dict[str, Any]] = None

    # Reflection
    reflection: str = ""
    confidence: float = 0.0
    step_success: bool = False

    # Output
    final_answer: str = ""
    termination_reason: str = ""

    # Tracking
    iterations: int = 0
    replan_count: int = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.observations = []
        self.executed_steps = []
        self.context = {}


# Reflection prompt for Gemma3:4b - short and direct
REFLECTION_PROMPT = """Step goal: {expected}
Actual result: {result}

Was this step successful? Reply:
- YES if result matches goal
- NO if result is incomplete or wrong
- Brief reason (10 words max)

Answer:"""

SYNTHESIS_PROMPT = """Task: {task}
Findings:
{observations}

Create a complete answer in {language}.
Be concise and accurate.

Answer:"""


class AutonomousAgent(BaseSpecializedAgent):
    """Fully autonomous agent with Plan-Execute-Reflect-Adapt loop.

    Optimized for Gemma3:4b with:
    - Simple 3-4 step plans
    - Quick reflection checks
    - Limited replanning
    - Graceful termination
    """

    @property
    def name(self) -> str:
        return "autonomous"

    def __init__(
        self,
        llm_provider: ILLMProvider,
        tools: dict[str, Callable] | None = None,
        mode: ExecutionMode = ExecutionMode.HYBRID,
        planner: PlannerAgent | None = None,
        validator: PlanValidator | None = None,
        guardrails: AutonomyGuardrails | None = None,
        episodic_memory: "EpisodicMemory | None" = None,
    ):
        self._llm = llm_provider
        self._tools = tools or {}
        self._mode = mode

        # Initialize components
        self._planner = planner or PlannerAgent(
            llm_provider=llm_provider,
            available_tools=list(self._tools.keys()) + ["final_answer"],
        )
        self._validator = validator or PlanValidator(
            available_tools=list(self._tools.keys()),
        )
        self._guardrails = guardrails or AutonomyGuardrails()
        self._terminator = GracefulTerminator(self._guardrails)
        self._episodic_memory = episodic_memory

        # Build the graph
        self._graph = self._build_graph()

    def get_graph(self) -> StateGraph:
        return self._graph

    def _build_graph(self) -> Any:
        """Build the Plan-Execute-Reflect-Adapt state machine."""
        builder = StateGraph(AutonomousState)

        # Add nodes
        builder.add_node("plan", self._plan_node)
        builder.add_node("execute", self._execute_node)
        builder.add_node("reflect", self._reflect_node)
        builder.add_node("adapt", self._adapt_node)
        builder.add_node("finalize", self._finalize_node)

        # Define flow
        builder.set_entry_point("plan")

        # Plan -> Execute (or Finalize if no steps)
        builder.add_conditional_edges(
            "plan",
            self._should_execute,
            {"execute": "execute", "finalize": "finalize"},
        )

        # Execute -> Reflect
        builder.add_edge("execute", "reflect")

        # Reflect -> (Execute next, Adapt, or Finalize)
        builder.add_conditional_edges(
            "reflect",
            self._after_reflection,
            {"continue": "execute", "adapt": "adapt", "finalize": "finalize"},
        )

        # Adapt -> Execute (with new plan) or Finalize (if too many replans)
        builder.add_conditional_edges(
            "adapt",
            self._after_adapt,
            {"execute": "execute", "finalize": "finalize"},
        )

        # Finalize -> END
        builder.add_edge("finalize", END)

        return builder.compile()

    async def _plan_node(self, state: AutonomousState) -> dict:
        """Create or validate the execution plan."""
        self._guardrails.reset()

        task = state.get("task", "")
        context = state.get("context", {}) or {}

        # Create plan
        plan = await self._planner.create_plan(task, context)
        state["plan"] = plan

        # Validate plan
        validation = self._validator.validate(plan)
        state["plan_validation"] = validation

        if not validation.is_valid:
            logger.warning(f"[Autonomous:plan] Validation failed: {validation.errors}")
            # Sanitize plan
            plan = self._validator.sanitize_plan(plan)
            state["plan"] = plan

        # Record action
        self._guardrails.record_action("plan_created")

        logger.info(
            f"[Autonomous:plan] Created plan with {len(plan.steps)} steps"
        )

        return {
            "plan": plan,
            "plan_validation": validation,
            "iterations": 0,
            "observations": [],
            "executed_steps": [],
        }

    async def _execute_node(self, state: AutonomousState) -> dict:
        """Execute the current step in the plan."""
        plan = state.get("plan")
        if not plan:
            return {"step_result": "No plan available", "step_success": False}

        current_step = plan.get_current_step()
        if not current_step:
            return {"step_result": "No more steps", "step_success": True}

        state["current_step"] = current_step
        action = current_step.action
        input_hint = current_step.input_hint

        # Record iteration
        self._guardrails.record_iteration()
        self._guardrails.record_action(action)

        logger.info(
            f"[Autonomous:execute] Step {current_step.step_number}: "
            f"{action} with input: {input_hint[:50]}..."
        )

        # Execute based on action type
        if action == "final_answer" or current_step.step_type == StepType.FINAL:
            # Generate final answer from observations
            result = await self._synthesize_final(state)
            return {
                "step_result": result,
                "step_success": True,
                "final_answer": result,
            }

        # Execute tool
        tool = self._tools.get(action)
        if not tool:
            result = f"Tool '{action}' not available"
            return {"step_result": result, "step_success": False}

        try:
            # Call tool with appropriate parameters
            post_id = state.get("post_id", "")
            session_id = state.get("session_id", "")
            language = state.get("language", "tr")
            tool_kwargs = {
                "post_id": post_id,
                "session_id": session_id,
                "language": language,
                "auth_context": (state.get("context", {}) or {}).get("auth_context"),
            }
            try:
                result = await tool(query=input_hint, **tool_kwargs)
            except TypeError:
                # Backward-compatible call path for tools that don't accept context kwargs.
                if action == "rag_retrieve":
                    result = await tool(query=input_hint, post_id=post_id)
                else:
                    result = await tool(query=input_hint)

            # Record LLM call estimate (tools may use LLM)
            self._guardrails.record_llm_call(tokens=len(result.split()) * 2)

            return {"step_result": result, "step_success": bool(result)}

        except Exception as e:
            logger.error(f"[Autonomous:execute] Tool {action} failed: {e}")
            self._guardrails.record_error(str(e))
            return {"step_result": f"Error: {e}", "step_success": False}

    async def _reflect_node(self, state: AutonomousState) -> dict:
        """Reflect on the executed step's result."""
        current_step = state.get("current_step")
        step_result = state.get("step_result", "")
        plan = state.get("plan")

        if not current_step:
            return {"reflection": "No step to reflect on", "confidence": 0.5}

        # Mark step as completed/failed in plan
        if state.get("step_success"):
            plan.mark_step_completed(step_result)
        else:
            plan.mark_step_failed(state.get("step_result", "Unknown error"))

        # Quick reflection check
        reflection = await self._quick_reflection(
            expected=current_step.expected_output,
            result=step_result,
        )

        # Add observation
        observations = state.get("observations", [])
        observations.append(f"[{current_step.action}] {step_result[:500]}")

        # Record confidence
        confidence = self._extract_confidence(reflection)
        self._guardrails.record_confidence(confidence)

        # Record result preview for semantic loop detection
        self._guardrails.record_action(
            action=current_step.action,
            result_preview=step_result[:200] if step_result else None
        )

        logger.info(
            f"[Autonomous:reflect] Step {current_step.step_number}: "
            f"success={state.get('step_success')}, confidence={confidence:.2f}"
        )

        # Advance plan
        has_more = plan.advance()
        state["iterations"] = state.get("iterations", 0) + 1

        return {
            "reflection": reflection,
            "confidence": confidence,
            "observations": observations,
            "plan": plan,
            "step_success": state.get("step_success"),
        }

    async def _adapt_node(self, state: AutonomousState) -> dict:
        """Adapt the plan based on reflection."""
        plan = state.get("plan")
        current_step = state.get("current_step")
        step_result = state.get("step_result", "")

        if not plan or not current_step:
            return {"plan": plan}

        # Create new plan with alternative approach
        new_plan = await self._planner.replan(
            original_plan=plan,
            failed_step=current_step,
            observation=step_result,
            error=None if state.get("step_success") else step_result,
        )

        # Validate new plan
        validation = self._validator.validate(new_plan)
        if not validation.is_valid:
            new_plan = self._validator.sanitize_plan(new_plan)

        new_plan.replan_count = plan.replan_count + 1
        new_plan.status = PlanStatus.REPLANNED

        self._guardrails.record_action("replan")

        logger.info(
            f"[Autonomous:adapt] Replanned (count: {new_plan.replan_count})"
        )

        return {
            "plan": new_plan,
            "replan_count": new_plan.replan_count,
        }

    async def _finalize_node(self, state: AutonomousState) -> dict:
        """Generate final answer and cleanup.

        Provides contextual fallback messages based on:
        - What errors occurred
        - How many iterations ran
        - Plan status
        - Loop detection (uses RAG fallback)
        """
        # If we have a final answer, use it
        if state.get("final_answer"):
            return {"final_answer": state["final_answer"]}

        # Otherwise synthesize from observations
        observations = state.get("observations", [])
        language = state.get("language", "tr")
        iterations = state.get("iterations", 0)
        plan = state.get("plan")
        termination_reason = state.get("termination_reason", "")

        # Check for RAG fallback flag (set when loop detected)
        if state.get("fallback_to_rag") and observations:
            logger.info("[Autonomous] Using RAG fallback to synthesize from observations")
            # Synthesize from observations for a partial answer
            final = await self._synthesize_final(state)
            if final and final != "No information gathered to answer the question.":
                # Add context that this is a partial result
                prefix = (
                    "İşlem sırasında bir döngü algılandı, ancak elde edilen bilgiler: "
                    if language == "tr" else
                    "A loop was detected during processing. Based on gathered information: "
                )
                return {"final_answer": f"{prefix}{final}"}

        if observations:
            final = await self._synthesize_final(state)
            return {"final_answer": final}

        # Generate contextual fallback message based on what happened
        fallback = self._generate_contextual_fallback(
            language=language,
            iterations=iterations,
            plan=plan,
            termination_reason=termination_reason,
            observations=observations,
        )
        return {"final_answer": fallback}

    def _generate_contextual_fallback(
        self,
        language: str,
        iterations: int,
        plan: Plan | None,
        termination_reason: str,
        observations: list[str],
    ) -> str:
        """Generate a contextual fallback message based on execution state."""
        is_turkish = language == "tr"

        # Check if we have partial results
        has_partial_results = len(observations) > 0

        # Determine the most helpful message based on context
        if termination_reason == "loop_detected":
            if has_partial_results:
                return (
                    "İşlem sırasında bir döngü algılandı, ancak bazı bilgiler toplandı. "
                    "Lütfen sorununuzu daha basit bir şekilde tekrar deneyin."
                    if is_turkish else
                    "A loop was detected during processing, but some information was gathered. "
                    "Please try rephrasing your question more simply."
                )
            return (
                "İşlem sırasında bir döngü algılandı. "
                "Lütfen sorununuzu daha basit bir şekilde sormayı deneyin."
                if is_turkish else
                "A loop was detected during processing. "
                "Please try asking your question in a simpler way."
            )

        if termination_reason == "max_iterations":
            if has_partial_results:
                return (
                    f"İşlem maksimum adım sayısına ({iterations}) ulaştı. "
                    "Kısmi sonuçlar mevcut - lütfen daha spesifik bir soru sorun."
                    if is_turkish else
                    f"Processing reached the maximum step limit ({iterations}). "
                    "Partial results are available - please try a more specific question."
                )
            return (
                f"İşlem maksimum adım sayısına ulaştı ({iterations}). "
                "Lütfen daha basit bir soru sormayı deneyin."
                if is_turkish else
                f"Processing reached the maximum step limit ({iterations}). "
                "Please try asking a simpler question."
            )

        if termination_reason == "timeout":
            return (
                "İşlem zaman aşımına uğradı. Lütfen daha kısa bir soru sorun veya daha sonra tekrar deneyin."
                if is_turkish else
                "Processing timed out. Please try a shorter question or try again later."
            )

        if plan and plan.replan_count > 0:
            return (
                "Plan birden fazla kez güncellendi ancak tamamlanamadı. "
                "Lütfen sorununuzu daha net bir şekilde sormayı deneyin."
                if is_turkish else
                "The plan was updated multiple times but couldn't be completed. "
                "Please try phrasing your question more clearly."
            )

        # Generic fallback
        return (
            "İstediğiniz işlem tamamlanamadı. Lütfen farklı bir şekilde sormayı deneyin."
            if is_turkish else
            "Unable to complete the requested task. Please try asking in a different way."
        )

    # ── Conditional Edge Handlers ─────────────────────────────────────

    def _should_execute(self, state: AutonomousState) -> str:
        """Decide if we should execute or finalize."""
        plan = state.get("plan")
        if not plan or not plan.steps:
            return "finalize"
        return "execute"

    async def _after_reflection(self, state: AutonomousState) -> str:
        """Decide next action after reflection."""
        plan = state.get("plan")
        iterations = state.get("iterations", 0)

        # Check guardrails
        guardrail_result = await self._guardrails.should_continue(
            has_final_answer=bool(state.get("final_answer")),
            confidence=state.get("confidence"),
        )

        if not guardrail_result.should_continue:
            logger.info(
                f"[Autonomous] Guardrail triggered: {guardrail_result.reason.value}"
            )
            state["termination_reason"] = guardrail_result.reason.value

            # When loop detected, set flag for RAG fallback instead of generic fail
            if guardrail_result.reason == TerminationReason.LOOP_DETECTED:
                state["fallback_to_rag"] = True
                logger.info("[Autonomous] Loop detected, will use RAG fallback for partial answer")

            return "finalize"

        # Check if we have a final answer
        if state.get("final_answer"):
            return "finalize"

        # Check if step failed and needs adaptation
        if not state.get("step_success") and plan.replan_count < 2:
            return "adapt"

        # Check if more steps remain
        if plan.current_step < len(plan.steps):
            return "continue"

        return "finalize"

    def _after_adapt(self, state: AutonomousState) -> str:
        """Decide after adaptation."""
        plan = state.get("plan")

        # Too many replans - force finalize
        if plan.replan_count > 2:
            return "finalize"

        return "execute"

    # ── Helper Methods ─────────────────────────────────────────────────

    async def _quick_reflection(self, expected: str, result: str) -> str:
        """Quick reflection on step result using LLM."""
        prompt = REFLECTION_PROMPT.format(
            expected=expected[:200],
            result=result[:500],
        )

        try:
            response = await self._llm.generate_text(prompt)
            self._guardrails.record_llm_call(tokens=len(response.split()) * 2)
            return response.strip()
        except Exception as e:
            logger.warning(f"[Autonomous] Reflection failed: {e}")
            return "YES (default)"

    def _extract_confidence(self, reflection: str) -> float:
        """Extract confidence score from reflection."""
        lower = reflection.lower()

        # Explicit confidence mention
        conf_match = re.search(r"confidence[:\s]+(\d+\.?\d*)", lower)
        if conf_match:
            return float(conf_match.group(1))

        # YES/NO detection
        if lower.startswith("yes"):
            return 0.8
        elif lower.startswith("no"):
            return 0.3

        # Default moderate confidence
        return 0.5

    async def _synthesize_final(self, state: AutonomousState) -> str:
        """Synthesize final answer from observations."""
        task = state.get("task", "")
        observations = state.get("observations", [])
        language = state.get("language", "tr")

        if not observations:
            return "No information gathered to answer the question."

        obs_text = "\n".join(f"- {obs}" for obs in observations[-5:])  # Last 5

        prompt = SYNTHESIS_PROMPT.format(
            task=task,
            observations=obs_text,
            language="Turkish" if language == "tr" else language,
        )

        try:
            response = await self._llm.generate_text(prompt)
            self._guardrails.record_llm_call(tokens=len(response.split()) * 2)
            return response.strip()
        except Exception as e:
            logger.error(f"[Autonomous] Synthesis failed: {e}")
            # Return last observation as fallback
            return observations[-1] if observations else "Unable to generate answer."

    # ── Public Interface ───────────────────────────────────────────────

    async def execute(self, payload: dict[str, Any], language: str) -> dict[str, Any]:
        """Execute the autonomous agent.

        Args:
            payload: Task payload with task, post_id, context, etc.
            language: Response language

        Returns:
            Dict with response and metadata
        """
        task = payload.get("userMessage", payload.get("task", ""))
        post_id = payload.get("postId", "")
        session_id = payload.get("sessionId", "")
        history = payload.get("conversationHistory", "")
        payload_context = payload.get("context", {}) or {}

        initial_state: AutonomousState = {
            "task": task,
            "post_id": post_id,
            "session_id": session_id,
            "conversation_history": history,
            "language": language,
            "context": {
                "post_id": post_id,
                "session_id": session_id,
                "has_memory": bool(history),
                **payload_context,
            },
            "plan": None,
            "observations": [],
            "executed_steps": [],
            "iterations": 0,
            "replan_count": 0,
        }

        try:
            start_time = time.time()
            final_state = await self._graph.ainvoke(initial_state)
            duration = time.time() - start_time

            # Store episode to episodic memory for learning
            if self._episodic_memory and settings.agent_episodic_memory_enabled:
                try:
                    await self._episodic_memory.store_episode(
                        task=task,
                        plan=final_state.get("plan"),
                        execution_trace=final_state.get("executed_steps", []),
                        outcome=final_state.get("final_answer", ""),
                        success=bool(final_state.get("final_answer")),
                        confidence=self._guardrails.state.confidence_scores[-1] if self._guardrails.state.confidence_scores else 0.5,
                        duration_seconds=duration,
                        metadata={
                            "session_id": session_id,
                            "post_id": post_id,
                            "language": language,
                            "replan_count": final_state.get("replan_count", 0),
                        },
                    )
                except Exception as e:
                    logger.warning(f"[Autonomous] Failed to store episode: {e}")

            return {
                "response": final_state.get("final_answer", "Task could not be completed."),
                "plan": final_state.get("plan").to_dict() if final_state.get("plan") else None,
                "iterations": final_state.get("iterations", 0),
                "guardrail_status": self._guardrails.get_status(),
            }

        except Exception as e:
            logger.exception(f"[Autonomous] Execution failed: {e}")
            termination = await self._terminator.terminate(
                reason=TerminationReason.ERROR,
                partial_result=None,
                context={"error": str(e)},
            )
            return {
                "response": termination["message"],
                "error": str(e),
                "termination": termination,
            }

    async def run(
        self,
        task: str,
        post_id: str = "",
        conversation_history: str = "",
        language: str = "tr",
    ) -> str:
        """Simple run interface returning just the answer."""
        payload = {
            "task": task,
            "userMessage": task,
            "postId": post_id,
            "conversationHistory": conversation_history,
        }
        result = await self.execute(payload, language)
        return result.get("response", "")


