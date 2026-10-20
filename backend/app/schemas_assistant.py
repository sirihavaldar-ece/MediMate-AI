from typing import Literal

from pydantic import BaseModel, Field
from pydantic import model_validator


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1000)


class AssistantChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def require_user_last(self) -> "AssistantChatRequest":
        if self.messages[-1].role != "user":
            raise ValueError("The final chat message must be from the user.")
        return self


class AssistantChatResponse(BaseModel):
    reply: str
    mode: Literal["mock", "nebius"]
    model: str


class IntegrationStatusResponse(BaseModel):
    ai_mode: Literal["mock", "nebius"]
    ai_model: str
    ai_configured: bool
    voice_mode: Literal["demo", "twilio"]
    voice_configured: bool


class VoiceTestRequest(BaseModel):
    phone_number: str | None = Field(default=None, max_length=24)
    confirm_live_call: bool = False
    recipient_consented: bool = False


class VoiceTestResponse(BaseModel):
    mode: Literal["demo", "twilio"]
    status: str
    message: str
    provider_call_id: str | None = None


class VoiceConsentRequest(BaseModel):
    phone_number: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    enabled: bool


class VoiceConsentResponse(BaseModel):
    enabled: bool
    phone_number: str | None
    provider_configured: bool


class VoiceCallLogResponse(BaseModel):
    id: int
    dose_event_id: int | None
    patient_id: int
    attempt_number: int
    status: str
    attempt_at: str
