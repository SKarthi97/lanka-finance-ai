"""The verify tool is used on REAL statements, so its output must stay redacted."""

from app.tools.verify_pdf import layout_shape, main, mask_line

from .synthetic import FAKE_ACCOUNT, boc_lines, boc_pdf, pdf_from_pages

SECRETS = [FAKE_ACCOUNT, "ATM CASH WITHDRAWAL", "SYNTHETIC SHOP", "100.00", "900.00", "1000.00"]


def run(tmp_path, pdf: bytes, *flags: str) -> str:
    path = tmp_path / "s.pdf"
    path.write_bytes(pdf)
    lines: list[str] = []
    assert main([str(path), *flags], out=lines.append) == 0
    return "\n".join(lines)


def test_report_never_contains_statement_values(tmp_path):
    pdf = boc_pdf(
        account=FAKE_ACCOUNT,
        rows=[("05/09", "ATM CASH WITHDRAWAL SYNTHETIC SHOP", "100.00", "900.00")],
    )
    output = run(tmp_path, pdf)

    for secret in SECRETS:
        assert secret not in output
    # ...but it is still informative
    assert "adapter selected: boc" in output
    assert "rows parsed: 1 (debit rows: 1, credit rows: 0)" in output
    assert "reconciled: yes" in output
    assert "account number found: yes" in output  # yes/no only, never the number


def test_shape_mode_masks_digits_and_free_text(tmp_path):
    pdf = boc_pdf(
        account=FAKE_ACCOUNT,
        rows=[("05/09", "ATM CASH WITHDRAWAL SYNTHETIC SHOP", "100.00", "900.00")],
    )
    output = run(tmp_path, pdf, "--shape")

    for secret in SECRETS:
        assert secret not in output
    assert "99/99" in output  # dates keep their shape
    assert "999.99" in output  # amounts keep their shape
    assert "PARTICULARS" in output  # structural words stay readable


def test_mask_line_examples():
    assert mask_line("DATE: 30/09/2022") == "DATE: 99/99/9999"
    assert mask_line("1,234.50") == "9,999.99"
    assert mask_line("Nimal Perera") == "Aaaaa Aaaaaa"
    assert mask_line("BALANCE B/F") == "BALANCE B/F"


def test_layout_shape_collapses_repeated_lines():
    shape = layout_shape(["12.00\n34.00\n56.00\nabc"])
    assert "99.99  (x3)" in shape


def test_unrecognised_layout_is_reported_without_content(tmp_path):
    output = run(tmp_path, pdf_from_pages([["Some other bank", "Account 5551234567"]]))
    assert "adapter selected: none" in output
    assert "5551234567" not in output


def test_failed_parse_prints_only_the_code(tmp_path):
    output = run(tmp_path, pdf_from_pages([boc_lines()[:2] + ["PARTICULARS", "PAYMENTS", "RECEIPTS", "BALANCE"]]))
    assert "parse: FAILED (statement_date_not_found)" in output


def test_blocks_mode_prints_only_masked_balance_rows(tmp_path):
    pdf = boc_pdf(
        account=FAKE_ACCOUNT,
        rows=[("05/09", "ATM CASH WITHDRAWAL SYNTHETIC SHOP", "100.00", "900.00")],
    )
    output = run(tmp_path, pdf, "--blocks")

    assert "BALANCE B/F: 1 occurrence(s)" in output
    assert "BALANCE C/F: 1 occurrence(s)" in output
    assert ">> BALANCE B/F" in output  # the marker row itself is marked
    assert "9999.99" in output  # the opening balance keeps only its shape
    for secret in SECRETS:
        assert secret not in output


def test_report_gives_date_and_totals_checks_without_dates_or_amounts(tmp_path):
    pdf = boc_pdf(
        statement_date="30/06/2022",
        opening=("28/12", "1,000.00"),
        rows=[
            ("31/12", "SYNTHETIC SHOP", "10.00", "990.00"),
            ("06/01", "SYNTHETIC SHOP", "10.00", "980.00"),
            ("30/06", "SYNTHETIC SHOP", "10.00", "970.00"),
        ],
        closing="970.00",
        summary=(0, ".00", 3, "30.00"),
    )
    output = run(tmp_path, pdf)

    assert "years spanned: 2 (rows per year, oldest first: [1, 2])" in output
    assert "largest gap between consecutive rows (days): 175" in output
    assert "statement totals withdrawals: items declared 3, found 3, count match yes, total match yes" in output
    # counts and yes/no only: no year, date or amount is printed
    for leaked in ("2020", "2021", "2022", "990.00", "30.00", "1,000.00"):
        assert leaked not in output


def test_report_says_when_the_statement_has_no_totals(tmp_path):
    output = run(tmp_path, boc_pdf())
    assert "statement totals: not found" in output


def test_report_says_which_rows_the_statement_totals_cover(tmp_path):
    pdf = boc_pdf(
        rows=[
            ("02/09", "SYNTHETIC SHOP", "100.00", "900.00"),
            ("03/09", "SYNTHETIC SALARY", "2,500.00", "3,400.00"),
            ("04/09", "SYNTHETIC SHOP", "500.00", "2,900.00"),
        ],
        closing="2,900.00",
        summary=(1, "2,500.00", 1, "500.00"),
    )
    output = run(tmp_path, pdf)

    assert "statement totals cover: only the last 2 of 3 rows (from page 1)" in output
    for leaked in ("2,500.00", "2,900.00", "500.00"):
        assert leaked not in output
