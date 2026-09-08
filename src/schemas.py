from pydantic import BaseModel

from .contract import Category, ClassifierOutput


class ClassificationResult(ClassifierOutput):
    """Eval-time result: the contract plus diagnostics."""

    raw_output: str | None = None
    usage: dict | None = None


# Re-exported for convenience so downstream code can use a single import.
__all__ = ["Category", "ClassifierOutput", "ClassificationResult"]