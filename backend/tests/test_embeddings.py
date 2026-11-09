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
    for item, cat in zip(items, ("Shopping", "Fuel")):
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
    assert set(texts) == set(LABELLED + UNLABELLED)
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
    assert len(labels) >= 20 and len(set(labels.values())) >= 5
