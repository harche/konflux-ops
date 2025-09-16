"""Application resource builder."""
from __future__ import annotations

from typing import Dict, Optional

from pydantic import Field

from .base import ResourceDefinition, ResourceModel


class ApplicationConfig(ResourceModel):
    """Configuration for creating or updating a Konflux Application."""

    name: str
    namespace: Optional[str] = None
    display_name: Optional[str] = None
    labels: Dict[str, str] = Field(default_factory=dict)
    annotations: Dict[str, str] = Field(default_factory=dict)

    def to_resource(self, default_namespace: Optional[str] = None) -> ResourceDefinition:
        namespace = self.namespace or default_namespace
        if not namespace:
            raise ValueError("Namespace must be provided for Application resources.")
        metadata: Dict[str, object] = {"name": self.name, "namespace": namespace}
        if self.labels:
            metadata["labels"] = dict(self.labels)
        if self.annotations:
            metadata["annotations"] = dict(self.annotations)
        spec: Dict[str, object] = {}
        if self.display_name:
            spec["displayName"] = self.display_name
        return ResourceDefinition(
            api_version="appstudio.redhat.com/v1alpha1",
            kind="Application",
            metadata=metadata,
            spec=spec or None,
        )
