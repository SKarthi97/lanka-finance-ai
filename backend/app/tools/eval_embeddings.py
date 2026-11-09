"""Measure whether similarity hints would be good enough on YOUR data, before turning them on.

Each description you categorised yourself is hidden in turn and predicted from all the others
(leave-one-out). Only aggregate numbers are printed (counts, percentages, similarity averages),
never a description, a category name or an amount, so the output is safe to share. Run it inside
the backend container, where the database and Ollama are reachable:

    docker compose exec ollama ollama pull nomic-embed-text
    docker compose exec backend python -m app.tools.eval_embeddings

    # A sanity check of the model and settings with 78 invented descriptions (13 categories x 6),
    # no data of your own needed. It says whether the model can separate ordinary wording; it
    # cannot tell you how it does on YOUR merchants.
    docker compose exec backend python -m app.tools.eval_embeddings --synthetic

Options:
  --k N               nearest neighbours consulted (default: EMBED_K)
  --min-neighbours N  close, agreeing neighbours a hint needs (default: EMBED_MIN_NEIGHBOURS)
  --task WORD         the task word put before each text ("classification", "clustering", ...);
                      "none" sends the text as it is (default: EMBED_TASK)
  --min-accuracy P    accuracy the confident part must reach to recommend it (default 0.90)
  --min-coverage P    share of descriptions it must cover (default 0.15)
  --synthetic         use the invented set in eval_set.json instead of your database

The output has three parts.
1. How well the model separates your categories: the similarity of each description to its closest
   neighbour, the average similarity inside a category compared with between categories (the gap
   is what a vote can use), and how often the single closest neighbour is in the right category.
2. The table for the app's own rule (needs MIN_NEIGHBOURS close neighbours that agree). A row needs at
   least 10 hints to count; the recommended row is the most ACCURATE one that meets the bar.
3. The same with one neighbour allowed: a diagnostic only, to tell "the model cannot tell" from
   "there is too little data".
"suggested" is how many descriptions got a hint at those settings, "coverage" that as a share of all
labelled descriptions, "accuracy" how often the hint matched the category you chose. A leave-one-out
test is a little optimistic, so keep a margin. Zeros everywhere mean either the similarity floor is
above what this model produces (see part 1) or too few descriptions share a category.
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

EVAL_SET = Path(__file__).with_name("embed_eval_set.json")
SIMILARITIES = (0.40, 0.45, 0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90)
MIN_SUGGESTED = 10  # fewer hints than this say too little to count as meeting the bar
AGREEMENTS = (0.60, 0.80, 1.00)


def synthetic_labels() -> dict[str, int]:
    """Invented descriptions (embed_eval_set.json) with a numeric id per category name."""
    ids: dict[str, int] = {}
    labels: dict[str, int] = {}
    for item in json.loads(EVAL_SET.read_text(encoding="utf-8")):
        stem = description_stem(item["description"])
        if stem:
            labels[stem] = ids.setdefault(item["category"], len(ids) + 1)
    return labels


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def describe(vectors: np.ndarray, categories: list[int]) -> list[str]:
    """Part 1, as plain lines. Returns the advice lines too."""
    r = embeddings.similarity_report(vectors, categories)
    n = r["n"]
    lines = [
        f"Closest neighbour similarity: 10% of descriptions below {_fmt(r['nearest_p10'])}, "
        f"half below {_fmt(r['nearest_p50'])}, 90% below {_fmt(r['nearest_p90'])}.",
        f"Average similarity inside a category {_fmt(r['same'])}, between categories {_fmt(r['different'])}"
        + (f" (gap {r['same'] - r['different']:.2f})." if r["same"] is not None and r["different"] is not None else "."),
        f"The single closest neighbour is in the right category for {r['nearest_same']:.0%} of descriptions.",
        f"{r['eligible']} of {n} descriptions share a category with another one; a vote can only be right for those.",
    ]
    advice = []
    if r["eligible"] < n * 0.5:
        advice.append("Too few descriptions share a category for a neighbour vote to work: categorise more of your own first.")
    if r["same"] is not None and r["different"] is not None and r["same"] - r["different"] < 0.05:
        advice.append("The model barely tells one category from another here. Try another --task word, or another embedding model.")
    if r["nearest_p90"] < min(SIMILARITIES):
        advice.append(f"Even the closest neighbours are below {min(SIMILARITIES):.2f}: lower EMBED_MIN_SIMILARITY or change the task word.")
    return lines + advice


def pick(
    rows: list[tuple[float, float, int, int]],
    total: int,
    min_accuracy: float,
    min_coverage: float,
    min_suggested: int = MIN_SUGGESTED,
) -> tuple[float, float, int, int] | None:
    """The row to recommend from (similarity, agree, suggested, right): among those that meet the
    bar with enough hints, the MOST ACCURATE (ties: the widest coverage). Accuracy first because a
    wrong hint costs more than a missing one."""
    fit = [
        r
        for r in rows
        if r[2] >= min_suggested and r[3] / r[2] >= min_accuracy and r[2] / total >= min_coverage
    ]
    return max(fit, key=lambda r: (r[3] / r[2], r[2])) if fit else None


def run(
    labels: dict[str, int],
    vectors: np.ndarray,
    k: int,
    min_accuracy: float,
    min_coverage: float,
    min_neighbours: int = 2,
) -> int:
    categories = [labels[s] for s in labels]
    counts = Counter(categories)
    total = len(categories)
    biggest = counts.most_common(1)[0][1]
    print(f"Labelled descriptions: {total} in {len(counts)} categories (smallest: {min(counts.values())}, biggest: {biggest})")
    print(f"Always the biggest category would be right {biggest / total:.0%} of the time.")
    print(f"Vectors: {vectors.shape[0]} of {vectors.shape[1]} dimensions. k={k}. Leave-one-out.\n")

    print("1. How the model separates your categories")
    for line in describe(vectors, categories):
        print("   " + line)

    header = f"{'min similarity':>14} {'min agree':>10} {'suggested':>10} {'coverage':>9} {'right':>6} {'accuracy':>9}"
    print(f"\n2. The app's rule: {min_neighbours} or more close neighbours that agree\n{header}")
    rows: list[tuple[float, float, int, int]] = []
    for similarity in SIMILARITIES:
        for agree in AGREEMENTS:
            suggested, right = embeddings.leave_one_out(vectors, categories, k, similarity, agree, min_neighbours)
            rows.append((similarity, agree, suggested, right))
    best = pick(rows, total, min_accuracy, min_coverage)
    for similarity, agree, suggested, right in rows:
        accuracy = right / suggested if suggested else 0.0
        coverage = suggested / total
        marker = ""
        if suggested >= MIN_SUGGESTED and accuracy >= min_accuracy and coverage >= min_coverage:
            marker = "  <= meets the bar" + ("  (recommended)" if (similarity, agree) == best[:2] else "")
        shown = f"{accuracy:>8.0%}" if suggested else f"{'-':>8}"
        print(f"{similarity:>14.2f} {agree:>10.2f} {suggested:>10} {coverage:>8.0%} {right:>6} {shown}{marker}")

    print(f"\n3. Diagnostic only: a single close neighbour is enough (not safe to use)\n{header.replace(' min agree ', '           ')}")
    for similarity in SIMILARITIES:
        suggested, right = embeddings.leave_one_out(vectors, categories, k, similarity, 0.0, 1)
        accuracy = f"{right / suggested:>8.0%}" if suggested else f"{'-':>8}"
        print(f"{similarity:>14.2f} {'':>10} {suggested:>10} {suggested / total:>8.0%} {right:>6} {accuracy}")

    print()
    if best is None:
        print(
            f"Verdict: no setting reaches {min_accuracy:.0%} accuracy while covering {min_coverage:.0%}. "
            "Leave EMBED_SUGGEST_ENABLED off, or fix what part 1 points at and run this again."
        )
        return 1
    print(
        f"Verdict: it can meet the bar. Suggested settings: EMBED_MIN_SIMILARITY={best[0]:.2f}, "
        f"EMBED_MIN_AGREE={best[1]:.2f}, EMBED_MIN_NEIGHBOURS={min_neighbours}, EMBED_K={k}, "
        "then EMBED_SUGGEST_ENABLED=true."
    )
    print(
        f"That row gave {best[2]} hints, {best[3]} of them right. With so few, read the accuracy as approximate "
        "(18 right out of 18 could still be about 85% in reality); run this again as you categorise more."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--k", type=int)
    parser.add_argument("--min-neighbours", type=int)
    parser.add_argument("--task")
    parser.add_argument("--min-accuracy", type=float, default=0.90)
    parser.add_argument("--min-coverage", type=float, default=0.15)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    if args.task is not None:
        settings = settings.model_copy(update={"embed_task": "" if args.task.lower() == "none" else args.task})
    k = args.k or settings.embed_k
    min_neighbours = args.min_neighbours or settings.embed_min_neighbours

    if args.synthetic:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
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

    print(f"Embedding model: {settings.ollama_embed_model}, task word: {settings.embed_task or 'none'}")
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

    return run(labels, vectors, k, args.min_accuracy, args.min_coverage, min_neighbours)


if __name__ == "__main__":
    sys.exit(main())
