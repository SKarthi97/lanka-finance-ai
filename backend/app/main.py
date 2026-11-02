from fastapi import FastAPI

from app.routers import auth, system

# Interactive docs are disabled: the API is only reachable through the frontend proxy.
app = FastAPI(
    title="Lanka Finance AI API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(system.router)
app.include_router(auth.router)
