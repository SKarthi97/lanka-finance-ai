
from decimal import Decimal
import pandas as pd


def calculate_statement_summary(
    transactions,
    opening_balance,
    closing_balance
):

    total_debit = sum(
        Decimal(str(item["debit"]))
        for item in transactions
    )

    total_credit = sum(
        Decimal(str(item["credit"]))
        for item in transactions
    )

    calculated_closing = None
    difference = None

    if opening_balance is not None:

        calculated_closing = (
            Decimal(str(opening_balance))
            + total_credit
            - total_debit
        ).quantize(Decimal("0.01"))

    if (
        calculated_closing is not None
        and closing_balance is not None
    ):

        difference = (
            calculated_closing
            - Decimal(str(closing_balance))
        ).quantize(Decimal("0.01"))

    return {
        "total_transactions": len(transactions),
        "total_debit": float(total_debit),
        "total_credit": float(total_credit),

        "calculated_closing": (
            float(calculated_closing)
            if calculated_closing is not None
            else None
        ),

        "actual_closing": closing_balance,

        "difference": (
            float(difference)
            if difference is not None
            else None
        )
    }


def calculate_monthly_summary(transactions):

    if not transactions:
        return pd.DataFrame()

    df = pd.DataFrame(transactions)

    df["date"] = pd.to_datetime(df["date"])

    df["month"] = (
        df["date"].dt.to_period("M").astype(str)
    )

    return (
        df.groupby("month")
        .agg(
            income=("credit", "sum"),
            expenses=("debit", "sum")
        )
        .reset_index()
    )
