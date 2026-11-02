
import streamlit as st

from config import APP_NAME

from database.db import (
    initialize_database,
    recategorize_saved_transactions
)

from ui.sidebar import render_sidebar
from ui.upload import render_upload
from ui.dashboard import render_dashboard
from ui.categories import render_categories
from ui.assistant import render_assistant
from ui.about import render_about


# ============================================================
# APPLICATION CONFIGURATION
# ============================================================

st.set_page_config(
    page_title=APP_NAME,
    page_icon="💰",
    layout="wide"
)


# ============================================================
# INITIALIZE DATABASE
# ============================================================

initialize_database()

recategorize_saved_transactions()


# ============================================================
# APPLICATION HEADER
# ============================================================

st.title("💰 Local Bank Statement Analyzer")

st.caption(
    "Your personal financial analysis application"
)


# ============================================================
# SIDEBAR
# ============================================================

render_sidebar()


# ============================================================
# APPLICATION NAVIGATION
# ============================================================

upload_tab, dashboard_tab, categories_tab, assistant_tab, about_tab = st.tabs([
    "📄 Upload Statements",
    "📊 Dashboard",
    "🏷️ Categories",
    "🤖 AI Assistant",
    "ℹ️ About"
])


# ============================================================
# UPLOAD PAGE
# ============================================================

with upload_tab:

    render_upload()


# ============================================================
# DASHBOARD PAGE
# ============================================================

with dashboard_tab:

    render_dashboard()


# ============================================================
# CATEGORY MANAGEMENT
# ============================================================

with categories_tab:

    render_categories()


# ============================================================
# AI ASSISTANT
# ============================================================

with assistant_tab:

    render_assistant()


# ============================================================
# ABOUT PAGE
# ============================================================

with about_tab:

    render_about()


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Local Bank Analyzer | Python 3.12 | "
    "Streamlit | PyMuPDF | SQLite | Ollama"
)
