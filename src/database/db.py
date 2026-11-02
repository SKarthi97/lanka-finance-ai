
import os
import sqlite3

from config import DATABASE_PATH


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():

    os.makedirs(
        os.path.dirname(DATABASE_PATH),
        exist_ok=True
    )

    connection = sqlite3.connect(DATABASE_PATH)

    connection.row_factory = sqlite3.Row

    return connection


# ============================================================
# INITIALIZE DATABASE AND MIGRATIONS
# ============================================================

def initialize_database():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            transaction_date TEXT,

            description TEXT,

            debit REAL DEFAULT 0,

            credit REAL DEFAULT 0,

            balance REAL,

            category TEXT DEFAULT 'Uncategorized',

            source TEXT,

            review_required INTEGER DEFAULT 0

        )
    """)

    # Add category_source to older databases.

    cursor.execute("PRAGMA table_info(transactions)")

    existing_columns = [
        row["name"] for row in cursor.fetchall()
    ]

    if "category_source" not in existing_columns:

        cursor.execute("""
            ALTER TABLE transactions
            ADD COLUMN category_source TEXT DEFAULT 'automatic'
        """)

    # Custom categorization rules.

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS category_rules (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            keyword TEXT NOT NULL COLLATE NOCASE UNIQUE,

            category TEXT NOT NULL,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP

        )
    """)

    connection.commit()
    connection.close()


# ============================================================
# SAVE TRANSACTIONS
# ============================================================

def save_transactions(transactions):

    connection = get_connection()

    cursor = connection.cursor()

    for item in transactions:

        cursor.execute("""
            INSERT INTO transactions (
                transaction_date,
                description,
                debit,
                credit,
                balance,
                category,
                source,
                review_required,
                category_source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item["date"],
            item["description"],
            item["debit"],
            item["credit"],
            item["balance"],
            item.get("category", "Uncategorized"),
            item["source"],
            int(item.get("review_required", False)),
            item.get("category_source", "automatic")
        ))

    connection.commit()
    connection.close()


# ============================================================
# GET TRANSACTIONS
# ============================================================

def get_all_transactions():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM transactions
        ORDER BY transaction_date DESC, id DESC
    """)

    rows = cursor.fetchall()

    result = [dict(row) for row in rows]

    connection.close()

    return result


# ============================================================
# MANUAL CATEGORY UPDATE
# ============================================================

def update_transaction_category(
    transaction_id,
    category
):

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute("""
        UPDATE transactions

        SET category = ?,
            category_source = 'manual'

        WHERE id = ?
    """, (
        category,
        transaction_id
    ))

    connection.commit()

    updated = cursor.rowcount > 0

    connection.close()

    return updated


# ============================================================
# CATEGORY RULE MANAGEMENT
# ============================================================

def get_category_rules():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, keyword, category
        FROM category_rules
        ORDER BY keyword
    """)

    rows = cursor.fetchall()

    result = [dict(row) for row in rows]

    connection.close()

    return result


def add_category_rule(keyword, category):

    keyword = keyword.strip()
    category = category.strip()

    if not keyword or not category:
        raise ValueError(
            "Keyword and category are required."
        )

    connection = get_connection()

    cursor = connection.cursor()

    try:

        cursor.execute("""
            INSERT INTO category_rules (
                keyword,
                category
            )
            VALUES (?, ?)
        """, (
            keyword,
            category
        ))

        connection.commit()

    finally:

        connection.close()


def delete_category_rule(rule_id):

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM category_rules
        WHERE id = ?
    """, (rule_id,))

    connection.commit()

    connection.close()


# ============================================================
# RECATEGORIZE AUTOMATIC TRANSACTIONS
# ============================================================

def recategorize_saved_transactions():

    from services.category_service import categorize_transaction

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, description
        FROM transactions
        WHERE category_source = 'automatic'
    """)

    rows = cursor.fetchall()

    for row in rows:

        category = categorize_transaction(
            row["description"]
        )

        cursor.execute("""
            UPDATE transactions
            SET category = ?
            WHERE id = ?
              AND category_source = 'automatic'
        """, (
            category,
            row["id"]
        ))

    connection.commit()
    connection.close()
