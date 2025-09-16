"""ReleasePlanAdmission resource builder."""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import Field

from .base import ResourceDefinition, ResourceModel


class ReleasePlanAdmissionConfig(ResourceModel):
    """Configuration for creating or updating a ReleasePlanAdmission."""

    name: str
    namespace: Optional[str] = None
    applications: List[str]
    origin_namespace: str = Field(..., alias="origin")
    environment: Optional[str] = None
    pipeline_ref: Optional[str] = Field(default=None, alias="pipelineRef")
    service_account: Optional[str] = Field(default=None, alias="serviceAccount")
    policy: Optional[str] = None
    data: Optional[Dict[str, object]] = None
    block_releases: bool = Field(default=False, alias="blockReleases")
    labels: Dict[str, str] = Field(default_factory=dict)
    annotations: Dict[str, str] = Field(default_factory=dict)

    def to_resource(self, default_namespace: Optional[str] = None) -> ResourceDefinition:
        namespace = self.namespace or default_namespace
        if not namespace:
            raise ValueError("Namespace must be provided for ReleasePlanAdmission resources.")

        metadata_labels: Dict[str, str] = {
            "release.appstudio.openshift.io/block-releases": str(self.block_releases).lower(),
        }
        metadata_labels.update(self.labels)

        metadata: Dict[str, object] = {
            "name": self.name,
            "namespace": namespace,
            "labels": metadata_labels,
        }
        if self.annotations:
            metadata["annotations"] = dict(self.annotations)

        spec: Dict[str, object] = {
            "applications": list(self.applications),
            "origin": self.origin_namespace,
        }
        if self.environment:
            spec["environment"] = self.environment
        if self.pipeline_ref:
            spec["pipelineRef"] = self.pipeline_ref
        if self.service_account:
            spec["serviceAccount"] = self.service_account
        if self.policy:
            spec["policy"] = self.policy
        if self.data:
            spec["data"] = dict(self.data)

        return ResourceDefinition(
            api_version="appstudio.redhat.com/v1alpha1",
            kind="ReleasePlanAdmission",
            metadata=metadata,
            spec=spec,
        )
