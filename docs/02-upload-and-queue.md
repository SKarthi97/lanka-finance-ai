# PDF Upload and Job Queue

Status: implemented (Phase 1). Follows `00-architecture.md` sections 5 and 10.

## Flow

```
Browser -> POST /api/documents (multipart: file, bank_code, password?)
  1. size limit (MAX_UPLOAD_MB) and %PDF- magic-byte check
  2. sha256 of the uploaded bytes; duplicate -> 409 (before any password prompt)
  3. open with PyMuPDF; encrypted -> password required / incorrect -> 422
  4. page limit (MAX_PAGES)
  5. save file to the documents volume, insert documents row + jobs row + audit row
     in ONE database transaction -> 202
Worker -> claims job (FOR UPDATE SKIP LOCKED) -> inspect_document -> status "inspected"
```

## Error codes (`detail.code`)

| HTTP | code | Meaning |
|---|---|---|
| 413 | `too_large` | Over `MAX_UPLOAD_MB` |
| 415 | `not_pdf` | Does not start with `%PDF-` |
| 409 | `duplicate` | Same sha256 already uploaded; `document_id` of the original is returned |
| 422 | `password_required` / `password_incorrect` | Encrypted PDF |
| 422 | `unreadable_pdf` / `empty_pdf` / `too_many_pages` / `unknown_bank` | Other validation |

## Decisions and trade-offs

- **Duplicate key:** SHA-256 of the file exactly as uploaded, unique per `(user_id, sha256)`.
  Enforced by the database constraint, so concurrent identical uploads cannot both win.
- **PDF passwords:** used once in the upload request to open the file. Never stored,
  logged, audited or put in a job payload. Because the worker runs later and must not
  need the password, **encrypted PDFs are stored decrypted** on the `documents` volume.
  The sha256 still refers to the original encrypted upload.
- **Retention (`RETAIN_DOCUMENTS`, default `false`):** the stored PDF is deleted as soon
  as processing succeeds, so plain statement files exist only between upload and
  processing. `documents.file_deleted_at` records the deletion; the sha256 stays, so
  duplicate detection still works. Failed documents keep their file so they can be
  retried. Set `RETAIN_DOCUMENTS=true` while building Phase 2, because extraction needs
  the file. Trade-offs of deleting: no re-extraction after improving an adapter, no
  source-page viewer to verify a row against the original, and no OCR retry. Keep files
  only for documents you may need to audit or reprocess.
- **Phase 2 note:** the delete call currently runs at the end of `inspect_document`.
  Move it to the end of the extraction job when that exists.
- **Queue:** Postgres table `jobs`, no Redis. Claim is committed immediately; a job whose
  worker dies is recovered after `JOB_STALE_AFTER_S` (default 600 s). Failures retry with
  exponential backoff (5 s, 10 s, ...) up to `max_attempts` (default 3), then the job and
  its document become `failed`.
- **First job type, `inspect_document`:** classifies each page as `text`, `mixed`,
  `scanned` or `empty` and stores counts only (no page text). This feeds the OCR decision
  in a later phase.
- **Bank:** the upload form offers Bank of Ceylon (`boc`). Auto-detection comes with the
  adapter registry.

## Operations

```
docker compose logs -f worker      # job lifecycle (ids and types only, no content)
docker compose exec postgres psql -U lanka -d lanka -c "select id,type,status,attempts,last_error from jobs order by id desc limit 10;"
```

## Known limits

- Page inspection only; no transaction extraction yet (Phase 2, BOC adapter).
- No delete/re-process endpoint for documents.
- Next.js may cap request bodies on its `/api` proxy; if large uploads fail at the
  frontend while working directly against the backend, raise the proxy body limit.
