"""The assistant endpoint: one question (with the conversation so far), one answer plus the tools it used."""
import logging
import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal

import anyio
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from app.assistant.conversation import run_conversation
from app.assistant.llm_client import LLMClient, get_llm_client
from app.assistant.mcp_bridge import McpBridge
from app.auth import CurrentUser
from app.config import get_settings
from app.trips import SessionDep, can_read, get_trip_for_user, require

logger = logging.getLogger("app.assistant")

router = APIRouter(tags=["assistant"])

MAX_MESSAGES = 20
MAX_CHARS = 4000


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=MAX_CHARS)]


class AssistantIn(BaseModel):
    """The conversation so far, ending with the user's question. The server keeps nothing between requests."""

    messages: Annotated[list[ChatMessage], Field(min_length=1, max_length=MAX_MESSAGES)]

    @field_validator("messages")
    @classmethod
    def _ends_with_a_question(cls, value: list[ChatMessage]) -> list[ChatMessage]:
        if value[-1].role != "user":
            raise ValueError("the last message must be the user's question")
        return value


class ToolCallOut(BaseModel):
    name: str
    arguments: dict[str, Any]
    ok: bool
    summary: str
    error: str | None
    result: str | None
    durationMs: int
    prefetched: bool  # read automatically before the first model call


class AssistantOut(BaseModel):
    reply: str
    toolCalls: list[ToolCallOut]
    steps: int
    incomplete: bool


def get_llm_factory() -> Callable[[], LLMClient]:
    """The way to get the model, resolved after the access check so a stranger never learns whether it is set up.
    Tests replace this dependency."""
    return get_llm_client


@router.post("/trips/{trip_id}/assistant/messages")
async def ask_assistant(
    trip_id: uuid.UUID,
    body: AssistantIn,
    user: CurrentUser,
    session: SessionDep,
    request: Request,
    llm_factory: Annotated[Callable[[], LLMClient], Depends(get_llm_factory)],
) -> AssistantOut:
    """Every participant (viewers too) may ask; non-participants get 404. Nothing is changed or stored."""

    def check_access() -> None:
        _, role = get_trip_for_user(session, trip_id, user)
        require(can_read(role))

    await anyio.to_thread.run_sync(check_access)
    llm = llm_factory()
    settings = get_settings()
    async with McpBridge(settings.mcp_url, request.headers["authorization"]) as bridge:
        result = await run_conversation(
            llm,
            bridge,
            str(trip_id),
            [{"role": m.role, "content": m.content} for m in body.messages],
            settings.assistant_max_steps,
        )
    return AssistantOut(
        reply=result.reply,
        toolCalls=[
            ToolCallOut(
                name=c.name,
                arguments=c.arguments,
                ok=c.ok,
                summary=c.summary,
                error=c.error,
                result=c.result,
                durationMs=c.duration_ms,
                prefetched=c.prefetched,
            )
            for c in result.tool_calls
        ],
        steps=result.steps,
        incomplete=result.incomplete,
    )
