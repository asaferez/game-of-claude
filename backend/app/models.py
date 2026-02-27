from pydantic import BaseModel
from typing import Any, Optional


class HookEvent(BaseModel):
    hook_event_name: str
    session_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[dict[str, Any]] = None
    tool_response: Optional[dict[str, Any]] = None
    cwd: Optional[str] = None
    duration_ms: Optional[int] = None
    model_config = {"extra": "allow"}


class DeviceRegister(BaseModel):
    device_id: str
    character_name: str


class ProfilePatch(BaseModel):
    character_name: str


class QuestCompletion(BaseModel):
    quest_id: str
    quest_name: str
    xp_awarded: int


class XPAward(BaseModel):
    source: str
    amount: int
    quest_completions: list[QuestCompletion] = []
