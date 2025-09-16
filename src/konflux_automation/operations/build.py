"""Operations for managing applications and components."""
from __future__ import annotations

import logging
from typing import Dict, Optional

from ..config import KonfluxContext
from ..kube import KonfluxAPI
from ..resources.application import ApplicationConfig
from ..resources.component import ComponentConfig
from ..resources.image_repository import ImageRepositoryConfig

_LOG = logging.getLogger(__name__)


class BuildOperations:
    """High level helper covering application and component lifecycle tasks."""

    def __init__(self, api: KonfluxAPI, context: KonfluxContext) -> None:
        self.api = api
        self.context = context

    def ensure_application(self, cfg: ApplicationConfig) -> Dict[str, object]:
        """Create or update an application."""

        definition = cfg.to_resource(self.context.namespace)
        _LOG.info("Ensuring Application %s", definition.metadata.get("name"))
        return self.api.apply(definition)

    def ensure_component(self, cfg: ComponentConfig) -> Dict[str, object]:
        """Create or update a component."""

        definition = cfg.to_resource(self.context.namespace)
        application = definition.spec.get("application") if definition.spec else None
        _LOG.info(
            "Ensuring Component %s for application %s",
            definition.metadata.get("name"),
            application or "(unknown)",
        )
        return self.api.apply(definition)

    def ensure_image_repository(self, cfg: ImageRepositoryConfig) -> Dict[str, object]:
        """Create or update an image repository."""

        definition = cfg.to_resource(self.context.namespace)
        _LOG.info(
            "Ensuring ImageRepository %s for component %s",
            definition.metadata.get("name"),
            cfg.component,
        )
        return self.api.apply(definition)

    def trigger_component_build(self, component_name: str, namespace: Optional[str] = None) -> Dict[str, object]:
        """Trigger a new Pipelines-as-Code build for the component."""

        target_namespace = namespace or self.context.namespace
        if not target_namespace:
            raise ValueError("Namespace must be provided when triggering a component build.")
        _LOG.info("Triggering build for component %s in namespace %s", component_name, target_namespace)
        return self.api.patch_annotations(
            api_version="appstudio.redhat.com/v1alpha1",
            kind="Component",
            name=component_name,
            annotations={"build.appstudio.openshift.io/request": "trigger-pac-build"},
            namespace=target_namespace,
        )
