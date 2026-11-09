"""Measure whether similarity hints would be good enough on YOUR data, before turning them on.

Each description you categorised yourself is hidden in turn and predicted from all the others
(leave-one-out), across a grid of settings. Only aggregate numbers are printed (counts and
percentages), never a description, a category name or an amount, so the output is safe to share.
Run it inside the backend container, where the database and Ollama are reachable:

    docker compose exec ollama ollama pull nomic-embed-text
    docker compose exec backend python -m app.tools.eval_embeddings

    # No data of your own yet? Use the built-in synthetic set (41 invented descriptions):
    docker compose exec backend python -m app.tools.eval_embeddings --synthetic

Options:
  --k N              nearest neighbours consulted (default: the app's EMBED_K)
  --min-accuracy P   accuracy the confident part must reach to recommend it (default 0.90)
  --min-coverage P   share of descriptions it must cover (default 0.15)
  --synthetic        use the invented set in eval_set.json instead of your database

Reading the table: "suggested" is how many descriptions got a hint at those settings, "coverage"
that as a share of all labelled descriptions, "right" how many hints matched the category you chose,
"accuracy" right / suggested. The "always the biggest category" line is the bar to beat. A leave-one-out
test is a little optimistic (every description here was easy enough to label), so keep a margin.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.models import Base, User
from app.services import embeddings
from app.services.categorizer import description_stem
from app.services.llm_classifier import LlmUnavailable

EVAL_SET = Path(__file__).with_name("eval_set.json")
SIMILARITIES = (0.70, 0.75, 0.80, 0.85, 0.90)
AGREEMENTS = (0.60, 0.80, 1.00)


def synthetic_labels() -> dict[str, int]:
    """Invented descriptions with a numeric id per category name."""
    ids: dict[str, int] = {}
    labels: dict[str, int] = {}
    for item in json.loads(EVAL_SET.read_text(encoding="utf-8")):
        stem = description_stem(item["description"])
        if stem:
            labels[stem] = ids.setdefault(item["category"], len(ids) + 1)
    return labels


def run(labels: dict[str, int], vectors: np.ndarray, k: int, min_accuracy: float, min_coverage: float) -> int:
    categories = [labels[s] for s in labels]
    counts = Counter(categories)
    total = len(categories)
    biggest = counts.most_common(1)[0][1]
    print(f"Labelled descriptions: {total} in {len(counts)} categories (smallest: {min(counts.values())}, biggest: {biggest})")
    print(f"Always the biggest category would be right {biggest / total:.0%} of the time.")
    print(f"Vectors: {vectors.shape[0]} of {vectors.shape[1]} dimensions. k={k}. Leave-one-out.\n")
    print(f"{'min similarity':>14} {'min agree':>10} {'suggested':>10} {'coverage':>9} {'right':>6} {'accuracy':>9}")

    best: tuple[float, float, int, int] | None = None
    for similarity in SIMILARITIES:
        for agree in AGREEMENTS:
            suggested, right = embeddings.leave_one_out(vectors, categories, k, similarity, agree)
            accuracy = right / suggested if suggested else 0.0
            coverage = suggested / total
            marker = ""
            if suggested and accuracy >= min_accuracy and coverage >= min_coverage:
                marker = "  <= meets the bar"
                if best is None or coverage > best[2] / total:
                    best = (similarity, agree, suggested, right)
            shown = f"{accuracy:>8.0%}" if suggested else f"{'-':>8}"
            print(f"{similarity:>14.2f} {agree:>10.2f} {suggested:>10} {coverage:>8.0%} {right:>6} {shown}{marker}")

    print()
    if best is None:
        print(
            f"Verdict: no setting reaches {min_accuracy:.0%} accuracy while covering {min_coverage:.0%}. "
            "Leave EMBED_SUGGEST_ENABLED off (or label more descriptions and run this again)."
        )
        return 1
    print(
        f"Verdict: it can meet the bar. Suggested settings: EMBED_MIN_SIMILARITY={best[0]:.2f}, "
        f"EMBED_MIN_AGREE={best[1]:.2f}, EMBED_K={k}, then EMBED_SUGGEST_ENABLED=true."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--k", type=int)
    parser.add_argument("--min-accuracy", type=float, default=0.90)
    parser.add_argument("--min-coverage", type=float, default=0.15)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    k = args.k or settings.embed_k

    if args.synthetic:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as db:
            labels = synthetic_labels()
            user_id = None
    else:
        from app.db import SessionLocal

        factory = SessionLocal
        with factory() as db:
            first = db.scalar(select(User.id).order_by(User.id).limit(1))
            if first is None:
                print("No user yet.")
                return 2
            user_id = first
            labels = embeddings.labelled_stems(db, user_id)

    if len(labels) < 10:
        print(f"Only {len(labels)} labelled descriptions. Categorise more yourself (Review, or the category menu), then run again.")
        return 2

    print(f"Embedding model: {settings.ollama_embed_model}")
    try:
        with factory() as db:
            if user_id is None:
                vectors = embeddings.embed_texts(db, settings, list(labels))
                db.rollback()  # the synthetic run keeps nothing
            else:
                cache = embeddings.vectors_for(db, settings, user_id, list(labels))
                db.commit()
                vectors = np.stack([cache[s] for s in labels])
    except LlmUnavailable as error:
        print(f"Cannot embed: {error}\nInstall the model first: docker compose exec ollama ollama pull {settings.ollama_embed_model}")
        return 2

    return run(labels, vectors, k, args.min_accuracy, args.min_coverage)


if __name__ == "__main__":
    sys.exit(main())
