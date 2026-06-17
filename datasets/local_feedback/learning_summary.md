# Local Feedback Learning Summary

Dataset: `D:\autosub_zh\datasets\local_feedback`

## Counts

- Bilibili feedback records: 0
- Bilibili learning records: 0
- Bilibili eval-marked records: 0
- Translation edit records: 0
- Translation style-learning records: 0
- Translation eval-marked records: 0

## Guardrails

- Small sample counts are not suitable for deep-learning fine-tuning.
- High-quality labels and a stable gold set come before model training.
- Bilibili duplicate search is primarily retrieval and ranking; start with query hints, lexical/semantic features, reranking, and active learning.
- Current subtitle style learning is prompt/RAG-like; keep expanding reusable datasets before training.
- Automatic learning must remain explainable, switchable, and reversible.
- Learning samples and eval samples must stay separate.
