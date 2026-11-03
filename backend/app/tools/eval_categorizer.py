"""Compare local models on categorisation, using a small SYNTHETIC labelled set.

Nothing from your statements or database is used: the descriptions in eval_set.json are
invented, generic bank wording, so the output is safe to share. Run it inside the backend
container, where Ollama is reachable:

    docker compose exec backend python -m app.tools.eval_categorizer qwen2.5:1.5b qwen2.5:3b
    docker compose exec backend python -m app.tools.eval_categorizer qwen2.5:3b --timeout 300 --batch 5 --verbose

Options:
  --timeout S   seconds to wait per model call (default: the app's setting). A bigger model on
                CPU may need several minutes per call; a call that times out looks like "no reply".
  --batch N     descriptions per call (default: the app's batch size). Smaller is easier for
                small models.
  --verbose     one line per description: expected, what the model said, its confidence.

A model must already be installed (`docker compose exec ollama ollama pull qwen2.5:3b`).
The table shows, per model: how many it answered, how many it got right, how often it was
right when it was confident enough to be applied (the number that matters), and how long it
took. "no reply" means the call timed out or the reply was unusable; "null" means the model
answered but declined to choose.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models import Base
from app.services import llm_classifier
from app.services.categorizer import CATEGORIES
from app.services.llm_classifier import LlmUnavailable, classify_stems

EVAL_SET = Path(__file__).with_name("eval_set.json")


def load_cases() -> list[tuple[str, str]]:
    data = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    return [(item["description"], item["category"]) for item in data]


def evaluate(model: str, timeout: float | None = None, batch: int | None = None) -> dict:
    update = {"ollama_model": model}
    if timeout is not None:
        update["ollama_timeout_s"] = timeout
    settings = get_settings().model_copy(update=update)
    if batch is not None:
        llm_classifier.BATCH_SIZE = batch
    categories = [(index + 1, name, kind) for index, (name, kind) in enumerate(CATEGORIES)]
    names = {cid: name for cid, name, _ in categories}

    cases = load_cases()
    stems = [description for description, _ in cases]
    expected = dict(cases)

    engine = create_engine("sqlite://")  # throwaway: only the per-call run log lands here
    Base.metadata.create_all(engine)
    began = time.perf_counter()
    with sessionmaker(engine)() as db:
        suggestions, answered = classify_stems(db, settings, stems, categories)
        calls = db.execute(llm_classifier.ModelRun.__table__.select()).fetchall()
    seconds = time.perf_counter() - began

    right = confident = confident_right = 0
    rows = []
    for stem in stems:
        suggestion = suggestions.get(stem)
        if suggestion is None:
            rows.append((stem, expected[stem], "null" if stem in answered else "no reply", None, False))
            continue
        correct = names[suggestion.category_id] == expected[stem]
        right += correct
        if suggestion.confidence >= settings.llm_confidence_threshold:
            confident += 1
            confident_right += correct
        rows.append((stem, expected[stem], names[suggestion.category_id], suggestion.confidence, correct))

    return {
        "model": model,
        "cases": len(cases),
        "answered": len(suggestions),
        "no_reply": len(stems) - len(answered),
        "right": right,
        "confident": confident,
        "confident_right": confident_right,
        "calls": len(calls),
        "bad_calls": sum(1 for c in calls if not c.valid_json),
        "seconds": seconds,
        "rows": rows,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="eval_categorizer")
    parser.add_argument("models", nargs="*")
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--batch", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    models = args.models or [settings.ollama_model]
    print(
        f"Confident means confidence >= {settings.llm_confidence_threshold}; "
        f"timeout {args.timeout or settings.ollama_timeout_s:g}s; "
        f"batch {args.batch or llm_classifier.BATCH_SIZE}\n"
    )
    print(
        f"{'model':16} {'answered':>9} {'no reply':>9} {'right':>6} {'confident':>10} "
        f"{'right when confident':>21} {'bad calls':>10} {'seconds':>8}"
    )
    results = []
    for model in models:
        try:
            r = evaluate(model, args.timeout, args.batch)
        except LlmUnavailable as error:
            print(f"{model:16} unavailable: {error}")
            continue
        results.append(r)
        sure = f"{r['confident_right']}/{r['confident']}" if r["confident"] else "-"
        print(
            f"{r['model']:16} {r['answered']:>4}/{r['cases']:<4} {r['no_reply']:>9} {r['right']:>6} "
            f"{r['confident']:>10} {sure:>21} {r['bad_calls']:>4}/{r['calls']:<5} {r['seconds']:>8.1f}"
        )

    if args.verbose:
        for r in results:
            print(f"\n{r['model']}: expected -> model said (confidence)")
            for stem, want, got, confidence, correct in r["rows"]:
                mark = "ok " if correct else "BAD" if confidence is not None else "-- "
                conf = "" if confidence is None else f" ({confidence:.2f})"
                print(f"  {mark} {stem:34} {want:16} -> {got}{conf}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
