"""
LLM generation layer.

Builds the final prompt from retrieved context and query,
calls the LLM (Groq by default), returns answer + source citations.
"""

from typing import List, Optional
from dataclasses import dataclass
from loguru import logger

from app.rag.retrieval.vector_store import SearchResult


SYSTEM_PROMPT = """You are a precise knowledge assistant. Answer questions using ONLY the provided context.

Rules:
- Answer based solely on the context below
- If the answer is not in the context, say: "I don't have that information in the provided documents."
- Always cite the source document and page at the end of your answer
- Be concise and factual
- Do not add information not present in the context"""

CONTEXT_TEMPLATE = """<context>
{context_blocks}
</context>

<question>{question}</question>

Answer (cite sources):"""


@dataclass
class GenerationResult:
    answer: str
    sources: List[dict]
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


def format_context(results: List[SearchResult]) -> str:
    blocks = []
    for i, r in enumerate(results, 1):
        source = r.metadata.get("source", "unknown")
        page = r.metadata.get("page", "")
        page_ref = f", page {page}" if page else ""
        blocks.append(f"[{i}] Source: {source}{page_ref}\n{r.text}")
    return "\n\n---\n\n".join(blocks)


class GroqGenerator:
    """
    Generates answers using Groq's LLM API.
    Same interface as OpenAI — swap providers by changing base_url + api_key.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
        temperature: float = 0.1,
        max_tokens: int = 1500,
    ):
        from groq import Groq

        self._client = Groq(api_key=api_key)
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        logger.info(f"GroqGenerator ready: model={model}")

    def generate(
        self,
        query: str,
        context_results: List[SearchResult],
        history: List[dict] | None = None,
        system_prompt: Optional[str] = None,
    ) -> GenerationResult:
        context_text = format_context(context_results)
        user_message = CONTEXT_TEMPLATE.format(
            context_blocks=context_text,
            question=query,
        )

        messages = [{"role": "system", "content": system_prompt or SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )

        answer = response.choices[0].message.content
        usage = response.usage

        sources = []
        for r in context_results:
            sources.append({
                "chunk_id": r.chunk_id,
                "source": r.metadata.get("source", ""),
                "page": r.metadata.get("page"),
                "score": round(r.score, 4),
            })

        return GenerationResult(
            answer=answer,
            sources=sources,
            model=self._model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )

    def generate_stream(
        self,
        query: str,
        context_results: List[SearchResult],
        history: List[dict] | None = None,
        system_prompt: Optional[str] = None,
    ):
        """
        Yields text tokens one-by-one as they arrive from Groq.
        Each yield is a string fragment (a few chars or a word).
        The caller wraps this in an SSE response.
        """
        context_text = format_context(context_results)
        user_message = CONTEXT_TEMPLATE.format(
            context_blocks=context_text,
            question=query,
        )

        messages = [{"role": "system", "content": system_prompt or SYSTEM_PROMPT}]

        # Inject conversation history before the current question
        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": user_message})

        stream = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            stream=True,          # ← key flag: returns iterator instead of full response
        )

        for chunk in stream:
            token = chunk.choices[0].delta.content
            if token:             # last chunk has content=None
                yield token
