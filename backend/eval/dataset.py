"""
Evaluation test cases for the RAG pipeline.

Each EvalCase captures:
  question        — what the user asks
  ground_truth    — the correct answer (human-written reference)
  expected_topics — key topics the answer must cover (for custom scoring)
  document_hint   — what kind of document this tests (for human readers)

How to add new cases:
  1. Index a real document in your system
  2. Write 3-5 questions whose answers are clearly in the document
  3. Write the ground_truth by reading the document yourself
  4. Run run_eval.py and check the scores

The dataset is intentionally small (10 cases) — enough to get meaningful
scores without taking 10 minutes to run. In production, 50-200 cases is typical.
"""

from dataclasses import dataclass, field


@dataclass
class EvalCase:
    question: str
    ground_truth: str
    expected_topics: list[str] = field(default_factory=list)
    document_hint: str = ""


# ── Sample dataset ─────────────────────────────────────────────────────────────
# These are generic cases that work with any knowledge base.
# Replace / extend with questions specific to YOUR indexed documents.

EVAL_DATASET: list[EvalCase] = [
    EvalCase(
        question="What is RAG and how does it work?",
        ground_truth=(
            "RAG (Retrieval-Augmented Generation) combines information retrieval "
            "with language model generation. It first retrieves relevant document "
            "chunks from a vector database based on the query, then passes those "
            "chunks as context to an LLM which generates a grounded answer."
        ),
        expected_topics=["retrieval", "generation", "vector database", "context"],
        document_hint="AI/ML documentation",
    ),
    EvalCase(
        question="What are embeddings and what are they used for?",
        ground_truth=(
            "Embeddings are dense numerical vector representations of text that "
            "capture semantic meaning. Similar texts have vectors that are close "
            "in the vector space. They are used for semantic search, document "
            "retrieval, clustering, and as input to downstream ML models."
        ),
        expected_topics=["vector", "semantic", "numerical", "similarity"],
        document_hint="AI/ML documentation",
    ),
    EvalCase(
        question="What is chunking and why is it important for RAG?",
        ground_truth=(
            "Chunking is the process of splitting documents into smaller pieces "
            "before indexing. It is important because LLMs have token limits, "
            "smaller chunks allow more precise retrieval, and irrelevant "
            "surrounding text is excluded from the context window."
        ),
        expected_topics=["splitting", "token", "retrieval", "context"],
        document_hint="RAG documentation",
    ),
    EvalCase(
        question="What is the difference between dense and sparse retrieval?",
        ground_truth=(
            "Dense retrieval uses neural embeddings and cosine similarity to find "
            "semantically similar documents. Sparse retrieval uses term-frequency "
            "methods like BM25 which match exact keywords. Hybrid search combines "
            "both to get the benefits of semantic understanding and keyword precision."
        ),
        expected_topics=["embedding", "BM25", "keyword", "semantic", "hybrid"],
        document_hint="Search/retrieval documentation",
    ),
    EvalCase(
        question="What is a vector database and how does it differ from a relational database?",
        ground_truth=(
            "A vector database stores high-dimensional embedding vectors and supports "
            "approximate nearest neighbor search. Unlike relational databases which "
            "use exact SQL queries on structured data, vector databases find the most "
            "similar vectors to a query vector using algorithms like HNSW."
        ),
        expected_topics=["vector", "embedding", "nearest neighbor", "HNSW", "similarity"],
        document_hint="Database documentation",
    ),
]
