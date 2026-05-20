"""
End-to-end RAG pipeline test.

Tests: document loading, chunking comparison, vector store, hybrid search,
reranking, and LLM generation with real Groq API.

Usage:
  conda activate nexus-ai
  cd backend
  GROQ_API_KEY=gsk_... python test_pipeline.py
"""

import os
import sys
import time
sys.path.insert(0, ".")


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def test_loading():
    separator("STAGE 1: Document Loading")
    from app.rag.ingestion.loader import load_file

    docs = load_file("sample_docs/company_policy.txt")
    print(f"  Loaded {len(docs)} document(s)")
    print(f"  Total chars: {sum(len(d.text) for d in docs)}")
    print(f"  Preview: {docs[0].text[:120]}...")
    print(f"  Metadata: {docs[0].metadata}")
    return docs


def test_chunking(docs):
    separator("STAGE 2: Chunking Strategy Comparison")
    from app.rag.ingestion.chunker import chunk_documents

    strategies = ["fixed", "recursive"]
    for strategy in strategies:
        chunks = chunk_documents(docs, strategy=strategy, chunk_size=500, chunk_overlap=100)
        avg_len = sum(len(c.text) for c in chunks) / len(chunks)
        print(f"\n  [{strategy.upper()}]")
        print(f"    Total chunks  : {len(chunks)}")
        print(f"    Avg chunk size: {avg_len:.0f} chars")
        print(f"    Sample chunk  : {chunks[0].text[:100]}...")

    # Use recursive for the rest of the test
    chunks = chunk_documents(docs, strategy="recursive", chunk_size=800, chunk_overlap=150)
    print(f"\n  Using recursive strategy: {len(chunks)} chunks")
    return chunks


def test_embeddings(chunks):
    separator("STAGE 3: Embedding")
    from app.rag.embeddings.embedder import HuggingFaceEmbedder

    embedder = HuggingFaceEmbedder("all-MiniLM-L6-v2")
    texts = [c.text for c in chunks]

    t0 = time.time()
    embeddings = embedder.embed_batch(texts)
    elapsed = time.time() - t0

    print(f"  Embedded {len(embeddings)} chunks in {elapsed:.2f}s")
    print(f"  Embedding dim  : {len(embeddings[0])}")
    print(f"  Speed          : {len(embeddings)/elapsed:.0f} chunks/sec")
    return embedder, embeddings


def test_vector_store(chunks, embeddings):
    separator("STAGE 4: Vector Store (ChromaDB)")
    from app.rag.retrieval.vector_store import VectorStore

    store = VectorStore(
        collection_name="nexus_test",
        persist_path="./chroma_data",
        use_embedded=True,
    )

    doc_id = "company_policy_v1"
    # Clean up from previous runs
    store.delete_document(doc_id)

    n = store.upsert_chunks(chunks, embeddings, document_id=doc_id)
    print(f"  Stored {n} chunks")
    print(f"  Total in collection: {store.count}")
    return store


def test_retrieval(store, embedder):
    separator("STAGE 5: Retrieval + Hybrid Search")
    from app.rag.retrieval.hybrid_search import BM25Index, reciprocal_rank_fusion

    query = "How many vacation days do employees get?"
    print(f"  Query: '{query}'")

    # Dense retrieval
    q_vec = embedder.embed_text(query)
    dense_results = store.search(q_vec, top_k=5)

    print(f"\n  [Dense / Semantic] Top 3:")
    for r in dense_results[:3]:
        print(f"    Score {r.score:.4f}: {r.text[:80]}...")

    # Build BM25 and do hybrid
    all_data = store._collection.get(include=["documents", "metadatas"])
    bm25 = BM25Index()
    bm25.build(all_data["documents"], all_data["ids"], all_data["metadatas"])
    sparse_results = bm25.search(query, top_k=5)

    print(f"\n  [Sparse / BM25] Top 3:")
    for r in sparse_results[:3]:
        print(f"    Score {r.score:.4f}: {r.text[:80]}...")

    fused = reciprocal_rank_fusion(dense_results, sparse_results)
    print(f"\n  [Hybrid / RRF merged] Top 3:")
    for r in fused[:3]:
        print(f"    Score {r.score:.4f}: {r.text[:80]}...")

    return fused


def test_reranking(query, results):
    separator("STAGE 6: Cross-Encoder Reranking")
    from app.rag.retrieval.reranker import CrossEncoderReranker

    print("  Loading cross-encoder model...")
    reranker = CrossEncoderReranker()
    reranked = reranker.rerank(query, results, top_k=3)

    print(f"  Reranked top 3:")
    for r in reranked:
        print(f"    Score {r.score:.4f}: {r.text[:80]}...")
    return reranked


def test_generation(query, results, api_key):
    separator("STAGE 7: LLM Generation (Groq)")
    from app.rag.generation.generator import GroqGenerator

    gen = GroqGenerator(api_key=api_key, model="llama-3.3-70b-versatile")
    result = gen.generate(query=query, context_results=results)

    print(f"  Answer:\n")
    print(f"  {result.answer}\n")
    print(f"  Sources: {[s['source'] for s in result.sources]}")
    print(f"  Tokens : {result.prompt_tokens} prompt + {result.completion_tokens} completion")
    return result


def main():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("ERROR: Set GROQ_API_KEY environment variable")
        print("  export GROQ_API_KEY=gsk_...")
        sys.exit(1)

    print("\n" + "="*60)
    print("  NEXUS AI — End-to-End RAG Pipeline Test")
    print("="*60)

    docs = test_loading()
    chunks = test_chunking(docs)
    embedder, embeddings = test_embeddings(chunks)
    store = test_vector_store(chunks, embeddings)

    query = "How many vacation days do employees get per year?"
    fused_results = test_retrieval(store, embedder)
    reranked = test_reranking(query, fused_results)
    test_generation(query, reranked, api_key)

    print("\n" + "="*60)
    print("  ALL STAGES PASSED")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
