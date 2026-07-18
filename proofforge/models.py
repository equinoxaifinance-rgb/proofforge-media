from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

ShortTerm = Annotated[str, StringConstraints(min_length=1, max_length=120, strip_whitespace=True)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CampaignBrief(StrictModel):
    campaign_name: str = Field(min_length=3, max_length=80)
    audience: str = Field(min_length=3, max_length=180)
    channel: Literal["social", "display", "email", "editorial"] = "social"
    message: str = Field(min_length=10, max_length=600)
    visual_style: str = Field(min_length=3, max_length=240)
    brand_colors: list[str] = Field(default_factory=lambda: ["#ff6b35", "#14213d"])
    forbidden_terms: list[ShortTerm] = Field(default_factory=list, max_length=20)
    quality_threshold: float = Field(default=0.9, ge=0.5, le=0.99)
    inject_weak_first: bool = True

    @field_validator("brand_colors")
    @classmethod
    def validate_colors(cls, colors: list[str]) -> list[str]:
        if not 1 <= len(colors) <= 5:
            raise ValueError("provide between one and five brand colors")
        for color in colors:
            if len(color) != 7 or not color.startswith("#"):
                raise ValueError("brand colors must use #RRGGBB format")
            int(color[1:], 16)
        return [color.lower() for color in colors]

    @field_validator("campaign_name", "audience", "message", "visual_style")
    @classmethod
    def reject_invalid_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
            raise ValueError("text contains an invalid control character")
        return value

    @model_validator(mode="after")
    def reject_instruction_and_forbidden_term_collisions(self) -> CampaignBrief:
        untrusted_text = " ".join(
            [self.campaign_name, self.audience, self.message, self.visual_style]
        ).casefold()
        injection_patterns = (
            r"\bignore\b(?:\s+\w+){0,3}\s+\b(?:previous|prior|system)\b\s+\binstructions?\b",
            r"\b(?:disregard|forget)\b(?:\s+\w+){0,3}\s+\b(?:instructions?|directions?|prompt)\b",
            r"\breveal\b(?:\s+\w+){0,3}\s+\bsystem\s+prompt\b",
            r"\bfollow\s+these\s+instructions\s+instead\b",
        )
        if any(re.search(pattern, untrusted_text) for pattern in injection_patterns):
            raise ValueError("brief contains an instruction-injection marker")
        collisions = [term for term in self.forbidden_terms if term.casefold() in untrusted_text]
        if collisions:
            raise ValueError("brief content contains one of its own forbidden terms")
        return self


class RunRequest(StrictModel):
    brief: CampaignBrief
    mode: Literal["demo", "live"] = "demo"


class ReviewRequest(StrictModel):
    approved: bool
    reviewer: str = Field(min_length=2, max_length=80)
    notes: str = Field(default="", max_length=800)
