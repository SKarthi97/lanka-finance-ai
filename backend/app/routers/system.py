from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_current_session
from app.services.hardware import hardware_report
from app.services.ollama import check_ollama

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(response: Response, db: Session = Depends(get_db)) -> dict:
    """Public liveness/readiness probe. Reveals no configuration."""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": True}
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "database": False}


@router.get("/system/ollama", dependencies=[Depends(get_current_session)])
async def ollama_status(
    warmup: bool = False, settings: Settings = Depends(get_settings)
) -> dict:
    return await check_ollama(settings, warmup=warmup)


@router.get("/system/hardware", dependencies=[Depends(get_current_session)])
def hardware() -> dict:
    return hardware_report()
