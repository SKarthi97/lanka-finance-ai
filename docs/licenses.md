# Licenses and Redistribution

Status: DRAFT. This is an engineering inventory, not legal advice. Every entry marked "verify" must be checked against the exact pinned version before any bundle is distributed (`00-architecture.md` §10, Phase 7).

The offline bundle (images plus model weights) is a redistribution. Personal use on your own machines has lighter obligations than handing the bundle to others.

## Model weights

| Component | License | Notes |
|---|---|---|
| `qwen3:4b` (default) | Apache-2.0 (per architecture doc; verify on the model card for the pinned digest) | Redistribution allowed with license text and notice. |
| Other Qwen3 sizes (1.7B, 8B) | Verify per model card | Do not assume all sizes share a license. |
| Llama-family models | Llama community license | Own terms (attribution, use restrictions). Not bundled by default. |

Rule: only bundle weights after recording the license, source URL and digest here. The pinned digest is also recorded per inference in `model_runs`.

## Runtime software

| Component | License (verify) | Concern |
|---|---|---|
| Ollama | MIT | None expected. |
| PostgreSQL 16 | PostgreSQL License | Permissive. |
| Tesseract OCR and `eng` traineddata | Apache-2.0 | Include notice. |
| FastAPI, Pydantic, SQLAlchemy, Alembic | MIT / MIT / MIT / MIT | Permissive. |
| pdfplumber | MIT | Permissive. |
| **PyMuPDF (MuPDF)** | **AGPL-3.0 or commercial** | **Needs a decision, see below.** |
| pytesseract | Apache-2.0 | Permissive. |
| openpyxl | MIT | Permissive. |
| WeasyPrint / ReportLab | BSD / BSD (ReportLab open-source edition) | Check system libs WeasyPrint pulls in. |
| Next.js, React, Tailwind | MIT | Permissive. |
| pdf.js | Apache-2.0 | Permissive. |
| Argon2 bindings | MIT / Apache-2.0 | Permissive. |
| procrastinate (if chosen) | MIT | Permissive. |

## Open decision: PyMuPDF and AGPL

PyMuPDF is AGPL-3.0 unless a commercial license is bought. For private, single-user use with no distribution this is generally low risk. If the bundle is given to other people, or the app is offered over a network to others, AGPL obligations (source availability) may apply to the whole backend/worker.

Options:
1. Keep PyMuPDF; the project is then AGPL-compatible. Check the repo's `LICENSE`.
2. Replace it with a permissive stack (pdfplumber/pdfminer.six for text, `pypdfium2` for rendering; `pikepdf` for decryption, MPL-2.0). Verify each, and whether password handling and rendering quality are adequate.
3. Buy a commercial license.

Decision: _pending_. Record it here before Phase 1 locks the PDF stack.

## Process

- Generate a dependency license report from the lockfiles (`pip-licenses`, `license-checker`) at each release and commit the output next to this file.
- Pin versions and image digests; licenses can change between releases.
- Ship a `THIRD_PARTY_NOTICES` file inside the offline bundle with the license texts.
- Sample statements and any real financial data are never part of a bundle.
