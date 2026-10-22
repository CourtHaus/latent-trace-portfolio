from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from casesignal.api.dependencies.db import get_db_session
from casesignal.api.dependencies.operator_auth import SupabaseAdminUser, require_operator_admin
from casesignal.api.schemas.operator import OperatorSnapshotResponse
from casesignal.api.services.operator_snapshot import get_operator_snapshot

router = APIRouter(prefix="/operator", tags=["operator"])


@router.get("/snapshot", response_model=OperatorSnapshotResponse)
def get_snapshot(
    _admin: SupabaseAdminUser = Depends(require_operator_admin),
    session: Session = Depends(get_db_session),
) -> OperatorSnapshotResponse:
    return get_operator_snapshot(session)
