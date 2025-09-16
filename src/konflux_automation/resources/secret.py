"""Secret resource builder."""
from __future__ import annotations

from typing import Dict, Optional

from pydantic import Field

from .base import ResourceDefinition, ResourceModel


class SecretConfig(ResourceModel):
    """Configuration for creating or updating Kubernetes secrets."""

    name: str
    namespace: Optional[str] = None
    type: str = "Opaque"
    data: Dict[str, str] = Field(default_factory=dict)
    string_data: Dict[str, str] = Field(default_factory=dict, alias="stringData")
    labels: Dict[str, str] = Field(default_factory=dict)
    annotations: Dict[str, str] = Field(default_factory=dict)

    def to_resource(self, default_namespace: Optional[str] = None) -> ResourceDefinition:
        namespace = self.namespace or default_namespace
        if not namespace:
            raise ValueError("Namespace must be provided for Secret resources.")

        metadata: Dict[str, object] = {"name": self.name, "namespace": namespace}
        if self.labels:
            metadata["labels"] = dict(self.labels)
        if self.annotations:
            metadata["annotations"] = dict(self.annotations)

        extra: Dict[str, object] = {"type": self.type}
        if self.data:
            extra["data"] = dict(self.data)
        if self.string_data:
            extra["stringData"] = dict(self.string_data)

        return ResourceDefinition(
            api_version="v1",
            kind="Secret",
            metadata=metadata,
            spec=None,
            extra=extra,
        )
