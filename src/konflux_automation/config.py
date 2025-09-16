"""Configuration models and helpers for Konflux automation."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field

from .resources.application import ApplicationConfig
from .resources.component import ComponentConfig
from .resources.image_repository import ImageRepositoryConfig
from .resources.release import ReleaseConfig
from .resources.release_plan import ReleasePlanConfig
from .resources.release_plan_admission import ReleasePlanAdmissionConfig
from .resources.secret import SecretConfig


class KonfluxContext(BaseModel):
    """Connection context to interact with a Konflux cluster."""

    namespace: Optional[str] = None
    kubeconfig: Optional[str] = None
    context: Optional[str] = None
    verify_ssl: bool = True
    field_manager: str = Field(default="konflux-automation")


class AutomationConfig(BaseModel):
    """High-level configuration describing desired Konflux state."""

    context: KonfluxContext = Field(default_factory=KonfluxContext)
    application: Optional[ApplicationConfig] = None
    components: List[ComponentConfig] = Field(default_factory=list)
    image_repositories: List[ImageRepositoryConfig] = Field(default_factory=list)
    release_plans: List[ReleasePlanConfig] = Field(default_factory=list)
    release_plan_admissions: List[ReleasePlanAdmissionConfig] = Field(default_factory=list)
    releases: List[ReleaseConfig] = Field(default_factory=list)
    secrets: List[SecretConfig] = Field(default_factory=list)

    @classmethod
    def from_file(cls, path: str | Path) -> "AutomationConfig":
        document_path = Path(path)
        data = yaml.safe_load(document_path.read_text())
        if not isinstance(data, dict):
            raise ValueError("Configuration file must contain a mapping at the top level.")
        return cls.model_validate(data)
