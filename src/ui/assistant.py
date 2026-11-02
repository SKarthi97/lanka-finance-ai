import pandas as pd
import streamlit as st

from config import OLLAMA_MODEL
from database.db import get_all_transactions
from services.ollama_service import ask_ollama, is_model_available


MAX_RECENT_ROWS = 40


def build_context(transactions):
    """Compact summary of the data. Kept small for a 1.5B model."""

    df = pd.DataFrame(transactions)

    df["transaction_date"] = pd.to_datetime(
        df["transaction_date"], errors="coerce"
    )
    df = df.dropna(subset=["transaction_date"])

    df["month"] = df["transaction_date"].dt.to_period("M").astype(str)

    monthly = (
        df.groupby("month")
        .agg(income=("credit", "sum"), expenses=("debit", "sum"))
        .round(2)
        .reset_index()
    )

    categories = (
        df[df["debit"] > 0]
        .groupby("category")["debit"]
        .sum()
        .round(2)
        .sort_values(ascending=False)
        .reset_index()
    )

    recent = (
        df.sort_values("transaction_date", ascending=False)
        .head(MAX_RECENT_ROWS)
        [["transaction_date", "description", "debit", "credit", "category"]]
        .assign(
            transaction_date=lambda d: d["transaction_date"].dt.strftime("%Y-%m-%d")
        )
    )

    return (
        "Monthly totals (LKR):\n" + monthly.to_csv(index=False)
        + "\nSpending by category (LKR):\n" + categories.to_csv(index=False)
        + f"\nMost recent {len(recent)} transactions "
        "(debit = money out, credit = money in):\n"
        + recent.to_csv(index=False)
    )


def render_assistant():

    st.header("AI Assistant")

    st.caption(
        f"Runs locally via Ollama in Docker using {OLLAMA_MODEL}. "
        "Small models can make mistakes; verify figures on the Dashboard."
    )

    if not is_model_available():

        st.warning(
            f"Model '{OLLAMA_MODEL}' is not available. "
            "Start Docker and run: docker compose up -d ollama "
            "then docker compose up ollama-pull"
        )

        return

    transactions = get_all_transactions()

    if not transactions:

        st.info("Upload a bank statement first.")

        return

    question = st.text_input(
        "Ask about your finances",
        placeholder="Which category did I spend the most on?"
    )

    if st.button("Ask", type="primary") and question.strip():

        prompt = (
            "You are a personal finance assistant. Answer the question "
            "using ONLY the data below. Amounts are in LKR. If the data "
            "does not contain the answer, say so.\n\n"
            f"{build_context(transactions)}\n"
            f"Question: {question.strip()}\nAnswer:"
        )

        try:

            with st.spinner("Thinking..."):
                answer = ask_ollama(prompt)

            st.markdown(answer)

        except RuntimeError as error:

            st.error(str(error))
