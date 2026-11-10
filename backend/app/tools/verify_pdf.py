"""Redacted local check of a real bank statement.

Prints only counts, pass/fail results and issue codes. It never prints amounts, dates,
descriptions, names or account numbers, so the output is safe to share. Nothing is
written to the database and the file is not copied.

Run it inside the worker container (nothing to install on the host):

  docker compose run --rm -v "<folder with the PDF>:/samples:ro" worker \
      python -m app.tools.verify_pdf /samples/Statement.pdf

Add --shape to also print the page layout with every digit and letter masked, which
helps when a real statement's layout differs from what the parser expects.
Review the output before sharing it.
"""

import argparse
import getpass
import re
import sys
from collections import Counter

import pymupdf

from app.adapters.base import ParseError
from app.adapters.registry import ADAPTERS, IDENTIFY_THRESHOLD, select_adapter
from app.services.validation import validate

# Structural words that identify a column or marker, never personal data.
KEEP_WORDS = {
    "PARTICULARS", "PAYMENTS", "RECEIPTS", "BALANCE", "B/F", "C/F", "TOTAL",
    "DEPOSITS", "WITHDRAWALS", "UNREALIZED", "CHEQUES", "DATE", "DATE:",
    "ACCOUNT", "A/C", "NO", "NO.", "PAGE", "OF", "STATEMENT", "BANK", "CEYLON",
    # Generic column and marker wording used by other banks (HNB and others).
    "DEBIT", "CREDIT", "DR", "CR", "DESCRIPTION", "NARRATION", "REFERENCE", "REF",
    "VALUE", "OPENING", "CLOSING", "BRANCH", "TRANSACTION", "TRANSACTIONS",
    "AMOUNT", "FROM", "TO", "PERIOD", "CURRENCY", "LKR", "HNB", "HATTON", "NATIONAL",
    "CARRIED", "BROUGHT", "FORWARD", "SUMMARY", "ITEMS",
}  # fmt: skip


def mask_token(token: str) -> str:
    if token.upper() in KEEP_WORDS:
        return token.upper()
    masked = re.sub(r"\d", "9", token)
    masked = re.sub(r"[A-Z]", "A", masked)
    return re.sub(r"[a-z]", "a", masked)


def mask_line(line: str) -> str:
    return " ".join(mask_token(token) for token in line.split())


def layout_shape(pages: list[str], max_lines: int = 150) -> list[str]:
    """Masked layout, with runs of identical lines collapsed as 'line  (xN)'."""
    out: list[str] = []
    for number, text in enumerate(pages, start=1):
        out.append(f"--- page {number} ---")
        previous, run = None, 0
        shown = 0
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            masked = mask_line(line)
            if masked == previous:
                run += 1
                continue
            if previous is not None:
                out.append(previous + (f"  (x{run})" if run > 1 else ""))
                shown += 1
            previous, run = masked, 1
            if shown >= max_lines:
                out.append("... (truncated)")
                previous = None
                break
        if previous is not None:
            out.append(previous + (f"  (x{run})" if run > 1 else ""))
    return out


def marker_blocks(pages: list[str], before: int = 3, after: int = 6, per_marker: int = 3) -> list[str]:
    """Masked lines around each BALANCE B/F and BALANCE C/F marker.

    Small and focused: shows how the opening/closing balance rows are laid out without
    printing the whole statement.
    """
    out: list[str] = []
    for marker in ("BALANCE B/F", "BALANCE C/F"):
        found = 0
        total = sum(
            1 for text in pages for raw in text.splitlines() if marker in raw.upper()
        )
        out.append(f"== {marker}: {total} occurrence(s); first {min(total, per_marker)} shown ==")
        for number, text in enumerate(pages, start=1):
            lines = [raw.strip() for raw in text.splitlines() if raw.strip()]
            for index, line in enumerate(lines):
                if marker not in line.upper() or found >= per_marker:
                    continue
                found += 1
                out.append(f"--- page {number}, line {index + 1} ---")
                for offset in range(max(0, index - before), min(len(lines), index + after + 1)):
                    arrow = ">>" if offset == index else "  "
                    out.append(f"{arrow} {mask_line(lines[offset])}")
    return out


def load_pages(path: str, password: str | None) -> list[str]:
    pdf = pymupdf.open(path)
    try:
        if pdf.needs_pass:
            if password is None:
                password = getpass.getpass("PDF password (not shown, not stored): ")
            if not pdf.authenticate(password):
                raise SystemExit("Incorrect PDF password.")
        return [page.get_text("text") for page in pdf]
    finally:
        pdf.close()


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _yn(value: bool | None) -> str:
    return "unknown" if value is None else yes_no(value)


def report(
    pages: list[str], bank_code: str | None, shape: bool, out=print, blocks: bool = False
) -> None:
    out("== Redacted statement check ==")
    out("(no amounts, dates, descriptions or account numbers are printed)")
    out(f"pages: {len(pages)}")
    out(f"text characters per page: {[len(''.join(p.split())) for p in pages]}")

    scores = {code: adapter.identify(pages) for code, adapter in ADAPTERS.items()}
    out(f"adapter scores: {scores} (threshold {IDENTIFY_THRESHOLD})")

    adapter = select_adapter(pages, bank_code)
    if adapter is None:
        out("adapter selected: none (unsupported layout)")
    else:
        out(f"adapter selected: {adapter.code}")
        try:
            parsed = adapter.parse(pages)
        except ParseError as error:
            out(f"parse: FAILED ({error.code})")
        else:
            rows = parsed.transactions
            result = validate(parsed)
            out("parse: ok")
            out(
                f"rows parsed: {len(rows)} "
                f"(debit rows: {sum(1 for r in rows if r.debit > 0)}, "
                f"credit rows: {sum(1 for r in rows if r.credit > 0)})"
            )
            out(f"rows per page: {dict(sorted(Counter(r.page_no for r in rows).items()))}")
            out(f"opening balance found: {yes_no(parsed.opening_balance is not None)}")
            out(f"closing balance found: {yes_no(parsed.closing_balance is not None)}")
            out(f"period start found: {yes_no(parsed.period_start is not None)}")
            out(f"account number found: {yes_no(bool(parsed.account_number))}")
            out(f"reconciled: {yes_no(result.reconciled)} (confidence {result.confidence})")
            for name, counts in result.checks.items():
                out(f"check {name}: passed {counts['passed']}, failed {counts['failed']}")
            histogram = Counter(issue.code for issue in result.issues)
            out(f"issue codes: {dict(histogram) or 'none'}")

            # Date sanity, as counts only: no year or date is ever printed.
            if rows:
                per_year = Counter(r.date.year for r in rows)
                out(f"years spanned: {len(per_year)} (rows per year, oldest first: "
                    f"{[per_year[y] for y in sorted(per_year)]})")
                gaps = [(b.date - a.date).days for a, b in zip(rows, rows[1:], strict=False)]
                out(f"largest gap between consecutive rows (days): {max(gaps, default=0)}")

            # What the statement says about itself vs what was extracted: counts and
            # yes/no only. The amounts themselves are never printed.
            if not result.declared:
                out("statement totals: not found")
            window = result.declared_window
            if window:
                if window["covers"] == "all":
                    out(f"statement totals cover: all {window['rows']} rows")
                elif window["covers"] == "last_rows":
                    out(
                        f"statement totals cover: only the last {window['rows']} of "
                        f"{len(rows)} rows (from page {window['from_page']})"
                    )
                else:
                    out("statement totals cover: no combination of rows matches")
            for key, d in result.declared.items():
                out(
                    f"statement totals {key}: items declared {d['declared_count']}, "
                    f"found {d['found_count']}, count match {_yn(d['count_match'])}, "
                    f"total match {_yn(d['total_match'])}"
                )

    if blocks:
        out("")
        out("== Balance-row layout (masked) ==")
        for line in marker_blocks(pages):
            out(line)

    if shape:
        out("")
        out("== Layout shape (digits -> 9, letters -> A/a, structural words kept) ==")
        for line in layout_shape(pages):
            out(line)


def main(argv: list[str] | None = None, out=print) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pdf", help="path to the statement PDF")
    parser.add_argument("--bank", default=None, help="force an adapter, e.g. boc")
    parser.add_argument("--shape", action="store_true", help="also print the masked layout")
    parser.add_argument(
        "--blocks",
        action="store_true",
        help="print only the masked lines around BALANCE B/F and C/F (short)",
    )
    parser.add_argument("--password", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    pages = load_pages(args.pdf, args.password)
    report(pages, args.bank, args.shape, out, blocks=args.blocks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
