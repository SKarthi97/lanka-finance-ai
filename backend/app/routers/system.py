from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_current_session
from app.models import UserSession
from app.services import backup_status
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


@router.get("/system/storage")
def storage(
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """How much room the data takes and when it was last backed up. Counts and sizes only."""
    return backup_status.storage(db, settings, session.user_id)
