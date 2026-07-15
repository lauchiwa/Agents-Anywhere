from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from agent_server.deps import current_user_id, get_approval_service
from agent_server.core.models import RpcResponsePayload
from agent_server.services.approvals import ApprovalService, ApprovalServiceError


router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.post("/{approval_id}/resolve", response_model=RpcResponsePayload)
async def resolve_approval(
    approval_id: str,
    payload: dict[str, Any],
    user_id: str = Depends(current_user_id),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> RpcResponsePayload:
    status = payload.get("status")
    if status not in {"approved", "approved_for_session", "rejected", "cancelled"}:
        raise HTTPException(status_code=422, detail="invalid approval status")
    # AskUserQuestion answers: [{"question": str, "labels": [str, ...]}, ...].
    # Optional — absent for plain approve/reject.
    selections = payload.get("selections")
    if selections is not None and not isinstance(selections, list):
        raise HTTPException(status_code=422, detail="selections must be a list")
    try:
        return await approval_service.resolve(
            approval_id, status, selections=selections, user_id=user_id
        )
    except ApprovalServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
