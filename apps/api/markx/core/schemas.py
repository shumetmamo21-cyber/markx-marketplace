"""Shared building blocks for request and response schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

Language = Annotated[str, StringConstraints(pattern=r"^(am|en)$")]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
PhoneText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=9, max_length=24)]


class ApiModel(BaseModel):
    """Requests reject unknown fields, so a typo is an error and not a silent no-op."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class Ok(ApiModel):
    ok: bool = True
