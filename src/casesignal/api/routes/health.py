from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from casesignal.api.dependencies.db import get_db_session
from casesignal.api.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
def healthz(session: Session = Depends(get_db_session)) -> HealthResponse:
    session.execute(text("SELECT 1"))
    return HealthResponse(status="ok")
