import streamlit as st


def render_about():

    st.header("About Bank Statement Analyzer")

    st.markdown("""
    ### Application Technology

    - Python 3.12
    - Streamlit
    - PyMuPDF
    - Pandas
    - SQLite
    - Ollama

    ### Current Features

    - Multiple PDF uploads
    - Password-protected PDF extraction
    - BOC transaction parsing
    - Debit and credit identification
    - Balance reconciliation
    - CSV exports
    - Monthly financial dashboard

    ### Planned Features

    - Support for multiple banks
    - Automatic transaction categorization
    - AI transaction search
    - Ask questions about bank statements
    - Monthly spending comparisons
    - Income and expense analysis

    ### Privacy

    PDF extraction and transaction processing run locally.
    Ollama can be used for local AI analysis.
    """)

    st.caption(
        "Always verify extracted transactions "
        "against your original bank statement."
    )