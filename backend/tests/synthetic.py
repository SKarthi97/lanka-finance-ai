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


def hnb_lines(
    opening: tuple[str, str] | None = ("01.10.26", "1,000.00"),
    rows: list[tuple] | None = None,
    closing: tuple[str, str] | None = ("31-10-2026", "900.00"),
    totals: tuple[str, str] | None = None,
    account: str | None = None,
    page_number: int = 1,
    footer: bool = True,
) -> list[str]:
    """One table row per line, like the text PyMuPDF extracts from an HNB statement.

    rows: (dd.mm.yy, reference or "", description, amount, balance); a description may be a
    list of lines (wrapped). The column headings and TOTAL labels are images on real
    statements, so they are not in the text.
    """
    if rows is None:
        rows = [("15.10.26", "SD100001", "SYNTHETIC SHOP PURCHASE", "100.00", "900.00")]

    lines = [str(page_number), "MR. SYNTHETIC PERSON", "NO 1 TEST ROAD COLOMBO"]
    lines.append(f"TEST CITY {account}" if account else "TEST CITY")
    lines.append("LKR")
    if opening:
        lines.append(f"{opening[0]} B/F {opening[1]}")
    for day, ref, description, amount, balance in rows:
        parts = [description] if isinstance(description, str) else list(description)
        # The amounts share the row's first line; a wrapped description continues below it.
        first = " ".join(filter(None, [day, ref, parts[0], amount, balance]))
        lines.append(first)
        lines += parts[1:]
    if totals:
        lines.append(f"{totals[0]} {totals[1]}")
    if closing:
        lines.append(f"{closing[0]} {closing[1]}")
    if footer:
        lines += [
            "HNB is a member of the SL Deposit Insurance Scheme operating under CBSL.",
            "This cover will apply for eligible deposits up to Rs.1.1 Mn. per depositor.",
        ]
    return lines


def commercial_lines(
    opening: tuple[str, str] | None = ("01/10/26", "1,000.00"),
    rows: list[tuple] | None = None,
    closing: tuple[str, str] | None = ("31/10/26", "900.00"),
    totals: tuple[tuple[int, str], tuple[int, str]] | None = None,
    account: str | None = None,
    page_number: int = 1,
    footer: bool = True,
) -> list[str]:
    """One value per line, like the text PyMuPDF extracts from a Commercial Bank statement.

    rows: (dd/mm/yy, description, amount, balance) where the balance is "1,000.00 CR" or a
    bare figure (CR is added). Opening, closing and totals follow the real layout; the logo,
    headings and footer are images on real statements, so they are not in the text.
    """
    if rows is None:
        rows = [("15/10/26", "SYNTHETIC SHOP PURCHASE", "100.00", "900.00")]

    def balance_text(value: str) -> str:
        return value if value.upper().endswith(("CR", "DR")) else f"{value} CR"

    lines = ["31/10/26", "LKR"]
    if account:
        lines.append(account)
    lines += ["MR SYNTHETIC PERSON", "NO 1 TEST ROAD", "COLOMBO", f"PAGE {page_number} OF 1"]
    if opening:
        lines += [opening[0], "OPENING BALANCE", balance_text(opening[1])]
    for day, description, amount, balance in rows:
        lines += [day, description, amount, balance_text(balance)]
    if closing:
        lines += [closing[0], "CLOSING BALANCE", balance_text(closing[1])]
    if totals:
        (deposit_count, deposit_total), (withdrawal_count, withdrawal_total) = totals
        lines += [
            f"TOTAL DEPOSITS - {deposit_count} ITEMS",
            deposit_total,
            f"TOTAL WITHDRAWALS - {withdrawal_count} ITEMS",
            withdrawal_total,
        ]
    if footer:
        lines += ["TELEPHONE NO. 0112 000 000"]
    return lines


def sampath_lines(
    opening: tuple[str, str] | None = ("22DEC2025", "1,000.00Cr"),
    rows: list[tuple] | None = None,
    closing: tuple[str, str] | None = ("31Dec2025", "900.00Cr"),
    totals: tuple[str, str] | None = None,
    period: tuple[str, str] | None = ("22-12-2025", "31-12-2025"),
    account: str | None = None,
    page_number: int = 1,
) -> list[str]:
    """One table row per line, like the text PyMuPDF extracts from a Sampath statement.

    rows: (ddMonyy, branch, particulars, amount, balance), balance with its Cr/Dr suffix.
    The logo, title and column headings are images on real statements.
    """
    if rows is None:
        rows = [("23Dec25", "NSC", "SYNTHETIC SHOP", "100.00", "900.00Cr")]
    lines = ["TO:", "MR. SYNTHETIC PERSON", "NO 1 TEST ROAD", "TEST CITY"]
    lines.append(f"{account} LKR PAGE_NO: {page_number}" if account else f"LKR PAGE_NO: {page_number}")
    if period:
        lines.append(f"FOR THE PERIOD : {period[0]} to {period[1]} DATE: 01-01-2026")
    if opening:
        lines.append(f"{opening[0]} {opening[1]}")
    for day, branch, particulars, amount, balance in rows:
        lines.append(f"{day} {branch} {particulars} {amount} {balance}")
    if closing:
        lines.append(f"{closing[0]} C/F {closing[1]}")
    lines.append("-" * 60)
    if totals:
        lines.append(f"TOTAL : {totals[0]} {totals[1]}")
        lines.append("-" * 60)
    return lines


def commercial_quarterly_lines(
    opening: tuple[str, str] | None = ("30/06/26", "1,000.00"),
    rows: list[tuple] | None = None,
    closing: tuple[str, str] | None = ("30/09/26", "1,008.00"),
    totals: tuple[str, str] | None = ("2.00", "10.00"),
    counts: tuple[int, int] | None = (1, 1),
    account: str | None = None,
    one_line_dates: bool = True,
) -> list[str]:
    """The quarterly Commercial layout: bare balances, posting + effective dates (on one line
    or two), the opening figure before its label, and the closing figures before the counts.

    rows: ("31 Jul 2026", description, amount, balance). totals = (payments, receipts).
    """
    if rows is None:
        rows = [
            ("31 Jul 2026", "SYNTHETIC INTEREST", "10.00", "1,010.00"),
            ("31 Jul 2026", "SYNTHETIC TAX", "2.00", "1,008.00"),
        ]
    lines = [
        "SYNTHETIC CITY BRANCH",
        "STATEMENT OF ACCOUNT",
        "STATEMENT DATE 30/09/26",
        "In Account With",
        "Commercial Bank Of Ceylon PLC",
        "MR SYNTHETIC PERSON",
        f"ACCOUNT NO {account}" if account else "ACCOUNT NO",
        "CURRENCY LKR",
        "DATE",
        "PARTICULARS",
        "RECEIPTS",
        "BALANCE",
        "PAYMENTS",
        "DATE",
    ]
    if opening:
        lines += [opening[1], f"BALANCE AS OF {opening[0]}"]
    for day, description, amount, balance in rows:
        lines += [f"{day} {day}"] if one_line_dates else [day, day]
        lines += [description, amount, balance]
    if closing:
        lines.append(f"CLOSING BALANCE AS OF {closing[0]}")
        if totals:
            lines += [totals[0], totals[1]]
        lines.append(closing[1])
    if counts:
        lines += [f"TOTAL DEPOSITS {counts[0]} ITEMS", f"TOTAL WITHDRAWALS {counts[1]} ITEMS"]
    lines += [
        "INTEREST EARNED FOR FINANCIAL YEAR TO",
        "DATE",
        "INTEREST WITHHELD FOR FINANCIAL YEAR",
        "TO DATE",
        "10.00",
        "2.00",
        "* INCLUDES ADVANCE INCOME TAX IN THE",
        "AMOUNT OF",
        "2.00",
        "PAGE 1",
        "THE ITEMS AND BALANCES ON THIS STATEMENT SHOULD BE VERIFIED",
    ]
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
