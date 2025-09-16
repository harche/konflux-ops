"""Operations for managing release resources."""
from __future__ import annotations

import logging
from typing import Dict

from ..config import KonfluxContext
from ..kube import KonfluxAPI
from ..resources.release import ReleaseConfig
from ..resources.release_plan import ReleasePlanConfig
from ..resources.release_plan_admission import ReleasePlanAdmissionConfig

_LOG = logging.getLogger(__name__)


class ReleaseOperations:
    """High level helper covering ReleasePlan, ReleasePlanAdmission, and Release objects."""

    def __init__(self, api: KonfluxAPI, context: KonfluxContext) -> None:
        self.api = api
        self.context = context

    def ensure_release_plan(self, cfg: ReleasePlanConfig) -> Dict[str, object]:
        definition = cfg.to_resource(self.context.namespace)
        _LOG.info(
            "Ensuring ReleasePlan %s targeting %s",
            definition.metadata.get("name"),
            definition.spec.get("target") if definition.spec else "",
        )
        return self.api.apply(definition)

    def ensure_release_plan_admission(self, cfg: ReleasePlanAdmissionConfig) -> Dict[str, object]:
        definition = cfg.to_resource(self.context.namespace)
        _LOG.info(
            "Ensuring ReleasePlanAdmission %s for origin %s",
            definition.metadata.get("name"),
            definition.spec.get("origin") if definition.spec else "",
        )
        return self.api.apply(definition)

    def create_release(self, cfg: ReleaseConfig) -> Dict[str, object]:
        definition = cfg.to_resource(self.context.namespace)
        _LOG.info(
            "Creating Release for snapshot %s via plan %s",
            definition.spec.get("snapshot") if definition.spec else "",
            definition.spec.get("releasePlan") if definition.spec else "",
        )
        return self.api.apply(definition)
