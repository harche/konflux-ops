"""Shared resource definitions for Konflux automation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


class ResourceModel(BaseModel):
    """Shared base model for Konflux resource configuration objects."""

    model_config = ConfigDict(populate_by_name=True)


@dataclass(frozen=True)
class ResourceDefinition:
    """Represents a Kubernetes resource manifest."""

    api_version: str
    kind: str
    metadata: Dict[str, Any]
    spec: Optional[Dict[str, Any]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": self.metadata,
        }
        if self.spec is not None:
            body["spec"] = self.spec
        if self.extra:
            body.update(self.extra)
        return body

    @property
    def name(self) -> Optional[str]:
        return self.metadata.get("name")

    @property
    def namespace(self) -> Optional[str]:
        return self.metadata.get("namespace")
