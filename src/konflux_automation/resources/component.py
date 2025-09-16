"""Component resource builder."""
from __future__ import annotations

import json
from typing import Dict, Optional

from pydantic import Field

from .base import ResourceDefinition, ResourceModel


class GitSource(ResourceModel):
    """Git source configuration for a component."""

    url: str
    revision: Optional[str] = None
    context: Optional[str] = None
    dockerfile: Optional[str] = Field(default=None, alias="dockerfileUrl")

    def to_dict(self) -> Dict[str, str]:
        data: Dict[str, str] = {"url": self.url}
        if self.revision:
            data["revision"] = self.revision
        if self.context:
            data["context"] = self.context
        if self.dockerfile:
            data["dockerfileUrl"] = self.dockerfile
        return data


class PipelineConfig(ResourceModel):
    """Pipeline bundle reference used to build the component."""

    name: str
    bundle: str = "latest"

    def to_annotation(self) -> str:
        return json.dumps({"name": self.name, "bundle": self.bundle}, separators=(",", ":"))


class ComponentConfig(ResourceModel):
    """Configuration for creating or updating a Konflux Component."""

    name: str
    application: str
    namespace: Optional[str] = None
    component_name: Optional[str] = Field(default=None, alias="componentName")
    git: GitSource
    container_image: Optional[str] = Field(default=None, alias="containerImage")
    configure_pac: bool = True
    pipeline: Optional[PipelineConfig] = None
    git_provider: Optional[str] = Field(default=None, alias="git-provider")
    git_provider_url: Optional[str] = Field(default=None, alias="git-provider-url")
    labels: Dict[str, str] = Field(default_factory=dict)
    annotations: Dict[str, str] = Field(default_factory=dict)

    def to_resource(self, default_namespace: Optional[str] = None) -> ResourceDefinition:
        namespace = self.namespace or default_namespace
        if not namespace:
            raise ValueError("Namespace must be provided for Component resources.")

        metadata: Dict[str, object] = {"name": self.name, "namespace": namespace}
        annotations = dict(self.annotations)
        if self.configure_pac:
            annotations.setdefault("build.appstudio.openshift.io/request", "configure-pac")
        if self.pipeline:
            annotations["build.appstudio.openshift.io/pipeline"] = self.pipeline.to_annotation()
        if self.git_provider:
            annotations["git-provider"] = self.git_provider
        if self.git_provider_url:
            annotations["git-provider-url"] = self.git_provider_url
        if annotations:
            metadata["annotations"] = annotations
        if self.labels:
            metadata["labels"] = dict(self.labels)

        spec: Dict[str, object] = {
            "application": self.application,
            "componentName": self.component_name or self.name,
            "source": {"git": self.git.to_dict()},
        }
        if self.container_image:
            spec["containerImage"] = self.container_image

        return ResourceDefinition(
            api_version="appstudio.redhat.com/v1alpha1",
            kind="Component",
            metadata=metadata,
            spec=spec,
        )
