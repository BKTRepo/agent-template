from typing import Literal

from pydantic import BaseModel, Field


class ConversationId(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=64)


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=255)


class ConversationRename(ConversationId):
    title: str = Field(min_length=1, max_length=255)


class ConversationFavorite(ConversationId):
    favorite: bool


class ConversationResources(ConversationId):
    skills: list[int] = Field(default_factory=list, max_length=100)
    knowledge_bases: list[int] = Field(default_factory=list, max_length=100)
    model: str | None = Field(default=None, max_length=128)


class FeedbackInput(BaseModel):
    message_id: int = Field(gt=0)
    rating: Literal["like", "dislike"]
    reason: str | None = Field(default=None, max_length=2000)


class SendInput(ConversationId):
    content: str = Field(min_length=1, max_length=40000)
    model: str | None = Field(default=None, max_length=128)


class TaskInput(BaseModel):
    task_id: int = Field(gt=0)


class ArtifactInput(BaseModel):
    artifact_id: int = Field(gt=0)
