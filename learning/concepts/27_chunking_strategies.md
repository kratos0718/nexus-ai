# Chunking Strategies — The Foundation of RAG Quality

## Why chunking is the most underestimated RAG component

Before any retrieval, embedding, or generation happens, your documents must be split into chunks. The chunking strategy determines:
- What text the embedding model "sees" for each vector
- How much context gets passed to the LLM per retrieved chunk
- Whether a retrieved chunk contains the complete answer or just a fragment
- How many chunks are needed to cover a document (affects cost and speed)

A badly chunked document cannot be rescued by a better embedding model, retrieval algorithm, or LLM. The information either is or isn't in the chunk. Chunking is upstream of everything.

---

## Level 1: What chunking actually does

A document is a long string of text. A vector embedding model has a maximum input length (token limit). ChromaDB stores individual embeddings. The retrieval step returns individual chunks, not the whole document.

This means:
1. Documents must be split before embedding
2. Each chunk gets its own vector in the vector store
3. Retrieval returns chunks, not documents
4. The LLM sees only the retrieved chunks (not the full document)

The chunking decision answers: "What is the right unit of information?"

Too small (50 chars): each chunk is a sentence fragment — retrieval finds it but the LLM gets no context
Too large (10,000 chars): few chunks, each packed with information — retrieval is imprecise, embedding averages across too many topics
Just right: each chunk is a self-contained unit of meaning — can be understood in isolation

---

## Level 2: Fixed-size chunking

Split text every N characters with M characters of overlap.

```python
def _fixed_split(text: str, size: int, overlap: int) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += size - overlap
    return chunks
```

**Example** (size=20, overlap=5):
```
Text: "The cat sat on a mat. The dog ran away."
Chunk 1: "The cat sat on a ma"
Chunk 2: "n a mat. The dog ra"  ← starts mid-sentence
Chunk 3: "og ran away."
```

**Overlap** solves the boundary problem partially: the same words appear in adjacent chunks, so a sentence split across chunk boundaries can still be retrieved.

**Problems:**
- Splits mid-sentence, mid-word, mid-paragraph — chunks lose syntactic coherence
- The embedding model encodes a fragment that has no standalone meaning
- Questions about topics that span a sentence boundary may retrieve neither chunk well

**When to use:** Baseline benchmarking, uniformity requirements (all chunks must be exactly N tokens for batch processing), very noisy text where structural boundaries don't exist.

---

## Level 3: Recursive character chunking

Split at natural text boundaries, falling through to smaller boundaries when the chunk is still too large.

```python
def _recursive_split(text, size, overlap):
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""],  # priority order
    )
    return splitter.split_text(text)
```

**Algorithm:**
1. Try to split on `"\n\n"` (paragraph boundary) — if any resulting chunk is still > `chunk_size`, recurse
2. Try `"\n"` (line break)
3. Try `". "` (sentence ending)
4. Try `" "` (word boundary)
5. Fall back to character-level split

**Why this is the default:** It respects document structure. Most documents are written with logical units separated by paragraph breaks. Splitting on `"\n\n"` gives chunks that correspond to what the author intended as a logical block.

**Example** (chunk_size=100, overlap=20):
```
Text:
"# Introduction\n\nThe retrieval step finds relevant chunks.\n\nThe generation step produces the answer."

Chunks:
["# Introduction\n\nThe retrieval step finds relevant chunks.", 
 "chunks.\n\nThe generation step produces the answer."]
```

**Overlap semantics:** In recursive chunking, overlap ensures that the last N characters of chunk K appear at the start of chunk K+1. Useful for questions whose answers straddle a split point.

**Ideal chunk size for RAG:**
- 512–1000 characters (roughly 100–250 words)
- Enough to hold a complete paragraph of reasoning
- Small enough that the embedding is specific to one topic

---

## Level 4: Semantic chunking (embedding-based boundary detection)

Split at topic boundaries detected by drops in embedding similarity between consecutive sentences.

```python
def _semantic_split(text: str, max_chunk_size: int, embedder) -> List[str]:
    import numpy as np

    # Step 1: split into sentences
    sentences = _split_sentences(text)   # regex: split on [.!?] followed by space

    # Step 2: embed all sentences (batch for efficiency)
    embeddings = embedder.embed_batch(sentences)

    # Step 3: cosine similarity between consecutive sentences
    similarities = []
    for i in range(len(embeddings) - 1):
        a, b = np.array(embeddings[i]), np.array(embeddings[i + 1])
        sim = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10))
        similarities.append(sim)

    # Step 4: split threshold = mean - 0.5*std
    threshold = np.mean(similarities) - 0.5 * np.std(similarities)

    # Step 5: group sentences into chunks
    chunks, current = [], [sentences[0]]
    for i, sim in enumerate(similarities):
        next_sent = sentences[i + 1]
        if sim < threshold or len(" ".join(current)) + len(next_sent) > max_chunk_size:
            chunks.append(" ".join(current))
            current = [next_sent]
        else:
            current.append(next_sent)
    if current:
        chunks.append(" ".join(current))
    return chunks
```

**How it works:**
- Consecutive sentences in the same paragraph have HIGH cosine similarity (same topic)
- Sentences from different topics have LOW cosine similarity (topic shift)
- A similarity drop below `mean - 0.5*std` signals a topic boundary → split there

**Example:**
```
"Embeddings are dense vectors that represent semantic meaning.
 They are generated by transformer models.
 FastAPI is a Python web framework.    ← low similarity with previous sentence
 It uses Pydantic for validation."

→ Split after "transformer models." because similarity drops sharply
→ Chunk 1: "Embeddings are dense vectors... generated by transformer models."
→ Chunk 2: "FastAPI is a Python web framework. It uses Pydantic for validation."
```

**Advantages:**
- Chunks correspond to actual topics, not arbitrary character counts
- Embedding of chunk is specific to one topic → better retrieval precision
- Works even when document has no paragraph breaks (transcripts, raw text)

**Disadvantages:**
- Requires embedding ALL sentences first (expensive for large documents)
- Indexing is slower (2-5× more compute than recursive chunking)
- Requires an embedder available at indexing time (always true for our system)

**When to use:**
- Raw text without structure (OCR output, transcripts, scraped text)
- Technical documents where topics shift within paragraphs
- When retrieval precision is more important than indexing speed

---

## Level 5: Chunk size trade-offs — the retrieval-generation tension

There is a fundamental tension in choosing chunk size:

**Small chunks (50–200 chars):**
- ✅ Precise retrieval — embedding is specific to one exact fact
- ✅ High recall — small topic coverage means better match probability
- ❌ Context loss — LLM receives a sentence fragment without surrounding explanation
- ❌ More chunks — slower retrieval, more ChromaDB storage

**Large chunks (2000–5000 chars):**
- ✅ Rich context — LLM receives full paragraphs, complete explanations
- ✅ Fewer chunks — faster retrieval, less storage
- ❌ Embedding dilution — vector represents many topics; retrieval is imprecise
- ❌ Context window pressure — passing 5 large chunks may exceed LLM context limit

**The sweet spot (800–1200 chars):**
- Embedding is specific enough for good retrieval
- Content is rich enough for good generation
- 5–10 chunks fit comfortably in Llama 3.3's 128K context

**Chunk overlap role:**
Overlap of 10–20% prevents information loss at split boundaries. Without overlap, a question whose answer spans two chunks (sentence A at end of chunk 1, sentence B at start of chunk 2) may retrieve neither chunk at high rank.

---

## Level 6: Advanced patterns (concepts)

### Parent-child retrieval (small-to-big)

Index small chunks (256 chars) for precise embedding match. When a small chunk is retrieved, return its parent chunk (1024 chars) to the LLM for rich context.

```
Document → parent chunks (1024 chars) → child chunks (256 chars)
                                            ↓
                              Child embeddings stored in vector DB
                                            ↓
Retrieval → find matching child chunk → look up parent chunk → pass parent to LLM
```

**Why it works:** Small chunks embed precisely. Large chunks provide context. You get the precision of small chunks and the context of large chunks simultaneously.

**Implementation:** Store parent_chunk_id in child chunk metadata. After retrieval, replace child text with parent text before generation.

### Sentence-window retrieval

Similar to parent-child. Index individual sentences. When retrieved, expand to a window of ±2 sentences around the match.

```
"Embeddings represent meaning. [MATCH] They capture semantic similarity. Use them for search."
                               ↑ retrieved sentence
→ Return window: "Embeddings represent meaning. They capture semantic similarity. Use them for search."
```

### Proposition-based chunking

Instead of splitting at boundaries, use an LLM to extract self-contained propositions from the document:

```
Input: "RAG was introduced in 2020. It combines retrieval with generation."
Propositions:
  - "RAG stands for Retrieval-Augmented Generation"
  - "RAG was introduced in 2020"
  - "RAG combines retrieval with generation"
```

Each proposition is a complete, standalone claim. Extremely precise retrieval. Very expensive (requires LLM call per document).

---

## Level 7: How Nexus AI uses chunking

**Default:** `recursive` — good for structured documents (PDFs, Markdown, DOCX)

**Semantic:** Best for raw or unstructured text — the embedder detects where topics change and splits there. More compute but better chunk coherence.

**Fixed:** Use for benchmarking or when you need predictable chunk counts.

**User control:** The upload form lets you choose strategy per document:
```
POST /documents/upload
Content-Type: multipart/form-data

file: <document>
chunking_strategy: semantic  ← controls which strategy is used for this document
```

The strategy is logged in chunk metadata (`"strategy": "semantic"`) and visible in the Knowledge Base Explorer. This lets you compare chunk quality visually for the same document indexed with different strategies.

---

## Quick reference

| Strategy | Splits on | Cost | Best for |
|----------|-----------|------|----------|
| Fixed | Character count | Lowest | Baselines, uniform processing |
| Recursive | Paragraph → sentence → word | Low | Structured documents (default) |
| Semantic | Embedding similarity drops | High (embeds all sentences) | Unstructured text, topic-dense docs |
| Parent-child | Two levels (small + large) | Medium | Precision + context simultaneously |
| Sentence-window | Sentence boundaries + expansion | Low | Dense factual text |
| Proposition | LLM extraction | Very high | Maximum precision, offline indexing |

---

## Interview Q&A

**Q: What is chunking in RAG and why does it matter?**
A: Chunking splits documents into smaller pieces before embedding and storing in the vector database. It matters because each chunk gets one embedding vector, and retrieval returns chunks (not documents). The chunking strategy determines whether retrieved chunks contain complete, coherent information. Bad chunking (mid-sentence splits, wrong size) cannot be compensated by better embedding models or retrieval algorithms — the information is either in the chunk or it isn't.

**Q: What is recursive character chunking and why is it the standard?**
A: Recursive chunking tries to split at natural boundaries in priority order: paragraph breaks (`\n\n`), then line breaks (`\n`), then sentence endings (`". "`), then words (`" "`), falling back to characters only if needed. It's the standard because it respects document structure — paragraphs are usually logical units the author intended as a single idea. The LangChain `RecursiveCharacterTextSplitter` is the canonical implementation.

**Q: What is semantic chunking and how does it work?**
A: Split at topic boundaries detected by drops in embedding similarity. First, split the document into sentences. Embed all sentences. Compute cosine similarity between consecutive sentence pairs. Similarities below `mean - 0.5*std` indicate a topic shift — split there. Sentences in the same topic cluster together (high similarity), sentences from different topics have low similarity. Produces chunks aligned with actual topic boundaries rather than arbitrary character counts.

**Q: What is the retrieval-generation tension in choosing chunk size?**
A: Small chunks embed precisely (specific topic → high retrieval recall/precision) but give the LLM little context (sentence fragments → poor generation). Large chunks give the LLM rich context but embed poorly (embedding averages across many topics → imprecise retrieval). The sweet spot is 800–1200 characters — specific enough for good retrieval, rich enough for good generation. The 10–20% overlap prevents information loss at split boundaries.

**Q: What is parent-child retrieval?**
A: Index small child chunks (256 chars) for precise embedding match, but store parent chunks (1024 chars) that each child belongs to. When a child chunk is retrieved, return the parent chunk to the LLM. This gives the precision of small-chunk retrieval with the context of large-chunk generation. Requires storing a `parent_chunk_id` in child chunk metadata and a lookup step after retrieval.

**Q: How do you choose between chunking strategies in practice?**
A: Recursive for structured documents with natural paragraph breaks (PDFs, Markdown, technical docs) — it's fast and respects structure. Semantic for unstructured or raw text (OCR output, transcripts, web scrapes) where structure is absent but topics shift within the text — more compute but better chunk coherence. Fixed only for benchmarking or when chunk count uniformity is a hard requirement. Test by uploading the same document with each strategy and comparing chunk text in the Knowledge Base Explorer.
