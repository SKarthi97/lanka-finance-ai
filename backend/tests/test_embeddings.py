"""Similarity hints (4.3), against a fake Ollama whose embeddings are hashed character trigrams:
descriptions that share words get similar vectors. No real model or network is used."""

import hashlib
import json

import httpx
import numpy as np
import pytest
from sqlalchemy import func, select

from app.models import ModelRun, StemEmbedding
from app.services import embeddings, llm_classifier
from app.services.llm_classifier import LlmUnavailable, classify_uncategorised

from .synthetic import boc_pdf
from .test_extraction import run_pipeline

H = lambda csrf: {"X-CSRF-Token": csrf}  # noqa: E731
EMBED_MODEL = "nomic-embed-text"


def vec(text: str, dim: int = 96) -> list[float]:
    v = np.zeros(dim, dtype=np.float32)
    padded = f"  {text.lower()}  "
    for i in range(len(padded) - 2):
        v[int(hashlib.md5(padded[i : i + 3].encode()).hexdigest(), 16) % dim] += 1
    return (v / np.linalg.norm(v)).tolist()


def fake_ollama(seen, generate_replies=None, embed_ok=True, installed=(EMBED_MODEL, "qwen2.5:1.5b")):
    """Serves tags, embeddings (trigram vectors) and generate (one scripted reply at a time)."""
    replies = list(generate_replies or [])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n, "digest": "sha256:" + n} for n in installed]})
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        if request.url.path == "/api/embed":
            if not embed_ok:
                return httpx.Response(200, json={"embeddings": []})
            return httpx.Response(200, json={"embeddings": [vec(t) for t in body["input"]]})
        reply = replies.pop(0) if replies else {"results": []}
        return httpx.Response(200, json={"response": json.dumps(reply)})

    return httpx.MockTransport(handler)


def embed_calls(seen):
    return [b for path, b in seen if path == "/api/embed"]


LABELLED = ["ZORBA FOODMART KANDY", "ZORBA FOODMART GALLE", "ZORBA FOODMART JAFFNA"]
UNLABELLED = ["ZORBA FOODMART MATARA", "QUIXOTE WINDMILL REPAIR"]


@pytest.fixture()
def prepared(logged_in, session_factory, test_settings):
    test_settings.llm_classify_enabled = True
    test_settings.embed_enabled = True
    test_settings.embed_min_labelled = 3
    test_settings.embed_min_similarity = 0.70
    client, csrf = logged_in
    names = LABELLED + UNLABELLED
    rows, balance = [], 1000
    for i, name in enumerate(names):
        balance -= 10
        rows.append((f"0{i + 2}/09", name, "10.00", f"{balance:,.2f}"))
    run_pipeline(client, csrf, session_factory, test_settings, boc_pdf(rows=rows, closing=f"{balance:,.2f}"))

    shopping = {c["name"]: c["id"] for c in client.get("/api/categories").json()}["Shopping"]
    items = {t["description"]: t for t in client.get("/api/transactions?limit=50").json()["items"]}
    for name in LABELLED:  # you categorised these yourself
        client.put(f"/api/transactions/{items[name]['id']}/category", json={"category_id": shopping}, headers=H(csrf))
    return client, csrf, shopping


def run_ai(session_factory, settings, transport):
    with session_factory() as db:
        counts = classify_uncategorised(db, settings, 1, transport)
        db.commit()
    return counts


# --- the arithmetic ---------------------------------------------------------------------------------


def test_vote_needs_enough_close_and_agreeing_neighbours():
    sims = np.array([0.95, 0.90, 0.40])
    assert embeddings.vote(sims, [1, 1, 2], k=5, min_similarity=0.8, min_agree=0.8).category_id == 1
    assert embeddings.vote(sims, [1, 1, 2], k=5, min_similarity=0.8, min_agree=0.8).neighbours == 2
    assert embeddings.vote(np.array([0.95, 0.40]), [1, 1], 5, 0.8, 0.8) is None  # one close neighbour only
    assert embeddings.vote(np.array([0.9, 0.9]), [1, 2], 5, 0.8, 0.8) is None  # they disagree
    assert embeddings.vote(np.array([]), [], 5, 0.8, 0.8) is None


def test_confidence_is_agreement_times_similarity_and_never_above_one():
    result = embeddings.vote(np.array([0.9, 0.9, 0.9]), [1, 1, 1], 5, 0.8, 0.8)
    assert result.confidence == 0.9 and result.top_similarity == 0.9


def test_leave_one_out_separates_clusters():
    rng = np.random.default_rng(1)
    a = rng.normal(size=(1, 16)) + rng.normal(scale=0.05, size=(6, 16))
    b = -a + rng.normal(scale=0.05, size=(6, 16))
    vectors = np.vstack([a, b]).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    suggested, right = embeddings.leave_one_out(vectors, [1] * 6 + [2] * 6, 5, 0.8, 0.8)
    assert (suggested, right) == (12, 12)


# --- labels ---------------------------------------------------------------------------------------------


def test_only_your_own_decisions_are_labels(prepared, session_factory):
    with session_factory() as db:
        labels = embeddings.labelled_stems(db, 1)
    assert set(labels) == set(LABELLED)  # built-in rules and unlabelled rows are not labels


def test_a_stem_split_between_categories_has_no_label(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    rows = [("02/09", "SPLIT SHOP", "10.00", "990.00"), ("03/09", "SPLIT SHOP", "10.00", "980.00")]
    run_pipeline(client, csrf, session_factory, test_settings, boc_pdf(rows=rows, closing="980.00"))
    ids = {c["name"]: c["id"] for c in client.get("/api/categories").json()}
    items = client.get("/api/transactions").json()["items"]
    for item, cat in zip(items, ("Shopping", "Fuel"), strict=False):
        client.put(f"/api/transactions/{item['id']}/category", json={"category_id": ids[cat]}, headers=H(csrf))
    with session_factory() as db:
        assert embeddings.labelled_stems(db, 1) == {}


# --- suggestions end to end -------------------------------------------------------------------------------


def test_a_similar_description_gets_a_hint_and_a_different_one_does_not(prepared, session_factory, test_settings):
    client, _, shopping = prepared
    seen: list = []
    counts = run_ai(session_factory, test_settings, fake_ollama(seen, [{"results": []}]))
    assert counts["similar"] == 1

    items = {t["description"]: t for t in client.get("/api/transactions?limit=50").json()["items"]}
    similar = items["ZORBA FOODMART MATARA"]
    assert similar["category_id"] is None  # a hint is never applied
    assert similar["classification_source"] == "llm_unsure"
    assert similar["classification_explanation"] == "Similar to 3 descriptions you categorised"
    assert items["QUIXOTE WINDMILL REPAIR"]["classification_source"] != "similar"

    review = {g["stem"]: g for g in client.get("/api/categorization/review").json()["groups"]}
    group = review["ZORBA FOODMART MATARA"]
    assert group["hint_category_id"] == shopping
    assert group["hint_reason"] == "Similar to 3 descriptions you categorised"
    assert review["QUIXOTE WINDMILL REPAIR"]["hint_category_id"] is None


def test_stems_with_a_hint_skip_the_slow_model(prepared, session_factory, test_settings):
    seen: list = []
    run_ai(session_factory, test_settings, fake_ollama(seen, [{"results": []}]))
    generate = [b for path, b in seen if path == "/api/generate"]
    assert len(generate) == 1
    asked = generate[0]["prompt"].split("Descriptions:")[1]
    assert "QUIXOTE" in asked and "ZORBA FOODMART MATARA" not in asked


def test_only_stems_are_embedded(prepared, session_factory, test_settings):
    seen: list = []
    run_ai(session_factory, test_settings, fake_ollama(seen, [{"results": []}]))
    texts = [t for body in embed_calls(seen) for t in body["input"]]
    assert {t.removeprefix("classification: ") for t in texts} == set(LABELLED + UNLABELLED)
    assert all(t.startswith("classification: ") for t in texts)  # the task word nomic-embed-text expects
    assert all(not any(c.isdigit() for c in t) for t in texts)  # no amounts, dates or numbers
    assert {b["model"] for b in embed_calls(seen)} == {EMBED_MODEL}


def test_vectors_are_cached_so_a_second_pass_does_not_embed_again(prepared, session_factory, test_settings):
    first: list = []
    run_ai(session_factory, test_settings, fake_ollama(first, [{"results": []}]))
    # ask again: the unsure rows are reset, as the "Ask the AI" button does
    with session_factory() as db:
        from app.models import Transaction

        db.query(Transaction).filter(Transaction.classification_source == "llm_unsure").update(
            {"classification_source": None}
        )
        db.commit()
    second: list = []
    run_ai(session_factory, test_settings, fake_ollama(second, [{"results": []}]))
    assert len(embed_calls(first)) == 1 and embed_calls(second) == []
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(StemEmbedding)) == 5


def test_the_calls_are_logged_by_time_only(prepared, session_factory, test_settings):
    run_ai(session_factory, test_settings, fake_ollama([], [{"results": []}]))
    with session_factory() as db:
        run = db.scalar(select(ModelRun).where(ModelRun.purpose == "embed"))
        assert run.valid_json and len(run.prompt_hash) == 64 and run.model == EMBED_MODEL


# --- when it should do nothing ------------------------------------------------------------------------------


def test_it_is_off_by_default(prepared, session_factory, test_settings):
    test_settings.embed_enabled = False
    seen: list = []
    counts = run_ai(session_factory, test_settings, fake_ollama(seen, [{"results": []}]))
    assert embed_calls(seen) == [] and "similar" not in counts


def test_too_few_labels_means_no_hints(prepared, session_factory, test_settings):
    test_settings.embed_min_labelled = 50
    seen: list = []
    counts = run_ai(session_factory, test_settings, fake_ollama(seen, [{"results": []}]))
    assert counts["similar"] == 0 and embed_calls(seen) == []


def test_a_missing_embedding_model_falls_back_to_the_normal_pass(prepared, session_factory, test_settings):
    seen: list = []
    counts = run_ai(session_factory, test_settings, fake_ollama(seen, [{"results": []}], installed=("qwen2.5:1.5b",)))
    assert counts["similar"] == 0 and counts["stems"] == 2  # both stems still went to the model


def test_an_unusable_embedding_answer_falls_back_too(prepared, session_factory, test_settings):
    counts = run_ai(session_factory, test_settings, fake_ollama([], [{"results": []}], embed_ok=False))
    assert counts["similar"] == 0 and counts["stems"] == 2


def test_embed_texts_raises_when_the_model_is_absent(prepared, session_factory, test_settings):
    with session_factory() as db, pytest.raises(LlmUnavailable):
        embeddings.embed_texts(db, test_settings, ["X"], fake_ollama([], installed=("other",)))


def test_the_default_is_off_and_the_model_is_named():
    from app.config import Settings

    s = Settings()
    assert s.embed_enabled is False and s.ollama_embed_model == "nomic-embed-text"
    assert llm_classifier.BATCH_SIZE > 0


# --- the evaluation tool ---------------------------------------------------------------------------------------


def clustered(n_classes=3, per_class=8, noise=0.05):
    rng = np.random.default_rng(7)
    centres = rng.normal(size=(n_classes, 24))
    vectors = np.vstack([c + rng.normal(scale=noise, size=(per_class, 24)) for c in centres]).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    labels = {f"S{i}": i // per_class + 1 for i in range(n_classes * per_class)}
    return labels, vectors


def test_the_tool_recommends_settings_when_they_meet_the_bar(capsys):
    from app.tools import eval_embeddings

    labels, vectors = clustered()
    assert eval_embeddings.run(labels, vectors, 5, 0.90, 0.15) == 0
    out = capsys.readouterr().out
    assert "meets the bar" in out and "Verdict: it can meet the bar" in out
    assert "EMBED_SUGGEST_ENABLED=true" in out


def test_the_tool_says_no_when_nothing_is_good_enough(capsys):
    from app.tools import eval_embeddings

    labels, _ = clustered()
    noise = np.random.default_rng(3).normal(size=(len(labels), 24)).astype(np.float32)
    noise /= np.linalg.norm(noise, axis=1, keepdims=True)  # vectors with no structure
    assert eval_embeddings.run(labels, noise, 5, 0.90, 0.15) == 1
    assert "Leave EMBED_SUGGEST_ENABLED off" in capsys.readouterr().out


def test_the_tool_prints_only_aggregates(capsys):
    from app.tools import eval_embeddings

    labels, vectors = clustered()
    eval_embeddings.run(labels, vectors, 5, 0.90, 0.15)
    out = capsys.readouterr().out
    assert "S0" not in out and "S1" not in out  # no description (here: stem name) is printed


def test_the_synthetic_set_is_usable():
    from app.tools import eval_embeddings

    labels = eval_embeddings.synthetic_labels()
    per_class = {c: list(labels.values()).count(c) for c in set(labels.values())}
    assert len(labels) >= 70 and len(per_class) == 13
    assert min(per_class.values()) >= 5  # enough per category for a neighbour vote


# --- the task word, the neighbour count and the diagnostics ---------------------------------------------------


def test_the_task_word_can_be_turned_off(prepared, session_factory, test_settings):
    test_settings.embed_task = ""
    seen: list = []
    run_ai(session_factory, test_settings, fake_ollama(seen, [{"results": []}]))
    texts = [t for body in embed_calls(seen) for t in body["input"]]
    assert set(texts) == set(LABELLED + UNLABELLED)  # sent as they are


def test_vectors_are_cached_per_task_word(prepared, session_factory, test_settings):
    run_ai(session_factory, test_settings, fake_ollama([], [{"results": []}]))
    test_settings.embed_task = "clustering"
    with session_factory() as db:
        before = db.scalar(select(func.count()).select_from(StemEmbedding))
        embeddings.vectors_for(db, test_settings, 1, LABELLED, fake_ollama([], []))
        db.commit()
        keys = set(db.scalars(select(StemEmbedding.model)))
        assert db.scalar(select(func.count()).select_from(StemEmbedding)) == before + 3  # embedded again
    assert keys == {"nomic-embed-text|classification", "nomic-embed-text|clustering"}


def test_the_neighbour_count_is_a_setting(prepared, session_factory, test_settings):
    test_settings.embed_min_neighbours = 4  # only three labelled neighbours exist
    counts = run_ai(session_factory, test_settings, fake_ollama([], [{"results": []}]))
    assert counts["similar"] == 0


def test_the_similarity_report_describes_the_separation():
    labels, vectors = clustered(n_classes=3, per_class=8)
    r = embeddings.similarity_report(vectors, list(labels.values()))
    assert r["n"] == 24 and r["eligible"] == 24
    assert r["same"] > r["different"] + 0.5 and r["nearest_same"] == 1.0
    assert r["nearest_p50"] > 0.9


def test_the_report_counts_descriptions_with_no_category_mate():
    vectors = np.eye(4, dtype=np.float32)
    r = embeddings.similarity_report(vectors, [1, 1, 2, 3])
    assert r["eligible"] == 2 and r["same"] is not None


def test_the_tool_explains_why_nothing_was_suggested_when_data_is_sparse(capsys):
    from app.tools import eval_embeddings

    rng = np.random.default_rng(5)
    vectors = rng.normal(size=(12, 16)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    labels = {f"S{i}": i + 1 for i in range(12)}  # every description alone in its category
    assert eval_embeddings.run(labels, vectors, 5, 0.90, 0.15) == 1
    out = capsys.readouterr().out
    assert "1. How the model separates your categories" in out
    assert "Too few descriptions share a category" in out
    assert "3. Diagnostic only" in out and "S0" not in out


def test_the_tool_flags_a_model_that_cannot_tell_categories_apart(capsys):
    from app.tools import eval_embeddings

    rng = np.random.default_rng(9)
    base = rng.normal(size=16)
    vectors = (base + rng.normal(scale=0.01, size=(20, 16))).astype(np.float32)  # all nearly identical
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    labels = {f"S{i}": i % 4 + 1 for i in range(20)}
    eval_embeddings.run(labels, vectors, 5, 0.90, 0.15)
    assert "barely tells one category from another" in capsys.readouterr().out


def test_the_tool_covers_lower_similarities_too(capsys):
    from app.tools import eval_embeddings

    labels, vectors = clustered()
    eval_embeddings.run(labels, vectors, 5, 0.90, 0.15)
    assert "          0.50" in capsys.readouterr().out


# The two tables from a real run on the synthetic set (78 descriptions), as (similarity, agree, suggested, right).
WITH_TASK_WORD = [
    (0.50, 0.60, 50, 48), (0.50, 0.80, 40, 39), (0.50, 1.00, 14, 14),
    (0.70, 0.60, 50, 47), (0.70, 0.80, 41, 40), (0.70, 1.00, 17, 17),
    (0.75, 0.60, 48, 44), (0.75, 0.80, 40, 39), (0.75, 1.00, 24, 23),
    (0.80, 0.60, 37, 36), (0.80, 0.80, 29, 29), (0.80, 1.00, 26, 26),
    (0.85, 0.60, 20, 20), (0.85, 0.80, 20, 20), (0.85, 1.00, 20, 20),
    (0.90, 0.60, 0, 0),
]  # fmt: skip
WITHOUT_TASK_WORD = [
    (0.50, 0.60, 43, 39), (0.50, 0.80, 24, 24), (0.50, 1.00, 9, 9),
    (0.60, 0.80, 18, 17), (0.65, 0.60, 30, 29), (0.65, 0.80, 18, 18), (0.65, 1.00, 13, 13),
    (0.70, 0.60, 21, 19), (0.75, 0.80, 8, 8), (0.80, 0.80, 1, 1),
]  # fmt: skip


def test_the_recommendation_is_the_most_accurate_row_not_the_widest():
    from app.tools import eval_embeddings

    # 100% rows: the widest of them is 0.80 / 0.80 with 29 hints (not 0.50 / 0.60, which is 96% on 50)
    assert eval_embeddings.pick(WITH_TASK_WORD, 78, 0.90, 0.15) == (0.80, 0.80, 29, 29)
    assert eval_embeddings.pick(WITHOUT_TASK_WORD, 78, 0.90, 0.15) == (0.50, 0.80, 24, 24)


def test_a_row_with_too_few_hints_never_counts():
    from app.tools import eval_embeddings

    assert eval_embeddings.pick([(0.80, 0.80, 8, 8)], 78, 0.90, 0.05) is None  # 8 < 10 hints
    assert eval_embeddings.pick([(0.80, 0.80, 12, 12)], 78, 0.90, 0.20) is None  # covers only 15%
    assert eval_embeddings.pick([(0.80, 0.80, 20, 17)], 78, 0.90, 0.15) is None  # 85% accurate
    assert eval_embeddings.pick([], 78, 0.90, 0.15) is None


def test_the_defaults_are_the_row_the_real_run_recommended():
    from app.config import Settings

    s = Settings()
    assert (s.embed_min_similarity, s.embed_min_agree, s.embed_min_neighbours, s.embed_k) == (0.80, 0.80, 2, 5)
    assert s.embed_task == "classification"


def test_the_tool_marks_the_recommended_row(capsys):
    from app.tools import eval_embeddings

    labels, vectors = clustered()
    eval_embeddings.run(labels, vectors, 5, 0.90, 0.15)
    out = capsys.readouterr().out
    assert out.count("(recommended)") == 1
    assert "read the accuracy as approximate" in out

