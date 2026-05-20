"""
Embedding verification script.

Demonstrates semantic similarity using all-MiniLM-L6-v2.

Usage:
  conda activate nexus-ai
  cd backend
  python test_embeddings.py
"""

import sys
sys.path.insert(0, ".")

from app.rag.embeddings.embedder import HuggingFaceEmbedder


def main():
    print("\n" + "="*60)
    print("  Nexus AI — Embedding Verification")
    print("="*60)

    print("\n[1] Loading model: all-MiniLM-L6-v2")
    embedder = HuggingFaceEmbedder("all-MiniLM-L6-v2")
    print(f"    Loaded. Output dimension: {embedder.dimension}")

    sentences = [
        "The dog ran across the park",
        "A puppy sprinted through the garden",
        "Machine learning is a subset of AI",
        "Deep learning uses neural networks",
        "I love eating pizza on weekends",
    ]

    print("\n[2] Embedding 5 test sentences...")
    embeddings = embedder.embed_batch(sentences)
    print(f"    Shape: {len(embeddings)} x {len(embeddings[0])}")

    print(f"\n[3] First 8 values for sentence 0:")
    print(f"    {[round(x, 4) for x in embeddings[0][:8]]} ...")

    print("\n[4] Cosine Similarity Results:")
    print("-" * 55)

    pairs = [
        (0, 1, "dog vs puppy            (expect: HIGH)"),
        (2, 3, "ML vs deep learning     (expect: HIGH)"),
        (0, 4, "dog vs pizza            (expect: LOW) "),
        (0, 2, "dog vs ML               (expect: LOW) "),
    ]

    for i, j, label in pairs:
        score = embedder.cosine_similarity(embeddings[i], embeddings[j])
        bar = "█" * int(score * 25)
        print(f"  {score:.4f}  {bar}")
        print(f"          {label}")

    print("\n" + "="*60 + "\n")


if __name__ == "__main__":
    main()
