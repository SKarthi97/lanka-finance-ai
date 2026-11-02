import re

from datetime import datetime
from decimal import Decimal

from parsers.common import parse_money


def parse_boc_statement(text, source):

    statement_match = re.search(
        r"DATE:\s*(\d{2}/\d{2}/\d{4})",
        text,
        re.IGNORECASE
    )

    if not statement_match:

        raise ValueError(
            "BOC statement date not found."
        )

    statement_date = datetime.strptime(
        statement_match.group(1),
        "%d/%m/%Y"
    ).date()

    upper_text = text.upper()

    required_headers = [
        "PARTICULARS",
        "PAYMENTS",
        "RECEIPTS",
        "BALANCE"
    ]

    if not all(
        header in upper_text
        for header in required_headers
    ):

        raise ValueError(
            "This PDF does not match the expected BOC format."
        )

    date_pattern = re.compile(
        r"^\d{2}/\d{2}$"
    )

    amount_pattern = re.compile(
        r"^\(?-?\d[\d,]*\.\d{2}\)?$"
    )

    transactions = []
    warnings = []

    opening_balance = None
    closing_balance = None
    previous_balance = None

    current_date = None
    current_lines = []

    def process_block(date_text, lines):

        nonlocal opening_balance
        nonlocal previous_balance

        if not date_text:
            return

        amounts = []
        descriptions = []

        for line in lines:

            if amount_pattern.fullmatch(line):

                amount = parse_money(line)

                if amount is not None:
                    amounts.append(amount)

            else:

                descriptions.append(line)

        description = " ".join(descriptions).strip()
        description_upper = description.upper()

        if not description:
            return

        # Opening balance

        if "BALANCE B/F" in description_upper:

            if len(amounts) == 1:

                opening_balance = amounts[0]
                previous_balance = opening_balance

            else:

                warnings.append(
                    "Unable to identify opening balance."
                )

            return

        # Ignore statement summaries

        if "TOTAL " in description_upper:
            return

        if "UNREALIZED CHEQUES" in description_upper:
            return

        # Expect transaction amount and running balance

        if len(amounts) != 2:

            warnings.append(
                f"Unexpected amount columns: {description}"
            )

            return

        transaction_amount = amounts[0]
        current_balance = amounts[1]

        if transaction_amount < 0:

            warnings.append(
                f"Negative transaction amount: {description}"
            )

            return

        # Transaction date

        day, month = map(
            int,
            date_text.split("/")
        )

        transaction_year = statement_date.year

        try:

            transaction_date = datetime(
                transaction_year,
                month,
                day
            ).date()

            if transaction_date > statement_date:

                transaction_date = datetime(
                    transaction_year - 1,
                    month,
                    day
                ).date()

        except ValueError:

            warnings.append(
                f"Invalid transaction date: {date_text}"
            )

            return

        # Identify debit and credit

        debit = Decimal("0.00")
        credit = Decimal("0.00")

        review_required = False

        if previous_balance is None:

            review_required = True

            warnings.append(
                f"Opening balance unavailable: {description}"
            )

        else:

            difference = (
                current_balance - previous_balance
            )

            if difference > 0:

                credit = transaction_amount

            elif difference < 0:

                debit = transaction_amount

            else:

                review_required = True

                warnings.append(
                    f"No balance movement: {description}"
                )

            if abs(
                abs(difference) - transaction_amount
            ) > Decimal("0.02"):

                review_required = True

                warnings.append(
                    f"Balance mismatch: {description}"
                )

        transactions.append({

            "date": transaction_date.isoformat(),

            "description": description,

            "debit": float(debit),

            "credit": float(credit),

            "balance": float(current_balance),

            "category": "Uncategorized",

            "source": source,

            "review_required": review_required

        })

        previous_balance = current_balance

    # Read PDF text

    reading_closing_balance = False

    for raw_line in text.splitlines():

        line = raw_line.strip()

        if not line:
            continue

        if date_pattern.fullmatch(line):

            process_block(
                current_date,
                current_lines
            )

            current_date = line
            current_lines = []

            reading_closing_balance = False

            continue

        if "BALANCE C/F" in line.upper():

            process_block(
                current_date,
                current_lines
            )

            current_date = None
            current_lines = []

            reading_closing_balance = True

            continue

        if reading_closing_balance:

            if amount_pattern.fullmatch(line):

                closing_balance = parse_money(line)

                reading_closing_balance = False

            continue

        if (
            "TOTAL DEPOSITS" in line.upper()
            or "TOTAL WITHDRAWALS" in line.upper()
            or "TOTAL UNREALIZED CHEQUES" in line.upper()
        ):

            process_block(
                current_date,
                current_lines
            )

            current_date = None
            current_lines = []

            continue

        if current_date:

            current_lines.append(line)

    process_block(
        current_date,
        current_lines
    )

    return (
        transactions,

        float(opening_balance)
        if opening_balance is not None else None,

        float(closing_balance)
        if closing_balance is not None else None,

        warnings
    )