import pymupdf


def extract_pdf_text(pdf_file, password=None):

    document = pymupdf.open(
        stream=pdf_file.getvalue(),
        filetype="pdf"
    )

    try:

        if document.needs_pass:

            if not password:
                raise ValueError(
                    "This PDF requires a password."
                )

            if not document.authenticate(password):
                raise ValueError(
                    "Incorrect PDF password."
                )

        pages = []

        for page in document:
            pages.append(page.get_text("text"))

        return "\n".join(pages)

    finally:
        document.close()