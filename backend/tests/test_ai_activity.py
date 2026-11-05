"""Progress and timing for the AI features. Durations only; never prompts or replies."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Job, ModelRun
from app.services import ai_activity, merchants, search
from app.services.llm_classifier import BATCH_SIZE, MAX_STEMS_PER_JOB

from .test_ai_features import fake_ollama, loaded, run_naming, seeded  # noqa: F401


def add_runs(session_factory, purpose, durations, ok=True):
    with session_factory() as db:
        for ms in durations:
            db.add(ModelRun(model="m", digest=None, purpose=purpose, prompt_hash="0" * 64,
                            duration_ms=ms, valid_json=ok))  # fmt: skip
        db.commit()


def test_the_activity_list_is_empty_at_first(logged_in):
    client, _ = logged_in
    assert client.get("/api/ai/activity").json() == {"window_days": 30, "summary": [], "recent": []}


def test_activity_summarises_calls_by_purpose(logged_in, session_factory):
    client, _ = logged_in
    add_runs(session_factory, "merchant", [2000, 4000, 6000])
    add_runs(session_factory, "search", [1500])
    add_runs(session_factory, "search", [900], ok=False)

    data = client.get("/api/ai/activity").json()
    by = {s["purpose"]: s for s in data["summary"]}
    assert by["merchant"] == {"purpose": "merchant", "runs": 3, "ok_runs": 3, "avg_ms": 4000, "max_ms": 6000, "total_ms": 12000}
    assert (by["search"]["runs"], by["search"]["ok_runs"]) == (2, 1)
    assert len(data["recent"]) == 5 and data["recent"][0]["duration_ms"] == 900  # newest first


def test_the_activity_never_exposes_prompts_or_hashes(logged_in, session_factory):
    client, _ = logged_in
    add_runs(session_factory, "merchant", [1000])
    run = client.get("/api/ai/activity").json()["recent"][0]
    assert set(run) == {"at", "purpose", "model", "duration_ms", "ok"}  # nothing else is sent


def test_a_real_naming_call_shows_up_with_its_time(loaded, session_factory, test_settings):  # noqa: F811
    client, _ = loaded
    run_naming(session_factory, test_settings, fake_ollama([{"results": []}], []))
    summary = client.get("/api/ai/activity").json()["summary"]
    assert [s["purpose"] for s in summary] == ["merchant"] and summary[0]["runs"] == 1


def test_the_estimate_comes_from_recent_call_times(logged_in, session_factory):
    client, _ = logged_in
    with session_factory() as db:
        none_yet = ai_activity.progress(db, 1, merchants.JOB_TYPE, "merchant", 45, 15, 90)
        assert none_yet.eta_s is None and none_yet.avg_call_s is None  # no history: no guess

    add_runs(session_factory, "merchant", [8000, 12000])  # average 10 s
    with session_factory() as db:
        p = ai_activity.progress(db, 1, merchants.JOB_TYPE, "merchant", 45, 15, 90)
    assert p.avg_call_s == 10.0
    assert p.eta_s == 30  # 45 descriptions = 3 calls of 15
    with session_factory() as db:
        capped = ai_activity.progress(db, 1, merchants.JOB_TYPE, "merchant", 500, 15, 90)
    assert capped.eta_s == 60  # a job covers at most 90: 6 calls


def test_unusable_calls_do_not_skew_the_average(logged_in, session_factory):
    add_runs(session_factory, "merchant", [10000])
    add_runs(session_factory, "merchant", [1], ok=False)
    with session_factory() as db:
        assert ai_activity.avg_call_ms(db, "merchant") == 10000


def test_a_queued_then_running_job_reports_elapsed_time(loaded, session_factory, test_settings):  # noqa: F811
    test_settings.llm_classify_enabled = True
    client, _ = loaded
    status = client.get("/api/merchants/status").json()
    assert status["progress"]["running"] is False and status["progress"]["queued"] is True  # queued after upload
    assert status["ai_enabled"] is True and status["unnamed"] >= 1

    now = datetime.now(timezone.utc)
    with session_factory() as db:
        job = db.scalar(select(Job).where(Job.type == merchants.JOB_TYPE))
        job.status, job.locked_at = "running", now - timedelta(seconds=42)
        db.commit()
        p = ai_activity.progress(db, 1, merchants.JOB_TYPE, "merchant", 3, 15, 90, now=now)
    assert p.running and not p.queued and p.elapsed_s == 42


def test_no_job_means_idle(logged_in):
    client, _ = logged_in
    p = client.get("/api/merchants/status").json()["progress"]
    assert p == {"running": False, "queued": False, "elapsed_s": None, "eta_s": None, "waiting": 0, "avg_call_s": None}


def test_the_categorisation_status_carries_progress_too(loaded):  # noqa: F811
    client, _ = loaded
    progress = client.get("/api/categorization/status").json()["progress"]
    assert set(progress) == {"running", "queued", "elapsed_s", "eta_s", "waiting", "avg_call_s"}
    assert BATCH_SIZE > 0 and MAX_STEMS_PER_JOB > 0


def test_a_search_says_how_long_it_took(seeded, session_factory, test_settings):  # noqa: F811
    client = seeded
    token = client.get("/api/auth/me").json()["csrf_token"]
    body = client.post("/api/search/interpret", json={"query": "fuel over 5k"}, headers={"X-CSRF-Token": token}).json()
    assert body["took_ms"] >= 0 and body["model_ms"] is None  # code alone: the model was not asked

    test_settings.llm_classify_enabled = True
    with session_factory() as db:
        result = search.interpret(
            db, test_settings, 1, "coffee shops",
            transport=fake_ollama([{"category": None, "keyword": None}], []),
        )  # fmt: skip
    assert result.model_ms is not None and result.model_ms >= 0
