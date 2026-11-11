"""Expected business failures in the conversation module."""

from fastapi import Request

from core.responses import FailureResponse


class ConversationBusinessError(Exception):
    """A failure whose message can be shown to the caller."""


class TestCaseWorkbookFormatError(ConversationBusinessError):
    """A workbook could not be read as a test case artifact."""


async def conversation_business_error_handler(
    _request: Request, exc: ConversationBusinessError,
) -> FailureResponse:
    return FailureResponse(message=str(exc))
