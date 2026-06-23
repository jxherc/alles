# stage 3f - semantic skill discovery + feedback - audit findings (2026-06-23)

## current state
- `skills_store.match_skills` ranks skills by TOKEN OVERLAP (Jaccard on name/description/when_to_use)
  with a small boost for used/pinned skills. it misses semantic matches: a request "tidy up my prose"
  won't surface a skill described as "copy editor" because no words overlap.
- the embedding infra exists + is already used elsewhere: `memory_store._embed` (fastembed) + `_cosine`
  (textindex search uses them). skills don't use it.
- the usage sidecar (`_usage.json`: {slug: {uses, last_used, pinned}}) tracks that a skill was LOADED,
  but there is NO "did this skill actually help?" signal - a loaded-but-useless skill ranks the same as
  a loaded-and-great one.

## the gap
- rank skills by cosine similarity of embed(request) vs embed(skill text), falling back to the token
  overlap when embeddings aren't available (fastembed missing).
- record explicit helpful/unhelpful feedback per skill + fold a bounded learned weight into the rank
  (mirrors the 1a proactive feedback loop).

## fix - extend `services/skills_store.py`
- `record_feedback(slug, helpful)` -> bump `helped`/`missed` in the usage sidecar.
- `_feedback_weight(row)` -> 0.5..1.5 bounded multiplier from helped vs missed (cold start = 1.0).
- `match_skills_semantic(query, top_k, *, embed_fn=None)` -> cosine rank (embed_fn injectable for tests),
  folding in the feedback weight + pinned boost; falls back to `match_skills` when embeddings are None.
- route POST /api/skills/{slug}/feedback {helpful}.

tested: feedback bump + persistence, weight cold-start/all-helped/all-missed/bounds, semantic cosine
rank, feedback reorders within bound, embedding-None fallback, empty + top_k.
