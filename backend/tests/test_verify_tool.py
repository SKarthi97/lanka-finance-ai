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
