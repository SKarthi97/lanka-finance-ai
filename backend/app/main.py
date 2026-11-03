import logging

from fastapi import FastAPI

from app.routers import auth, categories, documents, overview, system, transactions

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
app.include_router(transactions.router)
app.include_router(overview.router)
app.include_router(categories.router)
