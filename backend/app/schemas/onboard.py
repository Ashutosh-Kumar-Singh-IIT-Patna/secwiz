"""Onboarding request/response shapes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


KNOWN_ECOSYSTEMS = {
    "npm",
    "pypi",
    "go",
    "maven",
    "rubygems",
    "nuget",
    "cargo",
    "packagist",
    "composer",
    "software",
    "saas",
}


class DependencyIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ecosystem: str = "software"
    name: str = Field(min_length=1, max_length=200)
    raw_input: str | None = None
    aliases: list[str] = Field(default_factory=list)
    version_spec: str | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "DependencyIn":
        ecosystem = (self.ecosystem or "software").strip().lower()
        if ecosystem not in KNOWN_ECOSYSTEMS:
            ecosystem = "software"
        self.ecosystem = ecosystem
        self.name = self.name.strip()
        if not self.raw_input:
            self.raw_input = self.name
        return self


class FamilyConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    wire_platform_slugs: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    max_runs_per_day: int = 4


class SourceConfigIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    families: dict[str, FamilyConfig] = Field(default_factory=dict)
    wire_defaults: Literal[
        "all_enabled_except_auth_required", "none", "manual"
    ] = "all_enabled_except_auth_required"


class OnboardRequest(BaseModel):
    email: EmailStr
    dependencies: list[DependencyIn] = Field(min_length=1)
    source_config: SourceConfigIn = Field(default_factory=SourceConfigIn)


class OnboardResponse(BaseModel):
    ok: bool = True
    user_id: str
    watch_item_count: int


def family_to_dict(cfg: FamilyConfig) -> dict[str, Any]:
    return cfg.model_dump(exclude_unset=False)


def source_config_to_dict(cfg: SourceConfigIn) -> dict[str, Any]:
    return cfg.model_dump(exclude_unset=False)
