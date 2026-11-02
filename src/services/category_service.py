
import re

from database.db import get_category_rules


# ============================================================
# DEFAULT CATEGORY RULES
# ============================================================

CATEGORY_RULES = [

    (
        "Bank Charges",
        [
            "ATM SERVICE CHARGE",
            "SERVICE CHARGE",
            "ANNUAL FEE",
            "DEBIT CARD ANNUAL FEE",
            "BANK CHARGE",
            "SMS CHARGE",
            "MAINTENANCE FEE"
        ]
    ),

    (
        "Interest Income",
        [
            "INTEREST PAY",
            "INTEREST CREDIT",
            "INT PAID"
        ]
    ),

    (
        "Loan Repayment",
        [
            "LOAN RECO",
            "LOAN REPAYMENT",
            "LOAN PAYMENT",
            "LOAN RECOVERY"
        ]
    ),

    (
        "Cash Withdrawal",
        [
            "ATMCASHWDL",
            "ATM CASH WDL",
            "ATM CASH WITHDRAWAL",
            "CASH WITHDRAWAL"
        ]
    ),

    (
        "Card Payment",
        [
            "POS PURCHASE",
            "POS PAYMENT",
            "DEBIT CARD PURCHASE",
            "CARD PAYMENT"
        ]
    ),

    (
        "Deposit",
        [
            "SLIPS IN",
            "CASH DEPOSIT",
            "CHEQUE DEPOSIT",
            "DEPOSIT"
        ]
    ),

    (
        "Money Transfer",
        [
            "FUND TRANSFER",
            "TRANSFER TO",
            "TRANSFER FROM",
            "ONLINE TRANSFER",
            "CEFT",
            "SLIPS OUT"
        ]
    ),

    (
        "Utilities",
        [
            "ELECTRICITY",
            "CEB",
            "WATER BILL",
            "TELEPHONE",
            "DIALOG",
            "MOBITEL",
            "SLT"
        ]
    ),

    (
        "Salary",
        [
            "SALARY",
            "PAYROLL",
            "WAGES"
        ]
    )
]


# ============================================================
# CATEGORIZE ONE TRANSACTION
# ============================================================

def categorize_transaction(description):

    if not description:
        return "Uncategorized"

    description = description.upper().strip()

    # Custom rules have priority.

    custom_rules = get_category_rules()

    for rule in custom_rules:

        keyword = rule["keyword"].upper().strip()

        if keyword and keyword in description:

            return rule["category"]

    # Built-in rules.

    for category, keywords in CATEGORY_RULES:

        for keyword in keywords:

            if keyword in description:

                return category

    # Numeric references remain unclassified.

    if re.fullmatch(r"\d+", description):

        return "Uncategorized"

    return "Uncategorized"


# ============================================================
# CATEGORIZE MULTIPLE TRANSACTIONS
# ============================================================

def categorize_transactions(transactions):

    categorized = []

    for transaction in transactions:

        item = transaction.copy()

        item["category"] = categorize_transaction(
            item.get("description", "")
        )

        item["category_source"] = "automatic"

        categorized.append(item)

    return categorized
