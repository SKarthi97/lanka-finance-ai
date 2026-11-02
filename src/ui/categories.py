
import streamlit as st
import pandas as pd

from database.db import (
    get_all_transactions,
    update_transaction_category,
    get_category_rules,
    add_category_rule,
    delete_category_rule,
    recategorize_saved_transactions
)


# ============================================================
# AVAILABLE CATEGORIES
# ============================================================

DEFAULT_CATEGORIES = [

    "Salary",
    "Business Income",
    "Interest Income",
    "Deposit",
    "Money Transfer",
    "Cash Withdrawal",
    "Food and Dining",
    "Shopping",
    "Transport",
    "Fuel",
    "Utilities",
    "Healthcare",
    "Education",
    "Loan Repayment",
    "Bank Charges",
    "Card Payment",
    "Insurance",
    "Entertainment",
    "Investment",
    "Other",
    "Uncategorized"

]


# ============================================================
# CATEGORY MANAGEMENT PAGE
# ============================================================

def render_categories():

    st.header("Category Management")

    st.write(
        "Manage transaction categories and create "
        "your own automatic categorization rules."
    )

    transactions = get_all_transactions()

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    if transactions:

        df = pd.DataFrame(transactions)

        total_transactions = len(df)

        categorized = (
            df["category"] != "Uncategorized"
        ).sum()

        uncategorized = (
            df["category"] == "Uncategorized"
        ).sum()

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Total Transactions",
            total_transactions
        )

        col2.metric(
            "Categorized",
            int(categorized)
        )

        col3.metric(
            "Uncategorized",
            int(uncategorized)
        )

    else:

        st.info("No transactions found.")

        df = pd.DataFrame()

    st.divider()

    # --------------------------------------------------------
    # TABS
    # --------------------------------------------------------

    view_tab, edit_tab, rules_tab = st.tabs([
        "Transactions",
        "Edit Category",
        "Custom Rules"
    ])

    # ========================================================
    # TRANSACTIONS TAB
    # ========================================================

    with view_tab:

        st.subheader("Transaction Categories")

        if not df.empty:

            display_columns = [
                "id",
                "transaction_date",
                "description",
                "debit",
                "credit",
                "category",
                "category_source"
            ]

            st.dataframe(
                df[display_columns],
                use_container_width=True,
                hide_index=True
            )

            category_summary = (
                df.groupby("category")
                .size()
                .reset_index(name="transactions")
            )

            st.subheader("Category Summary")

            st.dataframe(
                category_summary,
                use_container_width=True,
                hide_index=True
            )

    # ========================================================
    # EDIT CATEGORY TAB
    # ========================================================

    with edit_tab:

        st.subheader("Manually Correct a Category")

        if not transactions:

            st.info("Upload a bank statement first.")

        else:

            transaction_options = {
                (
                    f"ID {item['id']} | "
                    f"{item['description']} | "
                    f"LKR {item['debit'] + item['credit']:,.2f}"
                ): item
                for item in transactions
            }

            selected_label = st.selectbox(
                "Select transaction",
                list(transaction_options.keys())
            )

            selected_transaction = transaction_options[
                selected_label
            ]

            st.write(
                "**Transaction description:**",
                selected_transaction["description"]
            )

            st.write(
                "**Current category:**",
                selected_transaction["category"]
            )

            existing_categories = sorted(set(
                DEFAULT_CATEGORIES
                + [
                    item["category"]
                    for item in transactions
                    if item["category"]
                ]
            ))

            selected_category = st.selectbox(
                "Choose correct category",
                existing_categories,
                index=(
                    existing_categories.index(
                        selected_transaction["category"]
                    )
                    if selected_transaction["category"]
                    in existing_categories
                    else existing_categories.index("Uncategorized")
                )
            )

            if st.button(
                "Save Category Correction",
                type="primary"
            ):

                success = update_transaction_category(
                    selected_transaction["id"],
                    selected_category
                )

                if success:

                    st.success(
                        "Transaction category updated successfully."
                    )

                    st.rerun()

                else:

                    st.error(
                        "Unable to update transaction."
                    )

    # ========================================================
    # CUSTOM RULES TAB
    # ========================================================

    with rules_tab:

        st.subheader("Create Automatic Categorization Rule")

        st.write(
            "When a transaction description contains "
            "a keyword, the selected category will be assigned."
        )

        with st.form("add_category_rule_form"):

            keyword = st.text_input(
                "Transaction keyword",
                placeholder="Example: ATMCASHWDL"
            )

            new_category = st.selectbox(
                "Assign category",
                DEFAULT_CATEGORIES[:-1]
            )

            submitted = st.form_submit_button(
                "Add Rule"
            )

            if submitted:

                try:

                    add_category_rule(
                        keyword,
                        new_category
                    )

                    st.success(
                        "Custom categorization rule added."
                    )

                    st.rerun()

                except Exception as error:

                    st.error(
                        f"Could not add rule: {error}"
                    )

        st.divider()

        st.subheader("Existing Custom Rules")

        rules = get_category_rules()

        if rules:

            for rule in rules:

                col1, col2, col3 = st.columns([3, 2, 1])

                col1.write(rule["keyword"])

                col2.write(rule["category"])

                if col3.button(
                    "Delete",
                    key=f"delete_rule_{rule['id']}"
                ):

                    delete_category_rule(
                        rule["id"]
                    )

                    st.rerun()

        else:

            st.info(
                "No custom categorization rules created yet."
            )

        st.divider()

        st.subheader("Reapply Automatic Rules")

        st.caption(
            "This updates automatically categorized transactions. "
            "Manually corrected transactions are protected."
        )

        if st.button("Reapply Categorization"):

            recategorize_saved_transactions()

            st.success(
                "Automatic categorization completed."
            )

            st.rerun()
