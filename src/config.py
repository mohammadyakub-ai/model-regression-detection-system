from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from .contract import Category


class ExampleOutput(BaseModel):
    category: Category
    summary: str


class FewShotExample(BaseModel):
    input: str
    output: ExampleOutput


class PromptConfig(BaseModel):
    version_id: str
    created_at: datetime | None = None
    description: str | None = None
    model: str
    temperature: float = 0.0
    system_prompt: str
    few_shot_examples: list[FewShotExample] = Field(default_factory=list)

    @field_validator("created_at", mode="before")
    @classmethod
    def _default_timestamp(cls, v: object) -> object:
        if v is None:
            return datetime.now(timezone.utc)
        return v

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PromptConfig":
        with open(path, "r", encoding="utf-8") as f:
            return cls.model_validate(yaml.safe_load(f))