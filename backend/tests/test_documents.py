import hashlib
from pathlib import Path

import pymupdf
from sqlalchemy import select

from app.models import AuditLog, Document, Job

from .conftest import make_pdf


def upload(client, csrf, data, name="statement.pdf", **form):
    return client.post(
        "/api/documents",
        files={"file": (name, data, "application/pdf")},
        data=form,
        headers={"X-CSRF-Token": csrf},
    )


def test_upload_requires_login(client):
    response = client.post(
        "/api/documents", files={"file": ("a.pdf", make_pdf(), "application/pdf")}
    )
    assert response.status_code == 401


def test_upload_requires_csrf(logged_in):
    client, _ = logged_in
    response = client.post(
        "/api/documents", files={"file": ("a.pdf", make_pdf(), "application/pdf")}
    )
    assert response.status_code == 403


def test_upload_stores_file_and_queues_job(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    data = make_pdf()

    response = upload(client, csrf, data, bank_code="boc")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["bank_code"] == "boc"
    assert body["is_encrypted"] is False
    assert body["page_count"] == 1
    assert len(body["sha256"]) == 64

    with session_factory() as db:
        document = db.scalar(select(Document))
        job = db.scalar(select(Job))
        assert job.type == "inspect_document"
        assert job.status == "queued"
        assert job.document_id == document.id
        assert job.payload is None  # nothing sensitive travels through the queue

    stored = (
        Path(test_settings.documents_dir) / document.storage_path
    )
    assert stored.read_bytes() == data


def test_duplicate_upload_is_rejected_without_second_job(logged_in, session_factory):
    client, csrf = logged_in
    data = make_pdf()

    first = upload(client, csrf, data)
    second = upload(client, csrf, data, name="renamed.pdf")

    assert first.status_code == 202
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "duplicate"
    assert detail["document_id"] == first.json()["id"]
    assert detail["original_filename"] == "statement.pdf"  # says WHICH upload matched
    assert detail["document_status"] == "queued"
    assert detail["uploaded_at"]

    with session_factory() as db:
        assert len(db.scalars(select(Document)).all()) == 1
        assert len(db.scalars(select(Job)).all()) == 1


def test_different_files_are_both_accepted(logged_in):
    client, csrf = logged_in
    assert upload(client, csrf, make_pdf(["First statement " * 5])).status_code == 202
    assert upload(client, csrf, make_pdf(["Second statement " * 5])).status_code == 202


def test_rejects_non_pdf_by_magic_bytes(logged_in):
    client, csrf = logged_in
    response = upload(client, csrf, b"MZ this is not a pdf", name="evil.pdf")
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "not_pdf"


def test_rejects_corrupt_pdf(logged_in):
    client, csrf = logged_in
    response = upload(client, csrf, b"%PDF-1.7 garbage that is not a real pdf")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unreadable_pdf"


def test_rejects_oversized_file(logged_in, test_settings):
    client, csrf = logged_in
    test_settings.max_upload_mb = 1
    response = upload(client, csrf, b"%PDF-" + b"0" * (1024 * 1024 + 1))
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "too_large"


def test_rejects_too_many_pages(logged_in, test_settings):
    client, csrf = logged_in
    test_settings.max_pages = 1
    response = upload(client, csrf, make_pdf(["page one " * 10, "page two " * 10]))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "too_many_pages"


def test_rejects_unknown_bank(logged_in):
    client, csrf = logged_in
    response = upload(client, csrf, make_pdf(), bank_code="nope")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unknown_bank"


def test_encrypted_pdf_needs_correct_password(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    data = make_pdf(password="s3cret-pw")

    missing = upload(client, csrf, data)
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "password_required"

    wrong = upload(client, csrf, data, password="wrong")
    assert wrong.status_code == 422
    assert wrong.json()["detail"]["code"] == "password_incorrect"

    # Failed attempts leave nothing behind.
    with session_factory() as db:
        assert db.scalars(select(Document)).all() == []
        assert db.scalars(select(Job)).all() == []

    ok = upload(client, csrf, data, password="s3cret-pw")
    assert ok.status_code == 202
    assert ok.json()["is_encrypted"] is True


def test_encrypted_pdf_is_stored_decrypted_and_password_is_not_persisted(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    data = make_pdf(password="s3cret-pw")
    upload(client, csrf, data, password="s3cret-pw")

    with session_factory() as db:
        document = db.scalar(select(Document))
        job = db.scalar(select(Job))
        audit = " ".join(str(a.detail) for a in db.scalars(select(AuditLog)))

    stored = pymupdf.open(
        Path(test_settings.documents_dir) / document.storage_path
    )
    assert not stored.needs_pass  # PyMuPDF returns 0/1, not a bool
    stored.close()

    # The duplicate hash is of the original upload, not the decrypted copy.
    assert document.sha256 == hashlib.sha256(data).hexdigest()

    for place in (str(job.payload), audit, document.error or ""):
        assert "s3cret-pw" not in place


def test_list_and_get_documents(logged_in):
    client, csrf = logged_in
    created = upload(client, csrf, make_pdf()).json()

    listed = client.get("/api/documents").json()
    assert [d["id"] for d in listed] == [created["id"]]

    detail = client.get(f"/api/documents/{created['id']}").json()
    assert detail["id"] == created["id"]
    assert detail["pages"] == []  # not inspected yet

    assert client.get("/api/documents/9999").status_code == 404


def test_documents_require_login(client):
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/documents/1").status_code == 401


def test_same_filename_with_different_content_is_accepted(logged_in):
    """Duplicates are detected by content hash, never by filename."""
    client, csrf = logged_in
    january = make_pdf(["January statement " * 5])
    february = make_pdf(["February statement " * 5])

    first = upload(client, csrf, january, name="Statement.pdf")
    second = upload(client, csrf, february, name="Statement.pdf")

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["sha256"] != second.json()["sha256"]


def test_delete_allows_reupload_of_same_file(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    data = make_pdf()
    created = upload(client, csrf, data).json()

    assert upload(client, csrf, data).status_code == 409

    deleted = client.delete(
        f"/api/documents/{created['id']}", headers={"X-CSRF-Token": csrf}
    )
    assert deleted.status_code == 204
    assert client.get(f"/api/documents/{created['id']}").status_code == 404

    with session_factory() as db:
        assert db.scalars(select(Document)).all() == []
        assert db.scalars(select(Job)).all() == []  # its queued job went with it
        actions = [a.action for a in db.scalars(select(AuditLog))]
        assert "document.delete" in actions

    stored = Path(test_settings.documents_dir) / "1" / f"{created['sha256']}.pdf"
    assert not stored.exists()  # the file was removed with the record
    assert upload(client, csrf, data).status_code == 202


def test_delete_requires_csrf_and_login(logged_in, client):
    c, csrf = logged_in
    created = upload(c, csrf, make_pdf()).json()

    assert c.delete(f"/api/documents/{created['id']}").status_code == 403
    assert (
        c.delete("/api/documents/9999", headers={"X-CSRF-Token": csrf}).status_code
        == 404
    )

    c.cookies.clear()
    assert c.delete(f"/api/documents/{created['id']}").status_code == 401


def test_cannot_delete_document_while_processing(logged_in, session_factory):
    client, csrf = logged_in
    created = upload(client, csrf, make_pdf()).json()

    with session_factory() as db:
        db.get(Document, created["id"]).status = "processing"
        db.commit()

    response = client.delete(
        f"/api/documents/{created['id']}", headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "busy"
