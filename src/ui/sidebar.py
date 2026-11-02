import streamlit as st

from config import OLLAMA_MODEL
from services.ollama_service import (
    get_ollama_status,
    get_installed_models,
    is_model_available
)


def render_sidebar():

    with st.sidebar:

        st.header("System Status")

        status = get_ollama_status()

        if status:

            st.success("Ollama is running")

            models = get_installed_models()

            if is_model_available():
                st.success(f"Model ready: {OLLAMA_MODEL}")
            else:
                st.warning(
                    f"Model '{OLLAMA_MODEL}' not found. "
                    f"Run: docker compose up ollama-pull"
                )

            if models:

                st.write("Installed models:")

                for model in models:
                    st.caption(f"• {model}")

                st.session_state["ollama_models"] = models

            else:

                st.info("No Ollama models installed.")

        else:

            st.error("Ollama is not running")

            st.session_state["ollama_models"] = []

        st.divider()

        st.write("Python: 3.12")
        st.write("PDF processing: PyMuPDF")
        st.write("Bank parser: BOC")
        st.write("Database: SQLite")