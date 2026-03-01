import re
from pydantic import BaseModel, Field, field_validator
from typing import Any, Optional

UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _validate_uuid4(v: str) -> str:
    if not UUID4_RE.match(v.lower()):
        raise ValueError("must be a valid UUID v4")
    return v.lower()


class HookEvent(BaseModel):
    hook_event_name: str
    session_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_use_id: Optional[str] = None   # Claude Code sends this; used for dedup
    tool_input: Optional[dict[str, Any]] = None
    tool_response: Optional[dict[str, Any]] = None
    cwd: Optional[str] = None
    duration_ms: Optional[int] = None
    model_config = {"extra": "ignore"}

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v):
        # Accept any non-empty string — Claude Code may use formats other than UUID4
        if v is not None and len(v) > 200:
            raise ValueError("session_id too long")
        return v if v else None


class DeviceRegister(BaseModel):
    device_id: str
    character_name: str = Field(min_length=1, max_length=30)

    @field_validator("device_id")
    @classmethod
    def validate_device_id(cls, v):
        return _validate_uuid4(v)


class ProfilePatch(BaseModel):
    character_name: str = Field(min_length=1, max_length=30)


class QuestCompletion(BaseModel):
    quest_id: str
    quest_name: str
    xp_awarded: int


class XPAward(BaseModel):
    source: str
    amount: int
    quest_completions: list[QuestCompletion] = []
