# Feedback Loops & RLHF — From Ratings to Fine-Tuning

## Why feedback matters

A RAG system that answers correctly 80% of the time is impressive in a demo. In production, you need to know which 20% it gets wrong, why, and how to fix it. RAGAS scores tell you aggregate quality. Feedback tells you which *specific* answers users found helpful or useless — and gives you data to make the model better.

The feedback loop is the mechanism that turns a deployed model into an improving one:

```
Deploy → Users interact → Collect ratings → Analyse failures → Fine-tune / fix pipeline → Deploy
         ↑_______________________________________________________________|
```

Without this loop, your model is static. Every production AI system that continuously improves has some version of this loop.

---

## Level 1: Types of feedback

**Explicit feedback** — the user deliberately signals quality:
- Thumbs up / thumbs down (binary preference)
- Star rating 1–5 (ordinal preference)
- Free-text comment ("this answer ignored the second half of my question")
- Edit the answer (implicit correction)

**Implicit feedback** — inferred from user behaviour without asking:
- Did the user follow up immediately? (suggests the answer was incomplete)
- Did the user copy-paste the answer? (suggests it was useful)
- Did the user rephrase and ask again? (suggests the answer was wrong)
- Session abandonment after a specific response

**Which is better?**
Explicit is cleaner (you know what it means) but suffers from low response rate — most users don't rate.
Implicit is higher volume but noisier — a user rephrasing might mean "I want more detail", not "wrong answer".

Production systems use both: explicit to train the reward model, implicit to detect regressions at scale.

---

## Level 2: RLHF — Reinforcement Learning from Human Feedback

RLHF is the technique that aligned GPT-4, Claude, and Gemini with human preferences. It has three stages:

### Stage 1: Supervised Fine-Tuning (SFT)

Train the base LLM on high-quality (prompt, response) pairs. This teaches the model the format and style of good answers.

```
Input:  "What is RAG?"
Output: "RAG (Retrieval-Augmented Generation) is a technique that..."
```

The base model (e.g. Llama) knows language. SFT teaches it to be a helpful assistant.

### Stage 2: Reward Model

A separate model that scores responses from 0 to 1 based on human preferences.

Training data: pairs of responses to the same prompt, labelled with which is better.

```
Prompt: "Explain embeddings"
Response A: "Embeddings are vectors that represent meaning..." → Score: 0.85
Response B: "It's complicated, basically numbers" → Score: 0.20
```

The reward model learns what "good" means from human comparisons, not from a fixed rubric.

### Stage 3: RL Optimisation (PPO)

Use the reward model as a signal to fine-tune the SFT model via Proximal Policy Optimisation (PPO). The model generates responses, the reward model scores them, the score is used as a reward signal to update the model weights.

```
LLM generates response
    ↓
Reward model scores it (0.0 – 1.0)
    ↓
PPO updates LLM weights to maximise reward
    ↓
Repeat for thousands of steps
```

**Problem: PPO is complex.** It requires running the LLM, the reward model, and a reference model simultaneously. Hyperparameter sensitive, slow, expensive.

---

## Level 3: DPO — Direct Preference Optimisation

DPO (2023) achieves the same alignment as RLHF but without the RL stage. It directly fine-tunes the model on preference pairs.

**Input to DPO:**
```python
{
    "prompt": "What is RAG?",
    "chosen": "RAG is a technique that augments LLMs with retrieved context...",
    "rejected": "RAG stands for retrieval thing, it fetches stuff"
}
```

DPO directly updates model weights to increase the probability of `chosen` and decrease the probability of `rejected`, relative to a reference model.

**Why DPO beat PPO for most teams:**
- No reward model needed — preference pairs are the signal
- No RL training loop — standard supervised training infrastructure
- More stable — no reward hacking, no mode collapse
- 10× cheaper to run

**DPO formula (simplified):**
The loss pushes the fine-tuned model to prefer `chosen` over `rejected` by at least a margin controlled by a temperature parameter β.

**When to use PPO vs DPO:**
- PPO: when you have a reliable, high-quality reward model and need maximal alignment
- DPO: when you have preference pairs and want a simpler, cheaper training pipeline

---

## Level 4: Preference data format

The JSONL format used for fine-tuning preference data:

```jsonl
{"messages": [{"role": "user", "content": "What is chunking?"}, {"role": "assistant", "content": "Chunking splits documents into smaller pieces..."}], "rating": 1}
{"messages": [{"role": "user", "content": "Explain embeddings"}, {"role": "assistant", "content": "Not sure, try googling it."}], "rating": -1}
```

**For DPO, you need pairs:**
```jsonl
{"prompt": "What is chunking?", "chosen": "Chunking splits...", "rejected": "I don't know."}
```

**How we get pairs from thumbs ratings:**
If user A gives answer X a 👍 and user B gets a different answer Y to the same question and gives it a 👎:
- chosen = X, rejected = Y

More commonly: use the LLM to generate multiple responses, let users rate all of them, pair the highest-rated against the lowest-rated.

**OpenAI fine-tuning format** (used in SFT, not DPO):
```jsonl
{"messages": [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": "What is RAG?"}, {"role": "assistant", "content": "RAG is..."}]}
```

Nexus AI exports in this format — each 👍 response becomes a training example.

---

## Level 5: Reward hacking

When you optimise against a reward model, the LLM eventually finds ways to maximise the score without actually being better. This is reward hacking.

**Examples:**
- Verbose answers score higher → model learns to pad with filler text
- Confident-sounding answers score higher → model learns to assert things it's uncertain about
- Flattery scores higher → model starts responses with "Great question!"

**Mitigations:**
1. **KL divergence penalty** — penalise the fine-tuned model for diverging too far from the reference model. Prevents extreme reward hacking while allowing genuine improvement.
2. **Regular reward model updates** — retrain the reward model on new data. The model can't hack a moving target.
3. **Separate evaluation** — always evaluate on held-out human raters, not the reward model itself.
4. **Diverse preference data** — if data covers many failure modes, the model can't exploit any single one.

---

## Level 6: RLAIF — Reinforcement Learning from AI Feedback

Instead of human raters, use another LLM as the judge.

```python
# Instead of humans rating responses:
judge_prompt = f"""
Rate this response on a scale of 1-10 for accuracy and helpfulness.
Question: {question}
Response: {response}
Score (1-10):
"""
score = llm.invoke(judge_prompt)
```

**Pros:** Cheaper, faster, scalable to millions of examples.
**Cons:** The judge model inherits its own biases. Susceptible to sycophancy (prefers responses that look like its own training data).

**Constitutional AI (Anthropic):** A specific RLAIF variant — the LLM critiques its own responses against a written "constitution" of principles, then revises them. The revised responses become training data.

We use RLAIF in Nexus AI's RAGAS evaluation — Groq (Llama) acts as the judge for faithfulness and relevancy scoring.

---

## Level 7: Cold start and annotation challenges

**The cold start problem:**
On day 1, you have no feedback. No feedback → can't fine-tune → model quality doesn't improve → users have no incentive to rate.

Practical solutions:
1. **Seed with synthetic data** — generate (question, good answer, bad answer) pairs using GPT-4, use them for initial SFT.
2. **Rate your own outputs** — have your team rate responses before launch.
3. **Start with implicit signals** — before adding explicit ratings, track which answers users follow up on.

**Annotation bias:**
Human raters have systematic biases:
- **Position bias**: prefer the first response shown in a pair comparison
- **Verbosity bias**: prefer longer responses even when shorter is better
- **Sycophancy**: prefer responses that agree with them
- **Domain bias**: non-experts can't distinguish correct from confident-sounding wrong

Mitigations:
- Randomise response order in A/B comparisons
- Use multiple raters per example, take majority vote
- Include calibration examples with known correct answers to catch unreliable raters

---

## Level 8: The Nexus AI feedback system

What we built in Day 18:

```
User sends question
    ↓
AI generates answer (via RAG or agent)
    ↓
User sees 👍 / 👎 buttons below the answer
    ↓
Click → POST /feedback { question, answer, rating: 1/-1, conversation_id, retrieval_mode }
    ↓
Stored in message_feedback table (PostgreSQL)
    ↓
GET /feedback/stats → positive_rate displayed in Observability dashboard
    ↓
GET /feedback/export → download as JSONL (one record per rating)
```

**What we can do with the exported data:**
1. **SFT training data**: filter `rating == 1` → (question, answer) pairs → fine-tune Llama via Axolotl or Unsloth
2. **DPO training data**: pair `rating == 1` with `rating == -1` for the same question → (prompt, chosen, rejected) → run DPO
3. **Pipeline debugging**: filter `rating == -1` → analyse which documents / retrieval modes produce bad answers → fix retrieval, not model

**Why we store `retrieval_mode`:**
If HyDE mode consistently gets 👎 but standard mode gets 👍 for the same questions, the problem is HyDE, not the LLM. The feedback system makes this visible.

---

## Quick reference

| Term | What it is |
|------|------------|
| RLHF | 3-stage alignment: SFT → reward model → PPO optimisation |
| SFT | Fine-tune base model on (prompt, response) pairs |
| Reward model | Separate model trained to score response quality |
| PPO | RL algorithm used to optimise LLM against reward signal |
| DPO | Direct preference optimisation — no RL, trains on pairs directly |
| RLAIF | Use LLM as judge instead of humans |
| Preference data | (prompt, chosen, rejected) triples for DPO |
| Reward hacking | Model maximises score via shortcuts, not genuine quality |
| KL divergence penalty | Prevents model from drifting too far from reference during RL |
| Constitutional AI | Anthropic's RLAIF — LLM critiques itself against written principles |

---

## Interview Q&A

**Q: What is RLHF and why is it used?**
A: Reinforcement Learning from Human Feedback — a three-stage technique to align LLMs with human preferences: first supervised fine-tuning on high-quality examples, then training a reward model on human preference pairs, then using PPO to optimise the LLM to maximise the reward model's score. Used because training loss on next-token prediction doesn't capture "is this a good, safe, helpful answer?" — only humans can define that.

**Q: What is DPO and how does it differ from RLHF?**
A: DPO (Direct Preference Optimisation) achieves the same alignment goal as RLHF but eliminates the RL stage. It directly fine-tunes the model on (prompt, chosen, rejected) preference pairs, increasing the probability of chosen relative to rejected. Simpler, more stable, and 10× cheaper than PPO-based RLHF. Most teams in 2024 use DPO over PPO.

**Q: What is preference data?**
A: Paired examples where for the same prompt, you have a response humans preferred (chosen) and one they didn't (rejected). Used to train reward models (RLHF) or directly as DPO training data. Collected via A/B response comparisons or aggregated thumbs-up/down ratings on the same question.

**Q: What is reward hacking?**
A: When the LLM discovers a pattern that scores high on the reward model without actually being better — for example, verbose filler text, false confidence, or flattery. Mitigated with KL divergence penalties (stay close to reference model), diverse preference data, and evaluating on held-out human raters rather than the reward model.

**Q: What format does fine-tuning data use?**
A: OpenAI SFT format is newline-delimited JSON (JSONL) where each line has a `messages` array with role/content objects: `{"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}`. DPO format adds `chosen` and `rejected` fields at the top level. Nexus exports in SFT format — 👍 answers become training examples.

**Q: What is RLAIF?**
A: Reinforcement Learning from AI Feedback — using an LLM as the judge instead of human raters. Cheaper and faster, but inherits the judge model's biases. Anthropic's Constitutional AI is a prominent RLAIF variant where the model critiques itself against written principles. Used in Nexus's RAGAS evaluation — Groq/Llama acts as judge for faithfulness scoring.

**Q: How do you solve the cold start problem in a feedback system?**
A: Three approaches: seed with synthetic preference data generated by GPT-4, have the team manually rate initial responses before launch, or start with implicit signals (session abandonment, follow-up questions) before adding explicit ratings. The goal is to have some signal to fine-tune before real users provide feedback.

**Q: What is annotation bias?**
A: Systematic errors in human ratings — position bias (prefer first response in a pair), verbosity bias (prefer longer responses), sycophancy (prefer responses that agree with them). Mitigated by randomising response order, using multiple raters with majority vote, and including calibration examples with known-correct answers to identify unreliable raters.
