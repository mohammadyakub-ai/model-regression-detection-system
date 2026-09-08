from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .config import PromptConfig


class Category(str, Enum):
    """The only valid classification labels."""

    billing = "billing"
    technical = "technical"
    account = "account"
    general = "general"


class ClassifierInput(BaseModel):
    """Contract for everything the feature accepts as input."""

    email_text: str = Field(min_length=1, description="The raw customer email body")


class ClassifierOutput(BaseModel):
    """Contract for everything the feature must return.

    The eval pipeline consumes only these two fields. Extra diagnostics
    (latency, tokens, raw output) may be added by subclasses.
    """

    category: Category
    summary: str = Field(min_length=1, description="One-sentence summary")


@runtime_checkable
class EvalTarget(Protocol):
    """The interface any LLM feature must satisfy to be testable.

    The eval engine (Phase 3) calls exactly this signature and only ever
    reads the returned ClassifierOutput.
    """

    def __call__(self, email_text: str, prompt: PromptConfig) -> ClassifierOutput: ...