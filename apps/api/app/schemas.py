"""Request bodies. Response shapes are plain dicts from the repository."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class RequestOtpBody(BaseModel):
    phone: str = Field(min_length=6, max_length=20)


class SignupBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=6, max_length=20)


class VerifyOtpBody(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    otp: str = Field(min_length=4, max_length=8)


class AgentBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    system_prompt: str = Field(min_length=1, max_length=200_000)
    trigger_type: Literal["scheduled", "event", "hybrid"] = "event"
    trigger_scope: Literal["room", "topic"] = "room"
    trigger_condition: Optional[str] = None
    room_id: Optional[int] = None
    chat_type: Literal["all", "dm", "group"] = "all"
    excluded_room_ids: list[int] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=lambda: ["read", "send"])
    tool_suites: list[str] = Field(default_factory=list)
    webhook_ids: list[int] = Field(default_factory=list)
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    recurrence_cron: Optional[str] = None
    timezone: str = "Asia/Kolkata"
    max_iterations: int = Field(default=6, ge=1, le=20)
    timeout_seconds: int = Field(default=60, ge=5, le=600)
    max_memory_chars: int = Field(default=4000, ge=200, le=50_000)


class AgentPatch(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None
    trigger_type: Optional[Literal["scheduled", "event", "hybrid"]] = None
    trigger_scope: Optional[Literal["room", "topic"]] = None
    trigger_condition: Optional[str] = None
    room_id: Optional[int] = None
    chat_type: Optional[Literal["all", "dm", "group"]] = None
    excluded_room_ids: Optional[list[int]] = None
    capabilities: Optional[list[str]] = None
    tool_suites: Optional[list[str]] = None
    webhook_ids: Optional[list[int]] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    recurrence_cron: Optional[str] = None
    timezone: Optional[str] = None
    max_iterations: Optional[int] = Field(default=None, ge=1, le=20)
    timeout_seconds: Optional[int] = Field(default=None, ge=5, le=600)
    max_memory_chars: Optional[int] = Field(default=None, ge=200, le=50_000)


class TestRunBody(BaseModel):
    system_prompt: str = Field(min_length=1, max_length=200_000)
    trigger_message: str = Field(min_length=1, max_length=200_000)
    test_message: Optional[str] = Field(default=None, max_length=4000)
    room_id: Optional[int] = None
    is_group: bool = False
    agent_id: Optional[int] = None


class ChatSendBody(BaseModel):
    text: Optional[str] = Field(default=None, max_length=4000)
    media_url: Optional[str] = Field(default=None, max_length=2000)
    room_id: Optional[int] = None


class LaneResetBody(BaseModel):
    room_id: Optional[int] = None
    lane: Optional[str] = None


class FollowUpRuleBody(BaseModel):
    id: Optional[str] = None
    message: str
    message_mode: Literal["generated", "verbatim"] = "generated"
    delay_seconds: int = Field(ge=1)
    send_text_separately: bool = False
    medias: list[dict[str, Any]] = Field(default_factory=list)


class FollowUpWindowBody(BaseModel):
    timezone: Optional[str] = None
    days: Optional[list[int]] = None
    start: Optional[str] = None
    end: Optional[str] = None


class FollowUpRulesBody(BaseModel):
    enabled: bool = True
    rules: list[FollowUpRuleBody] = Field(default_factory=list)
    send_window: Optional[FollowUpWindowBody] = None


class ScheduleBody(BaseModel):
    """One scheduled send. `rrule` uses iCalendar syntax; empty means one-shot."""
    context: dict[str, Any]
    rrule: Optional[str] = None
    dtstart_local: Optional[str] = None
    until_local: Optional[str] = None
    execute_after_local: Optional[str] = None


class WebhookBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    url: str = Field(min_length=1, max_length=2000)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    headers: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    body_fields: list[dict[str, Any]] = Field(default_factory=list, max_length=30)


class WebhookPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    method: Optional[Literal["GET", "POST", "PUT", "PATCH", "DELETE"]] = None
    headers: Optional[list[dict[str, Any]]] = None
    body_fields: Optional[list[dict[str, Any]]] = None
    active: Optional[bool] = None


class KnowledgeSourceBody(BaseModel):
    name: str
    source_room_id: str
    source_type: str = "whatsapp_room"
    extraction_instruction: str = ""


class KnowledgeEntryBody(BaseModel):
    keys: list[str] = Field(default_factory=list)
    title: str = ""
    content: str = ""
    medias: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class ExclusionBody(BaseModel):
    room_ids: list[int] = Field(min_length=1)
    duration_seconds: int = Field(default=86_400, ge=60)


class PauseBody(BaseModel):
    enabled: bool


class InboundBody(BaseModel):
    """Payload a channel adapter posts to /internal/inbound."""
    account_id: int
    external_room_id: str
    text: str = ""
    sender: str = ""
    sender_name: str = ""
    room_kind: Literal["dm", "group"] = "dm"
    media: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: Optional[int] = None
    is_human_owner: bool = False


class NotifyBody(BaseModel):
    account_id: int
    message: str = Field(min_length=1, max_length=10_000)
    source: str = "service"
    room_id: Optional[int] = None
    send: bool = True
    wait: bool = False
