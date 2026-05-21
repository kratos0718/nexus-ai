# Day 18 — User Feedback System & Fine-Tuning Data Export

## What we built

A complete feedback loop: thumbs up/down buttons on every AI response, preference data stored in PostgreSQL, aggregate stats in the Observability dashboard, and a JSONL export endpoint that produces fine-tuning-ready data in OpenAI format.

---

## Files created / modified

| File | Change |
|------|--------|
| `backend/app/models/feedback.py` | NEW: MessageFeedback ORM model |
| `backend/app/schemas/feedback.py` | NEW: FeedbackCreate, FeedbackResponse, FeedbackStats |
| `backend/app/api/v1/endpoints/feedback.py` | NEW: POST /feedback, GET /feedback/stats, GET /feedback/export |
| `backend/app/models/__init__.py` | Added MessageFeedback import |
| `backend/app/api/v1/router.py` | Registered feedback router at /feedback |
| `frontend/src/app/(app)/chat/page.tsx` | Added FeedbackButtons component + ratings state |
| `frontend/src/app/(app)/observability/page.tsx` | Added feedback stats section + export button |
| `learning/concepts/26_feedback_loops.md` | 8-level concept guide |

---

## The feedback data model

```python
class MessageFeedback(Base):
    __tablename__ = "message_feedback"
    id              # primary key
    user_id         # FK → users.id (multi-tenant isolation)
    conversation_id # FK → conversations (optional — for context)
    question        # the user's question (capped 2000 chars)
    answer          # the AI's answer (capped 5000 chars)
    rating          # 1 = positive, -1 = negative (binary)
    comment         # optional free-text (future: comments UI)
    retrieval_mode  # which retrieval mode produced this answer
    created_at
```

**Why binary rating (not 1–5)?**
Binary is easier to collect (one click vs multi-step), has higher response rate, and is sufficient for DPO training which only needs (chosen, rejected) pairs. 1–5 ratings add annotation complexity without proportional benefit for training.

**Why store `retrieval_mode`?**
If HyDE consistently gets 👎, the problem is the retrieval strategy, not the LLM. Storing the mode lets you cross-reference feedback with the observability dashboard to pinpoint which pipeline component is failing.

---

## API endpoints

```
POST /api/v1/feedback/          → submit rating
GET  /api/v1/feedback/stats     → { total, positive, negative, positive_rate }
GET  /api/v1/feedback/export    → download JSONL (fine-tuning format)
```

**Export format (one line per rating):**
```jsonl
{"messages": [{"role": "user", "content": "What is RAG?"}, {"role": "assistant", "content": "RAG is..."}], "rating": 1, "retrieval_mode": "standard"}
```

Each line is a complete JSON object (NDJSON format). Filter `rating == 1` to get 👍 responses as SFT training data. Pair 👍 and 👎 answers to the same question for DPO.

---

## Frontend: thumbs buttons

The `FeedbackButtons` component renders below every completed AI message (not streaming, not user messages):

```tsx
// Only appears when:
// 1. message.role === "assistant"
// 2. !message.streaming (fully rendered)
// 3. questionMap[msg.id] exists (from current session)

onRate={
  msg.role === "assistant" && questionMap[msg.id]
    ? (r) => rateMessage(msg.id, msg.content, r)
    : undefined
}
```

**Why only current-session messages?**
When loading old conversations, we don't have the question-answer mapping in component state. This avoids submitting ratings with empty question fields. A future improvement could reconstruct the map from the loaded conversation history.

**Rating state:**
```tsx
const [ratings, setRatings] = useState<Record<string, 1 | -1>>({});
```
After rating, the clicked button fills in and the other dims. The state is session-local — ratings don't persist across page refreshes (they're in PostgreSQL, not in the UI).

**Silent failure:**
The API call in `rateMessage` has a try/catch that swallows errors silently. Ratings are low-stakes — if the API is down, the user shouldn't see an error and the UI still shows the filled icon. The rating is just lost.

---

## Observability dashboard additions

Three new stat cards (only shown when feedback data is available):
1. **Ratings collected** — total count of thumbs ratings
2. **Positive rate** — percentage of 👍, shown in accent colour when ≥70%
3. **Fine-tuning pairs** — same count with reminder that export button is available

**Export button** (shown only when `total > 0`):
The export hits a protected endpoint, so it can't be a plain `<a href>`. Instead it uses `fetch` with the JWT token, gets the blob, creates an object URL, and programmatically clicks a temporary link. This is the standard pattern for downloading files from auth-protected endpoints in a browser.

---

## What you can do with the exported data

**Step 1 — SFT data (immediate):**
```bash
# Filter positively-rated responses
cat feedback_export.jsonl | python -c "
import sys, json
for line in sys.stdin:
    row = json.loads(line)
    if row['rating'] == 1:
        print(json.dumps({'messages': row['messages']}))
" > sft_data.jsonl
```

**Step 2 — DPO pairs (when you have enough data):**
For questions that received both 👍 and 👎, pair them as (chosen, rejected):
```python
from collections import defaultdict
by_question = defaultdict(lambda: {"chosen": [], "rejected": []})
for row in data:
    key = "chosen" if row["rating"] == 1 else "rejected"
    by_question[row["messages"][0]["content"]][key].append(row["messages"][1]["content"])

# Pair best positive with worst negative per question
dpo_data = [
    {"prompt": q, "chosen": v["chosen"][0], "rejected": v["rejected"][0]}
    for q, v in by_question.items()
    if v["chosen"] and v["rejected"]
]
```

**Step 3 — Fine-tune with Axolotl / Unsloth:**
Axolotl and Unsloth are popular libraries for efficient fine-tuning of Llama and Mistral on consumer GPUs. Pass `sft_data.jsonl` directly.

---

## Connection to RAGAS evaluation

Day 13 gave us automated quality metrics (RAGAS Faithfulness: 0.91).
Day 18 gives us human quality signals (positive rate: X%).

These are complementary:
- RAGAS: objective, fast, catches factual errors and context mismatches
- Feedback: subjective, captures "was this useful?" which RAGAS can't measure

When RAGAS is high but positive rate is low: the answers are factually grounded but users find them unhelpful (too verbose, wrong tone, missing the point of the question).

When RAGAS is low but positive rate is high: users like the answers but they're drifting from the source documents (hallucination risk).
