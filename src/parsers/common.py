from decimal import Decimal, InvalidOperation


def parse_money(value):

    value = (
        value.strip()
        .replace(",", "")
        .replace(" ", "")
    )

    negative = (
        value.startswith("(")
        and value.endswith(")")
    )

    value = value.replace("(", "").replace(")", "")

    try:

        amount = Decimal(value)

        if negative:
            amount = -amount

        return amount

    except InvalidOperation:

        return None