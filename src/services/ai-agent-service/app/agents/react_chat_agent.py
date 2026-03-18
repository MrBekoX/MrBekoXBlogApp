"""ReAct chat agent - iterative Thought -> Action -> Observation loop."""

import logging
import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.tools.rag_tool import RagRetrieveTool
from app.agents.tools.web_search_tool import WebSearchTool
from app.core.config import settings
from app.domain.interfaces.i_llm_provider import ILLMProvider
from app.security.backend_authorization_client import AuthorizationContext

logger = logging.getLogger(__name__)


class ReActState(TypedDict, total=False):
    """State for the ReAct reasoning loop."""

    user_message: str
    post_id: str
    conversation_history: str
    language: str
    auth_context: dict[str, Any] | None
    thought: str
    action: str
    action_input: str
    observation: str
    final_answer: str
    iteration: int
    max_iterations: int
    observations: list[str]


REACT_PROMPT_TEMPLATE = """You are a strict Q&A agent that answers questions ONLY from the provided article context.
You have access to these tools:
- rag_retrieve: Retrieve relevant sections from the article. Input: search query string.
- final_answer: Provide the final answer. Input: the answer text.

CRITICAL RULES:
1. SOURCE BINDING: Your ENTIRE answer MUST be based on content retrieved via 'rag_retrieve'.
   Do NOT use any external or general knowledge, even if you know the answer.
2. NO HALLUCINATION: If 'rag_retrieve' returns no relevant information, you MUST say the
   article does not cover this topic. Never invent or guess.
3. COMPARE/CONTRAST: When comparing items, state ONLY what the retrieved text says.
   If the article does not explicitly compare them, say so honestly.
4. DO NOT use 'web_search'. This agent is article-bound.

Use this format:
Thought: [your step-by-step reasoning]
Action: rag_retrieve
Action Input: [search query]

When you have retrieved enough article content OR confirmed the article doesn't cover it:
Thought: [reasoning]
Action: final_answer
Action Input: [answer]

Previous observations:
{observations}

Conversation context:
{history}

Question: {question}

{language_hint}

Thought:"""


class ReActChatAgent:
    """Implements a ReAct loop using LangGraph."""

    def __init__(
        self,
        llm_provider: ILLMProvider,
        web_search_tool: WebSearchTool | None = None,
        rag_tool: RagRetrieveTool | None = None,
    ):
        self._llm = llm_provider
        self._tools: dict[str, Any] = {}
        if web_search_tool:
            self._tools["web_search"] = web_search_tool
        if rag_tool:
            self._tools["rag_retrieve"] = rag_tool
        self._max_iterations = settings.agent_max_react_steps
        self._graph = self._build_graph()

    def _build_graph(self) -> Any:
        builder = StateGraph(ReActState)
        builder.add_node("think", self._think_node)
        builder.add_node("act", self._act_node)
        builder.add_node("observe", self._observe_node)
        builder.set_entry_point("think")
        builder.add_edge("think", "act")
        builder.add_conditional_edges(
            "act",
            self._should_continue,
            {"observe": "observe", "end": END},
        )
        builder.add_edge("observe", "think")
        return builder.compile()

    def _should_continue(self, state: ReActState) -> str:
        if state.get("final_answer"):
            return "end"
        iteration = state.get("iteration", 0)
        if iteration >= state.get("max_iterations", self._max_iterations):
            return "end"
        return "observe"

    async def _think_node(self, state: ReActState) -> dict:
        observations = state.get("observations", [])
        obs_text = "\n".join(observations) if observations else "None yet."
        history = state.get("conversation_history", "")
        language = state.get("language", "tr")

        if language == "tr":
            language_hint = (
                "IMPORTANT: The entire answer must be in Turkish. "
                "Even if the article is in English, always answer in Turkish."
            )
        else:
            language_hint = f"Answer entirely in {language}. Do not mix languages."

        prompt = REACT_PROMPT_TEMPLATE.format(
            observations=obs_text,
            history=history,
            question=state.get("user_message", ""),
            language_hint=language_hint,
        )

        try:
            response = await self._llm.generate_text(prompt)
            thought, action, action_input = self._parse_react_response(response)
            return {
                "thought": thought,
                "action": action,
                "action_input": action_input,
            }
        except Exception as exc:
            logger.error("[ReAct:think] LLM call failed: %s", exc)
            fallback_msg = (
                "Bu soruyu isleyemedim. Lutfen farkli bir ifadeyle deneyin."
                if language == "tr"
                else "I was unable to process this question. Please try rephrasing."
            )
            return {
                "thought": "Reasoning failed, providing direct answer.",
                "action": "final_answer",
                "action_input": fallback_msg,
            }

    async def _act_node(self, state: ReActState) -> dict:
        action = state.get("action", "final_answer")
        action_input = state.get("action_input", "")
        iteration = state.get("iteration", 0) + 1
        language = state.get("language", "tr")

        if action == "final_answer":
            return {"final_answer": action_input, "iteration": iteration}

        if action == "web_search":
            logger.warning("[ReAct:act] web_search blocked - agent is article-bound")
            msg = (
                "Makale bu konuyu ele almiyor. Sadece makaledeki bilgilere dayali yanit verebilirim."
                if language == "tr"
                else "The article does not cover this topic. I can only answer based on the article content."
            )
            return {"final_answer": msg, "action": "final_answer", "iteration": iteration}

        tool = self._tools.get(action)
        if not tool:
            logger.warning("[ReAct:act] Unknown tool: %s", action)
            return {
                "observation": f"Tool '{action}' not available.",
                "iteration": iteration,
            }

        try:
            post_id = state.get("post_id", "")
            if action == "rag_retrieve":
                auth_context = AuthorizationContext.from_payload(state.get("auth_context") or {})
                result = await tool(query=action_input, post_id=post_id, auth_context=auth_context)
            else:
                result = await tool(query=action_input)
            return {"observation": result, "iteration": iteration}
        except Exception as exc:
            logger.warning("[ReAct:act] Tool %s failed: %s", action, exc)
            return {"observation": f"Tool error: {exc}", "iteration": iteration}

    async def _observe_node(self, state: ReActState) -> dict:
        obs = state.get("observation", "")
        observations = list(state.get("observations", []))
        action = state.get("action", "unknown")
        language = state.get("language", "tr")

        entry = f"[{action}] {obs[:1000]}"
        observations.append(entry)

        if action == "rag_retrieve":
            stripped = obs.strip()
            no_content_signals = [
                not stripped,
                len(stripped) < 50,
                "no relevant" in stripped.lower(),
                "not found" in stripped.lower(),
                "bulunamadi" in stripped.lower(),
            ]
            if any(no_content_signals):
                if language == "tr":
                    fallback = (
                        "Makale bu konuyu ele almiyor. "
                        "Sadece makalede gecen konular hakkinda yardimci olabilirim."
                    )
                else:
                    fallback = (
                        "The article does not cover this topic. "
                        "I can only assist with topics discussed in the article."
                    )
                return {
                    "observations": observations,
                    "final_answer": fallback,
                    "action": "final_answer",
                }

        return {"observations": observations}

    @staticmethod
    def _parse_react_response(response: str) -> tuple[str, str, str]:
        thought = ""
        action = "final_answer"
        action_input = ""

        thought_match = re.search(r"Thought:\s*(.+?)(?=Action:|$)", response, re.DOTALL)
        if thought_match:
            thought = thought_match.group(1).strip()

        action_match = re.search(r"Action:\s*(\w+)", response)
        if action_match:
            action = action_match.group(1).strip()

        input_match = re.search(r"Action Input:\s*(.+?)(?=Thought:|$)", response, re.DOTALL)
        if input_match:
            action_input = input_match.group(1).strip()

        return thought, action, action_input

    async def run(
        self,
        user_message: str,
        post_id: str = "",
        conversation_history: str = "",
        language: str = "tr",
        auth_context: AuthorizationContext | None = None,
    ) -> str:
        initial: ReActState = {
            "user_message": user_message,
            "post_id": post_id,
            "conversation_history": conversation_history,
            "language": language,
            "auth_context": {
                "subjectType": auth_context.subject_type if auth_context else "anonymous",
                "subjectId": auth_context.subject_id if auth_context else None,
                "roles": auth_context.roles if auth_context else [],
                "fingerprint": auth_context.fingerprint if auth_context else None,
            },
            "iteration": 0,
            "max_iterations": self._max_iterations,
            "observations": [],
        }

        final = await self._graph.ainvoke(initial)

        answer = final.get("final_answer", "")
        if not answer:
            observations = final.get("observations", [])
            if observations:
                answer = observations[-1]
            else:
                answer = (
                    "Soruyu cevaplayamadim."
                    if language == "tr"
                    else "I could not answer the question."
                )

        logger.info(
            "[ReAct] Completed in %s iterations, answer_length=%s",
            final.get("iteration", 0),
            len(answer),
        )
        return answer
