"""Similarity hints: "this looks like descriptions you already categorised" (docs/08, 4.3).

How it works
* Each description STEM (the reusable words, no digits, at most four) is turned into a unit vector
  by a small local embedding model (Ollama `/api/embed`). Only stems are embedded: never
  amounts, dates, accounts or filenames. Vectors are cached per stem and model.
* The "labels" are descriptions you categorised yourself (manual choices and rules you made or
  learned from corrections), never built-in rules or earlier AI guesses. One category per stem
  (the majority; a stem you put in two categories evenly is left out).
* For an uncategorised stem, take its k nearest labelled stems. Those at least `min_similarity`
  similar vote, weighted by similarity. A suggestion needs two or more such neighbours and
  `min_agree` of the vote on one category.
* The result is only ever a HINT in Review (like a low-confidence AI guess); it is never applied.
  Its "confidence" is agreement times average similarity: a ranking, not a probability.

Whether it is good enough is measured, not assumed: `app.tools.eval_embeddings` hides each of your
labels in turn and predicts it from the rest, and the feature is off until you turn it on.
"""

import hashlib
import time
from collections import Counter, defaultdict
from dataclasses import dataclass

import httpx
import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ModelRun, StemEmbedding, Transaction
from app.services import llm_json
from app.services.categorizer import description_stem
from app.services.llm_classifier import LlmUnavailable, _model_digest

BATCH = 32
LABEL_SOURCES = ("manual", "user_rule")  # your own decisions
MIN_STEM_MAJORITY = 0.6  # a stem you filed in several categories needs a clear favourite
_IN_CHUNK = 500


@dataclass
class Suggestion:
    category_id: int
    confidence: float  # agreement x average similarity; a ranking, not a probability
    neighbours: int  # how many similar labelled descriptions voted
    top_similarity: float


# --- embedding -------------------------------------------------------------------------------------


def embed_texts(
    db: Session,
    settings: Settings,
    texts: list[str],
    transport: httpx.BaseTransport | None = None,
) -> np.ndarray:
    """Unit-length float32 vectors, one row per text. LlmUnavailable if Ollama or the model is
    missing or its answer cannot be used (the caller skips the similarity tier)."""
    model = settings.ollama_embed_model
    rows: list[list[float]] = []
    with llm_json.open_client(settings, transport) as client:
        try:
            digest = _model_digest(client, model)
        except httpx.HTTPError as error:
            raise LlmUnavailable(f"Ollama unreachable: {type(error).__name__}") from None
        for start in range(0, len(texts), BATCH):
            batch = texts[start : start + BATCH]
            began = time.perf_counter()
            vectors: list | None = None
            try:
                reply = client.post("/api/embed", json={"model": model, "input": batch})
                reply.raise_for_status()
                vectors = reply.json().get("embeddings")
            except (httpx.HTTPError, ValueError):
                vectors = None
            usable = (
                isinstance(vectors, list)
                and len(vectors) == len(batch)
                and all(isinstance(v, list) and v for v in vectors)
                and len({len(v) for v in vectors}) == 1
            )
            db.add(
                ModelRun(
                    model=model,
                    digest=digest,
                    purpose="embed",
                    prompt_hash=hashlib.sha256("\n".join(batch).encode()).hexdigest(),
                    duration_ms=int((time.perf_counter() - began) * 1000),
                    valid_json=usable,
                )
            )
            if not usable:
                raise LlmUnavailable("the embedding model gave no usable answer")
            rows.extend(vectors)  # type: ignore[arg-type]
    matrix = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def vectors_for(
    db: Session,
    settings: Settings,
    user_id: int,
    stems: list[str],
    transport: httpx.BaseTransport | None = None,
) -> dict[str, np.ndarray]:
    """Vectors for these stems, from the cache where possible, embedding and storing the rest.
    The caller commits."""
    model = settings.ollama_embed_model
    found: dict[str, np.ndarray] = {}
    for start in range(0, len(stems), _IN_CHUNK):
        chunk = stems[start : start + _IN_CHUNK]
        for row in db.scalars(
            select(StemEmbedding).where(
                StemEmbedding.user_id == user_id,
                StemEmbedding.model == model,
                StemEmbedding.stem.in_(chunk),
            )
        ):
            found[row.stem] = np.frombuffer(row.vector, dtype=np.float32)
    missing = [s for s in dict.fromkeys(stems) if s not in found]
    if missing:
        fresh = embed_texts(db, settings, missing, transport)
        for stem, vector in zip(missing, fresh):
            db.add(StemEmbedding(user_id=user_id, stem=stem[:200], model=model, vector=vector.tobytes()))
            found[stem] = vector
    return found


# --- labels ----------------------------------------------------------------------------------------


def labelled_stems(db: Session, user_id: int) -> dict[str, int]:
    """{stem: category id} from descriptions you categorised yourself."""
    per_stem: dict[str, Counter] = defaultdict(Counter)
    for description, category_id, count in db.execute(
        select(Transaction.original_description, Transaction.category_id, func.count())
        .where(
            Transaction.user_id == user_id,
            Transaction.classification_source.in_(LABEL_SOURCES),
            Transaction.category_id.is_not(None),
        )
        .group_by(Transaction.original_description, Transaction.category_id)
    ):
        stem = description_stem(description)
        if stem:
            per_stem[stem][category_id] += count

    labels: dict[str, int] = {}
    for stem, votes in per_stem.items():
        category_id, top = votes.most_common(1)[0]
        if top / sum(votes.values()) >= MIN_STEM_MAJORITY:
            labels[stem] = category_id
    return labels


# --- voting ----------------------------------------------------------------------------------------


def vote(
    sims: np.ndarray,
    categories: list[int],
    k: int,
    min_similarity: float,
    min_agree: float,
    min_neighbours: int = 2,
) -> Suggestion | None:
    """Decide from one row of similarities to the labelled stems (`categories` is parallel)."""
    if sims.size == 0:
        return None
    order = np.argsort(-sims)[:k]
    near = [(float(sims[i]), categories[i]) for i in order if sims[i] >= min_similarity]
    if len(near) < min_neighbours:
        return None
    weight: Counter = Counter()
    for similarity, category in near:
        weight[category] += similarity
    winner, winner_weight = weight.most_common(1)[0]
    share = winner_weight / sum(weight.values())
    if share < min_agree:
        return None
    winners = [s for s, c in near if c == winner]
    return Suggestion(
        category_id=winner,
        confidence=round(share * (sum(winners) / len(winners)), 3),
        neighbours=len(winners),
        top_similarity=round(near[0][0], 3),
    )


def leave_one_out(
    vectors: np.ndarray,
    categories: list[int],
    k: int,
    min_similarity: float,
    min_agree: float,
) -> tuple[int, int]:
    """(suggested, right): hide each label, predict it from all the others."""
    sims = vectors @ vectors.T
    np.fill_diagonal(sims, -1.0)  # a label never votes for itself (below any similarity floor)
    suggested = right = 0
    for i in range(len(categories)):
        result = vote(sims[i], categories, k, min_similarity, min_agree)
        if result is not None:
            suggested += 1
            right += result.category_id == categories[i]
    return suggested, right


def suggest(
    db: Session,
    settings: Settings,
    user_id: int,
    stems: list[str],
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Suggestion]:
    """Hints for uncategorised stems. Empty when too few labels exist. May raise LlmUnavailable."""
    labels = labelled_stems(db, user_id)
    if len(labels) < settings.embed_min_labelled:
        return {}
    wanted = [s for s in stems if s not in labels]
    if not wanted:
        return {}

    label_stems = list(labels)
    vectors = vectors_for(db, settings, user_id, label_stems + wanted, transport)
    matrix = np.stack([vectors[s] for s in label_stems])
    categories = [labels[s] for s in label_stems]

    found: dict[str, Suggestion] = {}
    for stem in wanted:
        sims = matrix @ vectors[stem]
        result = vote(sims, categories, settings.embed_k, settings.embed_min_similarity, settings.embed_min_agree)
        if result is not None:
            found[stem] = result
    return found
