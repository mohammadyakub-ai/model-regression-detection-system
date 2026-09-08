from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .contract import Category, ClassifierInput, ClassifierOutput

Difficulty = Literal["easy", "medium", "hard"]
EdgeType = Literal["ambiguous", "short", "typo", "mixed_language", "sarcasm"]


class TestCase(BaseModel):
    id: str
    input: str = Field(min_length=1)
    expected: ClassifierOutput
    expected_difficulty: Difficulty
    notes: str = Field(min_length=1)
    edge_case_types: list[EdgeType] = Field(default_factory=list)

    def to_classifier_input(self) -> ClassifierInput:
        return ClassifierInput(email_text=self.input)


class GoldenDataset(BaseModel):
    """A versioned golden dataset — the 'eval bar'."""

    model_config = ConfigDict(populate_by_name=True)

    dataset_version: str
    created_at: datetime | None = None
    description: str | None = None
    schema_doc: dict = Field(default_factory=dict, alias="schema")
    cases: list[TestCase]

    @field_validator("created_at", mode="before")
    @classmethod
    def _default_timestamp(cls, v: object) -> object:
        if v is None:
            return datetime.now(timezone.utc)
        return v

    @model_validator(mode="after")
    def _enforce_dataset_policy(self) -> "GoldenDataset":
        ids = [c.id for c in self.cases]
        if not self.cases:
            raise ValueError("dataset must contain at least one case")
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate case ids in dataset")
        for c in self.cases:
            if c.edge_case_types and c.expected_difficulty == "easy":
                raise ValueError(f"case {c.id}: edge cases must not be tagged easy")
        return self

    @classmethod
    def from_json(cls, path: str | Path) -> "GoldenDataset":
        with open(path, "r", encoding="utf-8") as f:
            return cls.model_validate(json.load(f))


class DuplicateDatasetVersionError(ValueError):
    pass


def load_all_datasets(datasets_dir: str | Path) -> list[GoldenDataset]:
    """Load every versioned dataset JSON from a directory.

    Raises DuplicateDatasetVersionError if two files share a version.
    """
    datasets_dir = Path(datasets_dir)
    datasets: list[GoldenDataset] = []
    seen: set[str] = set()
    for path in sorted(datasets_dir.glob("*.json")):
        dataset = GoldenDataset.from_json(path)
        if dataset.dataset_version in seen:
            raise DuplicateDatasetVersionError(
                f"duplicate dataset_version {dataset.dataset_version!r} in {path}"
            )
        seen.add(dataset.dataset_version)
        datasets.append(dataset)
    return datasets


def get_dataset(datasets_dir: str | Path, dataset_version: str) -> GoldenDataset:
    for dataset in load_all_datasets(datasets_dir):
        if dataset.dataset_version == dataset_version:
            return dataset
    raise KeyError(f"no dataset version {dataset_version!r} in {datasets_dir}")


def get_latest_dataset(datasets_dir: str | Path) -> GoldenDataset:
    """Return the newest dataset version, ordered by created_at."""
    datasets = load_all_datasets(datasets_dir)
    if not datasets:
        raise FileNotFoundError(f"no dataset files found in {datasets_dir}")
    return max(datasets, key=lambda d: d.created_at)