"""A printable PDF of the IRD figures with the transactions behind them, for an accountant.

Built from the same report the IRD tab shows (never recomputed here). It carries the
statement-based figures only and says plainly that it is not tax advice. Descriptions are
escaped, so statement text can never inject markup.
"""

import io
from datetime import date
from html import escape

import pymupdf

PAGE = pymupdf.paper_rect("a4")
MARGIN = pymupdf.Rect(36, 36, PAGE.width - 36, PAGE.height - 40)

CSS = """
body { font-family: sans-serif; font-size: 9pt; color: #111; }
h1 { font-size: 16pt; margin: 0 0 2pt 0; }
h2 { font-size: 11pt; margin: 12pt 0 3pt 0; border-bottom: 1px solid #888; }
p.note { font-size: 8pt; color: #444; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; font-size: 8pt; background: #e8e8e8; padding: 2pt 3pt; }
td { padding: 2pt 3pt; border-bottom: 0.5pt solid #ccc; vertical-align: top; }
td.n, th.n { text-align: right; }
"""


def _money(value) -> str:
    return f"{value:,.2f}"


def _row(cells: list[str], numeric_from: int = 1) -> str:
    return "<tr>" + "".join(
        f'<td class="{"n" if i >= numeric_from else ""}">{escape(str(c))}</td>' for i, c in enumerate(cells)
    ) + "</tr>"


def _table(head: list[str], rows: list[list[str]], numeric_from: int = 1) -> str:
    header = "".join(f'<th class="{"n" if i >= numeric_from else ""}">{escape(h)}</th>' for i, h in enumerate(head))
    return f"<table><tr>{header}</tr>{''.join(_row(r, numeric_from) for r in rows)}</table>"


def build_html(report, today: date, max_lines: int) -> str:
    parts = [
        f"<h1>Year of assessment {escape(report.label)}</h1>",
        f"<p>{report.period_start:%d %B %Y} to {report.period_end:%d %B %Y} &middot; amounts in LKR &middot; prepared {today:%d %B %Y}</p>",
        '<p class="note">Figures read from bank statements kept in Lanka Finance AI. This is not tax advice or a tax '
        "calculation: check them against your certificates and the IRD rules before filing.</p>",
        "<h2>Summary</h2>",
        _table(
            ["Head", "Amount", "Tax withheld", "Rows"],
            [[h.label, _money(h.amount), _money(h.tax_withheld), str(h.count)] for h in report.heads]
            + [["Total income recorded (deposits not counted)", _money(report.total_income), "", ""]]
            + [["Other tax lines (stamp duty and so on)", _money(report.other_tax), "", ""]],
        ),
        "<h2>Entered by you</h2>",
        _table(
            ["Item", "Amount"],
            [["Employer tax (APIT)", _money(report.extras.employer_tax)], ["Other tax paid", _money(report.extras.other_tax_paid)]],
        ),
    ]
    if report.extras.notes:
        parts.append(f'<p class="note">Note: {escape(report.extras.notes)}</p>')

    warnings = []
    if report.review_documents:
        warnings.append(f"{report.review_documents} statement(s) in this period are still waiting for review and are not included.")
    if report.uncategorised_count:
        warnings.append(f"{report.uncategorised_count} uncategorised credit(s) worth {_money(report.uncategorised_credits)} are not in any head.")
    if report.possible_tax_count:
        warnings.append(f"{report.possible_tax_count} uncategorised debit(s) worth {_money(report.possible_tax)} sit next to an interest or dividend credit and may be tax.")
    for account in report.coverage:
        if account.missing:
            months = ", ".join(f"{m.year}-{m.month:02d}" for m in account.missing)
            warnings.append(f"Account {escape(str(account.account_last4 or '?'))} has no statement for: {months}.")
    if warnings:
        parts.append("<h2>Check before relying on these figures</h2><ul>" + "".join(f"<li>{w}</li>" for w in warnings) + "</ul>")

    parts += [
        "<h2>By month</h2>",
        _table(
            ["Month", "Employment", "Interest", "Dividends", "Other income", "Tax withheld"],
            [[f"{m.year}-{m.month:02d}", _money(m.employment), _money(m.interest), _money(m.dividends), _money(m.other_income), _money(m.tax_withheld)] for m in report.months],
        ),
        "<h2>By bank</h2>",
        _table(
            ["Bank", "Employment", "Interest", "Tax on interest", "Dividends", "Other income"],
            [[b.bank_name or "Unknown bank", _money(b.employment), _money(b.interest), _money(b.interest_tax), _money(b.dividends), _money(b.other_income)] for b in report.banks],
        ),
    ]

    shown = report.lines[:max_lines]
    parts.append("<h2>The transactions behind the figures</h2>")
    if shown:
        parts.append(
            _table(
                ["Date", "Head", "Bank", "Account", "Description", "Amount"],
                [[row.date.isoformat(), row.kind, row.bank_code or "", row.account_last4 or "", row.description[:90], _money(row.amount)] for row in shown],
                numeric_from=5,
            )
        )
    if len(report.lines) > len(shown):
        parts.append(f'<p class="note">Showing {len(shown)} of {len(report.lines)} lines; the totals above count them all.</p>')
    return "<html><body>" + "".join(parts) + "</body></html>"


def build_pdf(report, today: date, max_lines: int = 300) -> bytes:
    story = pymupdf.Story(html=build_html(report, today, max_lines), user_css=CSS)
    out = io.BytesIO()
    writer = pymupdf.DocumentWriter(out)

    def rectfn(rect_num, filled):
        return PAGE, MARGIN, None

    story.write(writer, rectfn)
    writer.close()
    return out.getvalue()
