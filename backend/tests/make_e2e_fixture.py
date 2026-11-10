"""Writes the synthetic statement the browser tests upload (frontend/e2e/fixtures).

Everything in it is invented. Run it from the backend folder:

    venv/Scripts/python.exe -m tests.make_e2e_fixture
"""

from pathlib import Path

from .synthetic import FAKE_ACCOUNT, boc_pdf

TARGET = Path(__file__).resolve().parents[2] / "frontend" / "e2e" / "fixtures" / "synthetic-statement.pdf"


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(
        boc_pdf(
            rows=[
                ("02/09", "SALARY CREDIT SYNTHETIC", "2,500.00", "3,500.00"),
                ("05/09", "ATM CASH WITHDRAWAL", "500.00", "3,000.00"),
            ],
            closing="3,000.00",
            account=FAKE_ACCOUNT,
        )
    )
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
