# Concept: Chunking Strategies

---

## The Real-Life Analogy

You're making notes from a 300-page textbook to study for an exam.

**Bad approach (fixed chunking):** You copy exactly 200 words at a time.  
Sometimes a sentence gets cut in half between two note cards.  
"The refund policy states that customers can return items within... (card 1)"  
"...30 days of purchase with original receipt." (card 2)  
When you search for "refund policy," card 1 seems relevant but card 2 has the answer.

**Good approach (recursive chunking):** You copy complete paragraphs.  
When a paragraph is too long, split at a sentence boundary — never mid-sentence.  
Each note card is a complete, self-contained idea.  
When you search for "refund policy," you find the whole answer on one card.

**Best approach (semantic chunking):** You split only when the topic changes.  
All sentences about refunds stay together, even across paragraph breaks.  
All sentences about shipping stay together in a separate card.  
Maximum coherence per card.

---

## The Three Strategies

### Strategy 1: Fixed Size Chunking

```python
def _fixed_split(text, size=500, overlap=100):
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + size])
        start += size - overlap   # overlap = shared text between chunks
    return chunks
```

**What it does:** Cuts text every N characters regardless of content.  
**Problem:** Cuts mid-sentence, mid-word even.  
**When to use:** Uniform structured data, quick baselines.  

Real numbers from our test:
- Document: 3852 chars
- Fixed (size=500, overlap=100): **10 chunks**, avg 475 chars
- Some chunks started mid-sentence

---

### Strategy 2: Recursive Character Splitting

```python
separators = ["\n\n", "\n", ". ", " ", ""]
# Try largest separators first; fall back to smaller ones
```

LangChain's `RecursiveCharacterTextSplitter` tries each separator in order:  
1. Split at double newline (paragraph boundary) — most natural
2. If still too big, split at single newline
3. If still too big, split at ". " (sentence end)
4. If still too big, split at space (word boundary)
5. Last resort: split at character

**Result:** Each chunk ends at a natural language boundary.  
**This is the default for most RAG systems — including ours.**

Real numbers from our test:
- Recursive (size=500, overlap=100): **11 chunks**, avg 356 chars
- Every chunk ends at a complete sentence or paragraph

---

### Strategy 3: Semantic Chunking

```python
# Embed every sentence
# Compute cosine similarity between consecutive sentences
# Split where similarity drops sharply (topic change)

threshold = mean_similarity - 0.5 * std_similarity
if consecutive_similarity < threshold:
    START_NEW_CHUNK()
```

**What it does:** Detects where the topic changes by measuring  
if consecutive sentences are semantically distant.

Example:
```
"Employees get 20 vacation days." ─────────┐ similarity = 0.91 (same topic)
"Unused days carry forward up to 5."       │ → STAY TOGETHER
"Sick leave is 12 days per year." ──────────┘ similarity = 0.51 (topic shift!)
                                            → SPLIT HERE
"A medical certificate is required..."     ─ new chunk starts
```

**Cost:** Embeds every sentence during indexing → 10-50x slower index build.  
**Quality:** Best chunk coherence → better retrieval.  
**When to use:** Long documents with clear section changes, offline indexing jobs.

---

## The Overlap Parameter

```
WITHOUT overlap (overlap=0):
  Chunk 1: "...vacation policy: 20 days per year."
  Chunk 2: "Sick leave is 12 days per year..."
  Query: "how many days off total?"
  → Chunk 1 retrieved, but what about sick leave? Missed.

WITH overlap (overlap=150 chars):
  Chunk 1: "...vacation policy: 20 days per year. Sick leave is 12 days..."
  Chunk 2: "Sick leave is 12 days per year. A medical certificate..."
  Query: "how many days off total?"
  → Chunk 1 retrieved with both pieces of information
```

**Trade-off:** Overlap increases storage (by ~15-20%) but prevents  
information loss at chunk boundaries. Always use overlap in production.

---

## Chunking Parameters — How to Choose

| Document Type | Chunk Size | Overlap | Strategy |
|--------------|------------|---------|----------|
| Legal documents | 800–1200 | 200 | recursive |
| FAQ pages | 200–400 | 50 | recursive |
| Research papers | 1000–1500 | 300 | semantic |
| Code documentation | 500–800 | 100 | recursive |
| News articles | 300–600 | 100 | recursive |
| Chat transcripts | 200–300 | 50 | fixed |

**Rule of thumb:** Chunk size ≈ the amount of text that answers ONE question.  
Too small → loses context. Too large → retrieves noise.

---

## What Happened in Our Project

```
Document: company_policy.txt (3852 chars, 5 sections)

Fixed  (500, overlap=100): 10 chunks — some cut mid-paragraph
Recursive (500, overlap=100): 11 chunks — cleaner boundaries
Recursive (800, overlap=150): 6 chunks — used for pipeline test

Retrieval result with 6 chunks:
  Query "vacation days" → correctly retrieved Section 1 (Annual Leave)
  Cross-encoder confirmed: score 3.17 (relevant) vs -4.42 (not relevant)
```

---

## Interview Questions

**Q: Why not just embed the entire document as one vector?**  
A: Embedding an entire document averages all its content into one vector. A query about "vacation days" won't precisely match a vector that also encodes information about gratuity, sick leave, WFH policy, and everything else in the document. Chunking creates focused embeddings where each vector represents ONE idea. This is why retrieval works — the query vector closely matches the vacation-days chunk vector, not the whole-document vector.

**Q: What chunk size would you use for a production system?**  
A: I'd start with 800–1000 characters with 150–200 overlap using recursive splitting — that typically fits one to three paragraphs, which is enough to answer most questions without excess noise. Then I'd evaluate with RAGAS metrics: if Context Precision is low (retrieving noise), reduce chunk size. If Context Recall is low (missing answers), increase chunk size or overlap. Chunk size is one of the most impactful hyperparameters in a RAG system.

**Q: What is the difference between recursive chunking and semantic chunking?**  
A: Recursive chunking splits based on text structure (paragraph/sentence/word boundaries) using predefined separator characters. It's fast, deterministic, and doesn't require a model. Semantic chunking splits based on meaning — it embeds consecutive sentences and splits where embedding similarity drops sharply, detecting actual topic changes. Semantic chunking produces more coherent chunks but requires embedding every sentence during indexing, making it 10-50x slower. For most production use cases, recursive chunking is the right default; semantic chunking is worth the cost for long, multi-topic documents.

---

## Resume Bullets

```
• Implemented three chunking strategies (fixed, recursive, semantic) with configurable
  size and overlap parameters; selected RecursiveCharacterTextSplitter as production
  default preserving paragraph and sentence boundaries

• Tuned chunk parameters (800 chars, 150 overlap) using RAGAS Context Precision/Recall
  metrics, balancing retrieval specificity against context completeness

• Built semantic chunking using consecutive sentence embedding similarity to detect
  topic boundaries, improving chunk coherence for multi-section documents
```
