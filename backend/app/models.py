"""Versioned relational schema (Alembic migrations in alembic/versions)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow


def uid() -> str:
    return uuid.uuid4().hex


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    project: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan",
                                                     passive_deletes=True, order_by="Message.seq")
    __table_args__ = (Index("ix_conversations_updated", "updated_at"), Index("ix_conversations_archived", "archived"))


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="complete")
    provider_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    transcription: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    client_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_messages_conv_seq"),
        CheckConstraint("role in ('system','user','assistant','tool')", name="ck_messages_role"),
        CheckConstraint("status in ('complete','streaming','cancelled','error','interrupted')", name="ck_messages_status"),
        Index("ix_messages_conversation", "conversation_id", "seq"),
    )


class ProviderConfig(Base):
    __tablename__ = "provider_configs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(32))
    base_url: Mapped[str] = mapped_column(String(500))
    model: Mapped[str] = mapped_column(String(200))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("kind in ('ollama','openai_compatible','anthropic')", name="ck_provider_kind"),)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RobotActionRequest(Base):
    __tablename__ = "robot_action_requests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    actions: Mapped[list | dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        CheckConstraint("status in ('rejected','sent','completed','failed','cancelled','timeout','disconnected')", name="ck_robot_status"),
        Index("ix_robot_created", "created_at"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(50))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (Index("ix_audit_kind_ts", "kind", "ts"),)
