"""Synthetic fixtures. Everything here is invented: no real statement, name, account
number or amount. Real statements must never be used in tests or committed."""

import pymupdf

FAKE_ACCOUNT = "9990001111"  # obviously fake

HEADERS = ["PARTICULARS", "PAYMENTS", "RECEIPTS", "BALANCE"]


def boc_lines(
    statement_date: str = "30/09/2022",
    opening: tuple[str, str] | None = ("30/08", "1000.00"),
    rows: list[tuple] | None = None,
    closing: str | None = "900.00",
    account: str | None = None,
    account_style: str = "inline",
    bank_name: bool = True,
    summary: tuple | None = None,
) -> list[str]:
    """One table cell per line, like the text PyMuPDF extracts from a BOC statement.

    rows: (dd/mm, description or [description lines], *amount columns). Normally
    amount and balance; fewer or more build deliberately broken rows.
    """
    if rows is None:
        rows = [("05/09", "ATM CASH WITHDRAWAL", "100.00", "900.00")]

    lines: list[str] = []
    if bank_name:
        lines.append("BANK OF CEYLON")
    lines.append("STATEMENT OF ACCOUNT")
    lines.append(f"DATE: {statement_date}")
    if account and account_style == "inline":
        lines.append(f"A/C No: {account}")
    elif account and account_style == "label":
        lines += ["ACCOUNT NO", account]
    lines += HEADERS

    if opening:
        lines += [opening[0], "BALANCE B/F", opening[1]]

    for date, description, *amounts in rows:
        lines.append(date)
        lines += [description] if isinstance(description, str) else list(description)
        lines += amounts

    if closing is not None:
        lines += [statement_date[:5], "BALANCE C/F", closing]

    if summary:  # (deposit count, deposit total, withdrawal count, withdrawal total)
        deposits, deposit_total, withdrawals, withdrawal_total = summary
        lines += [
            "TOTAL UNREALIZED CHEQUES", ".00",
            "TOTAL DEPOSITS", f"{deposits} item(s)", deposit_total,
            "TOTAL WITHDRAWALS", f"{withdrawals} item(s)", withdrawal_total,
            "END OF STATEMENT",
        ]  # fmt: skip
    return lines


def to_pages(lines: list[str]) -> list[str]:
    return ["\n".join(lines)]


def boc_two_pages(first: list[str], second: list[str], total: int = 2) -> list[str]:
    """Page 2 repeats the column headers and carries a page footer, as real
    multi-page statements do."""
    page_two = HEADERS + second + [f"Page 2 of {total}"]
    return ["\n".join(first + ["Page 1 of 2"]), "\n".join(page_two)]


def pdf_from_pages(pages: list[list[str]] | list[str], password: str | None = None) -> bytes:
    """A real PDF whose text layer holds one line per entry (each on its own y)."""
    doc = pymupdf.open()
    for page_lines in pages:
        if isinstance(page_lines, str):
            page_lines = page_lines.splitlines()
        page = doc.new_page()
        for index, line in enumerate(page_lines):
            page.insert_text((40, 40 + 12 * index), line, fontsize=9)
    try:
        if password:
            return doc.tobytes(
                encryption=pymupdf.PDF_ENCRYPT_AES_256,
                user_pw=password,
                owner_pw=password + "-owner",
            )
        return doc.tobytes()
    finally:
        doc.close()


def boc_pdf(**kwargs) -> bytes:
    return pdf_from_pages([boc_lines(**kwargs)])


def upload(client, csrf, data: bytes, name: str = "statement.pdf", **form):
    return client.post(
        "/api/documents",
        files={"file": (name, data, "application/pdf")},
        data=form,
        headers={"X-CSRF-Token": csrf},
    )
