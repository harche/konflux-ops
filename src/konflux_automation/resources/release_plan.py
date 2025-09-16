"""ReleasePlan resource builder."""
from __future__ import annotations

from typing import Dict, Optional

from pydantic import Field

from .base import ResourceDefinition, ResourceModel


class ReleasePlanConfig(ResourceModel):
    """Configuration for creating or updating a ReleasePlan."""

    name: str
    namespace: Optional[str] = None
    application: str
    target_namespace: str = Field(..., alias="target")
    auto_release: bool = Field(default=True, alias="autoRelease")
    standing_attribution: bool = Field(default=True)
    release_plan_admission: Optional[str] = Field(default=None, alias="releasePlanAdmission")
    pipeline_ref: Optional[str] = Field(default=None, alias="pipelineRef")
    service_account: Optional[str] = Field(default=None, alias="serviceAccount")
    release_grace_period_days: Optional[int] = Field(default=None, alias="releaseGracePeriodDays")
    data: Optional[Dict[str, object]] = None
    labels: Dict[str, str] = Field(default_factory=dict)
    annotations: Dict[str, str] = Field(default_factory=dict)

    def to_resource(self, default_namespace: Optional[str] = None) -> ResourceDefinition:
        namespace = self.namespace or default_namespace
        if not namespace:
            raise ValueError("Namespace must be provided for ReleasePlan resources.")

        metadata_labels: Dict[str, str] = {
            "release.appstudio.openshift.io/auto-release": str(self.auto_release).lower(),
            "release.appstudio.openshift.io/standing-attribution": str(self.standing_attribution).lower(),
        }
        if self.release_plan_admission:
            metadata_labels["release.appstudio.openshift.io/releasePlanAdmission"] = self.release_plan_admission
        metadata_labels.update(self.labels)

        metadata: Dict[str, object] = {
            "name": self.name,
            "namespace": namespace,
            "labels": metadata_labels,
        }
        if self.annotations:
            metadata["annotations"] = dict(self.annotations)

        spec: Dict[str, object] = {
            "application": self.application,
            "target": self.target_namespace,
        }
        if self.pipeline_ref:
            spec["pipelineRef"] = self.pipeline_ref
        if self.service_account:
            spec["serviceAccount"] = self.service_account
        if self.release_grace_period_days is not None:
            spec["releaseGracePeriodDays"] = self.release_grace_period_days
        if self.data:
            spec["data"] = dict(self.data)

        return ResourceDefinition(
            api_version="appstudio.redhat.com/v1alpha1",
            kind="ReleasePlan",
            metadata=metadata,
            spec=spec,
        )
