import hashlib

import streamlit as st
import pandas as pd

from services.pdf_service import extract_pdf_text
from parsers.boc_parser import parse_boc_statement
from services.report_service import calculate_statement_summary
from database.db import save_transactions
from services.category_service import categorize_transactions


def render_upload():

    st.header("Upload Bank Statements")

    st.write(
        "Upload your computer-generated BOC PDF statements."
    )

    uploaded_files = st.file_uploader(
        "Select PDF statements",
        type=["pdf"],
        accept_multiple_files=True
    )

    if not uploaded_files:
        return

    for pdf in uploaded_files:

        st.divider()

        st.subheader(pdf.name)

        file_hash = hashlib.sha256(
            pdf.getvalue()
        ).hexdigest()

        processed_key = f"processed_{file_hash}"

        password = st.text_input(
            f"PDF password (if required): {pdf.name}",
            type="password",
            key=f"password_{file_hash}"
        )

        if st.button(
            f"Process {pdf.name}",
            key=f"process_{file_hash}"
        ):

            try:

                with st.spinner("Extracting PDF text..."):

                    extracted_text = extract_pdf_text(
                        pdf,
                        password
                    )

                if not extracted_text.strip():

                    st.warning(
                        "No selectable text found. OCR may be required."
                    )

                    continue

                with st.expander("Inspect PDF text"):

                    st.text_area(
                        "Extracted text",
                        extracted_text,
                        height=250,
                        key=f"text_{file_hash}"
                    )

                with st.spinner("Parsing BOC transactions..."):

                    (
                        transactions,
                        opening_balance,
                        closing_balance,
                        warnings
                    ) = parse_boc_statement(
                        extracted_text,
                        pdf.name
                    )

                if not transactions:

                    st.warning(
                        "No transactions were identified."
                    )

                    continue

                transactions = categorize_transactions(
                    transactions
                )

                if st.session_state.get(processed_key):

                    st.warning(
                        "This statement has already been processed "
                        "during this session."
                    )

                    continue

                summary = calculate_statement_summary(
                    transactions,
                    opening_balance,
                    closing_balance
                )

                # Save extracted transactions

                save_transactions(transactions)

                st.session_state[processed_key] = True

                # Keep results in session

                st.session_state.setdefault(
                    "statement_results",
                    []
                )

                st.session_state["statement_results"].append({

                    "source": pdf.name,

                    "opening_balance": opening_balance,

                    "closing_balance": closing_balance,

                    "transactions": transactions,

                    "summary": summary,

                    "warnings": warnings

                })

                st.success(
                    f"Successfully processed {len(transactions)} transactions."
                )

                # Summary

                st.subheader("Statement Summary")

                col1, col2, col3 = st.columns(3)

                col1.metric(
                    "Opening Balance",
                    f"LKR {opening_balance:,.2f}"
                    if opening_balance is not None
                    else "Unavailable"
                )

                col2.metric(
                    "Total Credits",
                    f"LKR {summary['total_credit']:,.2f}"
                )

                col3.metric(
                    "Total Debits",
                    f"LKR {summary['total_debit']:,.2f}"
                )

                col4, col5 = st.columns(2)

                col4.metric(
                    "Calculated Closing",
                    f"LKR {summary['calculated_closing']:,.2f}"
                    if summary["calculated_closing"] is not None
                    else "Unavailable"
                )

                col5.metric(
                    "Statement Closing",
                    f"LKR {closing_balance:,.2f}"
                    if closing_balance is not None
                    else "Unavailable"
                )

                # Reconciliation

                st.subheader("Balance Reconciliation")

                difference = summary["difference"]

                if difference is None:

                    st.warning(
                        "Unable to reconcile statement."
                    )

                elif abs(difference) < 0.02:

                    st.success(
                        "Statement balances match."
                    )

                else:

                    st.error(
                        f"Difference: LKR {difference:,.2f}"
                    )

                # Transactions

                st.subheader("Extracted Transactions")

                transaction_df = pd.DataFrame(
                    transactions
                )

                st.dataframe(
                    transaction_df,
                    use_container_width=True,
                    hide_index=True
                )

                # Download CSV

                csv_data = transaction_df.to_csv(
                    index=False
                ).encode("utf-8-sig")

                st.download_button(
                    "Download CSV",
                    data=csv_data,
                    file_name=f"{pdf.name}_transactions.csv",
                    mime="text/csv",
                    key=f"download_{file_hash}"
                )

                # Warnings

                if warnings:

                    with st.expander(
                        f"Review warnings ({len(warnings)})"
                    ):

                        for warning in warnings:
                            st.warning(warning)

            except Exception as error:

                st.error(
                    f"Statement processing failed: {error}"
                )