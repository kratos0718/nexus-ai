"""
Agent service — thin async wrapper around the synchronous LangGraph graph.

Runs the graph in a thread pool so it doesn't block the FastAPI event loop.
"""

import asyncio
import json
from typing import Optional
from loguru import logger

from app.agents.graph import build_agent_graph
from app.agents.state import AgentState


# Singleton graph — compiled once, reused for every request
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        logger.info("Compiling agent graph (first request)…")
        _graph = build_agent_graph()
    return _graph


class AgentService:

    async def run(
        self,
        question: str,
        document_id: Optional[str] = None,
        history: Optional[list[dict]] = None,
    ) -> dict:
        """
        Invoke the LangGraph agent and return the final state.
        Runs in a thread pool — LangGraph is synchronous.
        """
        graph = get_graph()
        where = {"document_id": document_id} if document_id else None

        initial_state: AgentState = {
            "question": question,
            "history": history or [],
            "document_filter": where,
            "route": "",
            "sub_questions": [],
            "context": [],
            "answer": "",
            "sources": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

        loop = asyncio.get_event_loop()
        final_state = await loop.run_in_executor(
            None,
            lambda: graph.invoke(initial_state),
        )

        return {
            "answer": final_state["answer"],
            "sources": final_state["sources"],
            "route": final_state["route"],
            "sub_questions": final_state.get("sub_questions", []),
            "prompt_tokens": final_state.get("prompt_tokens", 0),
            "completion_tokens": final_state.get("completion_tokens", 0),
        }

    async def stream(
        self,
        question: str,
        document_id: Optional[str] = None,
        history: Optional[list[dict]] = None,
    ):
        """
        Async generator that yields SSE events as the graph progresses.

        Events:
          data: [STEP] router       ← node started
          data: [ROUTE] complex     ← routing decision
          data: [PLAN] ["q1","q2"]  ← sub-questions (complex only)
          data: [CONTEXT] 8         ← number of chunks retrieved
          data: <token>             ← answer tokens streaming
          data: [SOURCES]{...}      ← citations
          data: [DONE]              ← stream complete
        """
        import threading
        import queue

        graph = get_graph()
        where = {"document_id": document_id} if document_id else None

        initial_state: AgentState = {
            "question": question,
            "history": history or [],
            "document_filter": where,
            "route": "",
            "sub_questions": [],
            "context": [],
            "answer": "",
            "sources": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

        event_queue: queue.Queue = queue.Queue()

        def run_graph():
            try:
                # stream_mode="updates" yields one dict per node as it completes
                for node_name, update in graph.stream(initial_state, stream_mode="updates"):
                    event_queue.put(("node_done", node_name, update))
                event_queue.put(("done", None, None))
            except Exception as e:
                event_queue.put(("error", str(e), None))

        thread = threading.Thread(target=run_graph, daemon=True)
        thread.start()

        final_sources = []

        while True:
            try:
                kind, name, data = event_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.02)
                continue

            if kind == "error":
                yield f"data: [ERROR]{name}\n\n"
                break

            if kind == "done":
                break

            if kind == "node_done":
                yield f"data: [STEP]{name}\n\n"

                if name == "router" and "route" in data:
                    yield f"data: [ROUTE]{data['route']}\n\n"

                if name == "planner" and "sub_questions" in data:
                    yield f"data: [PLAN]{json.dumps(data['sub_questions'])}\n\n"

                if name in ("rag", "researcher") and "context" in data:
                    yield f"data: [CONTEXT]{len(data['context'])}\n\n"

                if name == "synthesizer":
                    if "sources" in data:
                        final_sources = data["sources"]
                    if "answer" in data:
                        # Stream the answer token-by-token
                        answer = data["answer"]
                        words = answer.split(" ")
                        for i, word in enumerate(words):
                            chunk = word if i == 0 else " " + word
                            yield f"data: {chunk}\n\n"
                            await asyncio.sleep(0.005)

        yield f"data: [SOURCES]{json.dumps(final_sources)}\n\n"
        yield "data: [DONE]\n\n"


agent_service = AgentService()
