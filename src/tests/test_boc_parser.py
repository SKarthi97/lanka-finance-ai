from parsers.boc_parser import parse_boc_statement


def test_boc_parser():

    sample_text = """
    DATE: 30/09/2022

    PARTICULARS
    PAYMENTS
    RECEIPTS
    BALANCE

    30/08
    BALANCE B/F
    1000.00

    05/09
    ATM CASH WITHDRAWAL
    100.00
    900.00

    30/09
    BALANCE C/F
    900.00
    """

    (
        transactions,
        opening_balance,
        closing_balance,
        warnings
    ) = parse_boc_statement(
        sample_text,
        "test.pdf"
    )

    assert opening_balance == 1000.00

    assert closing_balance == 900.00

    assert len(transactions) == 1

    assert transactions[0]["debit"] == 100.00

    assert transactions[0]["credit"] == 0.00