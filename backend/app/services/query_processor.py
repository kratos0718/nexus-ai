"""
Query Processor — transforms user questions before retrieval to improve result quality.

Two techniques:
  1. HyDE (Hypothetical Document Embeddings)
       Generate a short hypothetical answer to the question, embed THAT instead.
       Documents live in "answer space"; questions live in "question space".
       A hypothetical answer is shaped like a document, so it retrieves better.

  2. Multi-query expansion
       Generate N differently-worded versions of the question.
       Retrieve chunks for each phrasing, deduplicate, and merge.
       Catches blind spots: different phrasings surface different chunks.

Usage:
    processor = QueryProcessor(llm)
    hyde_text = processor.hyde("What is chunking in RAG?")
    variants  = processor.expand_queries("What is chunking in RAG?")
"""

from loguru import logger


class QueryProcessor:
    """Wraps an LLM to transform queries before retrieval."""

    def __init__(self, llm):
        self.llm = llm

    def hyde(self, question: str) -> str:
        """
        Generate a short hypothetical document that would answer the question.
        Returns the hypothetical text — caller should embed this instead of the question.
        Falls back to the original question on any LLM failure.
        """
        prompt = (
            "Write a short factual paragraph (2–4 sentences) that directly answers "
            "the question below. Do not say you cannot answer. Write only the answer, "
            "no preamble.\n\n"
            f"Question: {question}\n\n"
            "Answer:"
        )
        try:
            raw = self.llm.invoke(prompt)
            text = (raw.content if hasattr(raw, "content") else str(raw)).strip()
            if text:
                logger.debug(f"HyDE generated: '{text[:80]}'")
                return text
        except Exception as e:
            logger.warning(f"HyDE generation failed: {e}")
        return question  # graceful fallback

    def expand_queries(self, question: str, n: int = 3) -> list[str]:
        """
        Generate n alternative phrasings of the question.
        Returns a list starting with the original question followed by variants.
        Falls back to [question] on failure.
        """
        prompt = (
            f"Generate {n} alternative ways to phrase the following question. "
            "Each phrasing should have different wording but the same intent. "
            "Return ONLY the questions, one per line, no numbering, no extra text.\n\n"
            f"Question: {question}"
        )
        try:
            raw = self.llm.invoke(prompt)
            text = (raw.content if hasattr(raw, "content") else str(raw)).strip()
            variants = [line.strip() for line in text.split("\n") if line.strip()][:n]
            if variants:
                logger.debug(f"Expanded to {len(variants)+1} queries for: '{question[:50]}'")
                return [question] + variants
        except Exception as e:
            logger.warning(f"Query expansion failed: {e}")
        return [question]
