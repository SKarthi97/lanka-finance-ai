
import streamlit as st
import pandas as pd
import plotly.express as px

from database.db import get_all_transactions


def render_dashboard():

    st.header("Financial Dashboard")

    transactions = get_all_transactions()

    if not transactions:

        st.info(
            "No transactions available. "
            "Upload a bank statement to view your dashboard."
        )

        return

    df = pd.DataFrame(transactions)

    # --------------------------------------------------------
    # STANDARDIZE DATE COLUMN
    # --------------------------------------------------------

    df["transaction_date"] = pd.to_datetime(
        df["transaction_date"],
        errors="coerce"
    )

    df = df.dropna(subset=["transaction_date"])

    if df.empty:

        st.warning("No valid transaction dates found.")

        return

    # --------------------------------------------------------
    # NUMERIC COLUMNS
    # --------------------------------------------------------

    for column in ["debit", "credit", "balance"]:

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        ).fillna(0)

    # --------------------------------------------------------
    # MONTH COLUMN
    # --------------------------------------------------------

    df["month"] = (
        df["transaction_date"]
        .dt.to_period("M")
        .astype(str)
    )

    # --------------------------------------------------------
    # FINANCIAL SUMMARY
    # --------------------------------------------------------

    total_income = df["credit"].sum()

    total_expenses = df["debit"].sum()

    net_savings = total_income - total_expenses

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Total Income",
        f"LKR {total_income:,.2f}"
    )

    col2.metric(
        "Total Expenses",
        f"LKR {total_expenses:,.2f}"
    )

    col3.metric(
        "Net Cash Flow",
        f"LKR {net_savings:,.2f}"
    )

    st.divider()

    # --------------------------------------------------------
    # MONTHLY REPORT
    # --------------------------------------------------------

    st.subheader("Monthly Income vs Expenses")

    monthly = (
        df.groupby("month")
        .agg(
            Income=("credit", "sum"),
            Expenses=("debit", "sum")
        )
        .reset_index()
        .sort_values("month")
    )

    monthly_melted = monthly.melt(
        id_vars="month",
        value_vars=["Income", "Expenses"],
        var_name="Type",
        value_name="Amount"
    )

    fig = px.bar(
        monthly_melted,
        x="month",
        y="Amount",
        color="Type",
        barmode="group",
        title="Monthly Financial Activity"
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )

    st.divider()

    # --------------------------------------------------------
    # EXPENSE CATEGORIES
    # --------------------------------------------------------

    st.subheader("Spending by Category")

    expenses = df[df["debit"] > 0].copy()

    if not expenses.empty:

        category_summary = (
            expenses.groupby("category")["debit"]
            .sum()
            .reset_index()
            .sort_values("debit", ascending=False)
        )

        fig = px.pie(
            category_summary,
            names="category",
            values="debit",
            hole=0.4,
            title="Expense Distribution"
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

        st.dataframe(
            category_summary,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info("No expenses available.")

    st.divider()

    # --------------------------------------------------------
    # MONTHLY COMPARISON
    # --------------------------------------------------------

    st.subheader("Monthly Comparison")

    if len(monthly) >= 2:

        st.dataframe(
            monthly,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "Upload statements covering multiple months "
            "to compare monthly spending."
        )

    st.divider()

    # --------------------------------------------------------
    # RECENT TRANSACTIONS
    # --------------------------------------------------------

    st.subheader("Recent Transactions")

    recent = df.sort_values(
        "transaction_date",
        ascending=False
    ).head(20)

    display = recent[
        [
            "transaction_date",
            "description",
            "debit",
            "credit",
            "category"
        ]
    ].copy()

    display["transaction_date"] = (
        display["transaction_date"].dt.strftime("%Y-%m-%d")
    )

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True
    )
