from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import AppSetting, AuditEvent

DEFAULT_SYSTEM = ("You are Humanoid Companion, a concise and helpful desktop assistant for programming and general questions. "
                  "Never claim to have run code, changed files or moved the robot unless a tool result in this conversation says so.")


class AppSettings(BaseModel):
    local_only: bool = False
    retention_days: int = Field(0, ge=0, le=3650, description="0 keeps history until deleted")
    system_prompt: str = Field(DEFAULT_SYSTEM, max_length=4000)
    max_context_tokens: int = Field(8000, ge=512, le=200_000)
    max_response_tokens: int = Field(1024, ge=16, le=32_000)
    default_provider_id: str | None = None
    shortcut: str = Field("CommandOrControl+Shift+Space", max_length=64)
    auto_speak: bool = False
    store_audio: bool = False


def load(db: Session) -> AppSettings:
    rows = {r.key: r.value for r in db.query(AppSetting).all()}
    return AppSettings(**{k: v for k, v in rows.items() if k in AppSettings.model_fields})


def update(db: Session, patch: dict) -> AppSettings:
    merged = load(db).model_dump()
    merged.update(patch)
    new = AppSettings(**merged)  # validates
    for k, v in new.model_dump().items():
        row = db.get(AppSetting, k)
        if row is None:
            db.add(AppSetting(key=k, value=v))
        elif row.value != v:
            row.value, row.updated_at = v, utcnow()
    db.add(AuditEvent(kind="settings.updated", detail={"keys": sorted(patch)}))
    return new
