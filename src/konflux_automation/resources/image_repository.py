"""ImageRepository resource builder."""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import Field

from .base import ResourceDefinition, ResourceModel


class NotificationConfig(ResourceModel):
    """Notification entry for ImageRepository."""

    event: str = Field(description="Event that triggers the notification, for example 'repo_push'.")
    method: str = Field(description="Delivery method, for example 'webhook'.")
    title: str
    config: Dict[str, str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "event": self.event,
            "method": self.method,
            "title": self.title,
            "config": dict(self.config),
        }


class ImageRepositoryConfig(ResourceModel):
    """Configuration for creating or updating a Konflux ImageRepository."""

    name: str
    namespace: Optional[str] = None
    application: str
    component: str
    image_name: str = Field(..., alias="image")
    visibility: str = Field(default="public")
    notifications: List[NotificationConfig] = Field(default_factory=list)
    annotations: Dict[str, str] = Field(default_factory=dict)
    labels: Dict[str, str] = Field(default_factory=dict)

    def to_resource(self, default_namespace: Optional[str] = None) -> ResourceDefinition:
        namespace = self.namespace or default_namespace
        if not namespace:
            raise ValueError("Namespace must be provided for ImageRepository resources.")

        metadata: Dict[str, object] = {
            "name": self.name,
            "namespace": namespace,
            "labels": {
                "appstudio.redhat.com/application": self.application,
                "appstudio.redhat.com/component": self.component,
                **self.labels,
            },
        }
        annotations = {"image-controller.appstudio.redhat.com/update-component-image": "true"}
        annotations.update(self.annotations)
        metadata["annotations"] = annotations

        spec: Dict[str, object] = {
            "image": {
                "name": self.image_name,
                "visibility": self.visibility,
            }
        }
        if self.notifications:
            spec["notifications"] = [entry.to_dict() for entry in self.notifications]

        return ResourceDefinition(
            api_version="appstudio.redhat.com/v1alpha1",
            kind="ImageRepository",
            metadata=metadata,
            spec=spec,
        )
