"""Unified data model for all normalised case data sources."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DataType(str, Enum):
    """Enumeration of all supported data source types."""

    calendar = "calendar"
    slack = "slack"
    email = "email"
    credit_card = "credit_card"
    expense = "expense"
    garage = "garage"
    parking_permit = "parking_permit"
    helpdesk = "helpdesk"
    jira = "jira"
    diligence = "diligence"


class DataPoint(BaseModel):
    """A single normalised record from any data source."""

    model_config = ConfigDict(extra="forbid")

    id: str
    data_type: DataType
    persons: list[str] = Field(default_factory=list)
    content: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    location: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", mode="before")
    @classmethod
    def _validate_id(cls, v: Any) -> str:
        """Strip whitespace and reject blank ids."""
        if not isinstance(v, str):
            raise ValueError("id must be a string")
        stripped = v.strip()
        if not stripped:
            raise ValueError("id must not be empty or whitespace")
        return stripped

    @field_validator("content", mode="before")
    @classmethod
    def _validate_content(cls, v: Any) -> str:
        """Strip whitespace and reject blank content."""
        if not isinstance(v, str):
            raise ValueError("content must be a string")
        stripped = v.strip()
        if not stripped:
            raise ValueError("content must not be empty or whitespace")
        return stripped

    @field_validator("location", mode="before")
    @classmethod
    def _validate_location(cls, v: Any) -> str | None:
        """Strip whitespace; convert blank location to None."""
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("location must be a string or None")
        stripped = v.strip()
        return stripped if stripped else None

    @field_validator("persons", mode="before")
    @classmethod
    def _validate_persons(cls, v: Any) -> list[str]:
        """Strip each name and reject blank entries."""
        if not isinstance(v, list):
            raise ValueError("persons must be a list")
        result: list[str] = []
        for entry in v:
            if not isinstance(entry, str):
                raise ValueError("each person must be a string")
            stripped = entry.strip()
            if not stripped:
                raise ValueError("person names must not be empty or whitespace")
            result.append(stripped)
        return result

    @model_validator(mode="after")
    def _validate_time_range(self) -> "DataPoint":
        """Ensure end_time is not before start_time when both are set."""
        if self.start_time is not None and self.end_time is not None:
            if self.end_time < self.start_time:
                raise ValueError("end_time must not be before start_time")
        return self


class UnifiedData(BaseModel):
    """Container for all normalised DataPoint records."""

    model_config = ConfigDict(extra="forbid")

    records: list[DataPoint] = Field(default_factory=list)
