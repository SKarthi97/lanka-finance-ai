import logging

from fastapi import FastAPI

from app.routers import (
    ai,
    auth,
    budgets,
    categories,
    categorization,
    documents,
    history,
    imports,
    insights,
    ird,
    merchants,
    notifications,
    overview,
    recurring,
    reports,
    rules,
    savings,
    search,
    system,
    tracker,
    transactions,
    transfers,
    trend,
    views,
)

# Application loggers (uvicorn only configures its own). Messages carry codes and ids,
# never statement contents, descriptions, amounts or passwords.
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

# Interactive docs are disabled: the API is only reachable through the frontend proxy.
app = FastAPI(
    title="Lanka Finance AI API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(system.router)
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(imports.router)
app.include_router(transactions.router)
app.include_router(history.router)
app.include_router(overview.router)
app.include_router(trend.router)
app.include_router(tracker.router)
app.include_router(categories.router)
app.include_router(rules.router)
app.include_router(categorization.router)
app.include_router(transfers.router)
app.include_router(notifications.router)
app.include_router(budgets.router)
app.include_router(savings.router)
app.include_router(ird.router)
app.include_router(recurring.router)
app.include_router(views.router)
app.include_router(reports.router)
app.include_router(merchants.router)
app.include_router(search.router)
app.include_router(ai.router)
app.include_router(insights.router)
