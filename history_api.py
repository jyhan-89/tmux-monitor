from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

import history
import tokens

router = APIRouter(prefix="/api")


@router.get("/history")
def api_history(since: str | None = None, type: str | None = None, session: str | None = None, limit: int = 200,
                _: dict = Depends(tokens.require("history.read"))):
    try:
        start = datetime.fromisoformat(since) if since else None
    except ValueError:
        raise HTTPException(400, "since는 ISO 형식 시각이어야 합니다")
    if start and start.tzinfo is None:
        start = start.astimezone()
    return history.query(start, type, session, max(1, min(limit, 2000)))
