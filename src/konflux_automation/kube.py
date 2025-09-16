"""Low-level Kubernetes client helpers for Konflux automation."""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, Optional

from kubernetes import client, config
from kubernetes.client import ApiException
from kubernetes.dynamic import DynamicClient, ResourceInstance

from .config import KonfluxContext
from .resources.base import ResourceDefinition
from .utils import deep_merge


_LOG = logging.getLogger(__name__)


class KonfluxAPI:
    """Wrapper around the Kubernetes dynamic client with Konflux-specific helpers."""

    def __init__(self, context: KonfluxContext) -> None:
        self.context = context
        api_client = config.new_client_from_config(
            config_file=context.kubeconfig,
            context=context.context,
        )
        api_client.configuration.verify_ssl = context.verify_ssl
        self.api_client = api_client
        self.dynamic = DynamicClient(api_client)
        self.core_v1 = client.CoreV1Api(api_client)

    def apply(self, definition: ResourceDefinition, namespace: Optional[str] = None) -> Dict[str, Any]:
        """Create or update a resource to match the provided definition."""

        body = definition.to_dict()
        target_namespace = namespace or definition.namespace or self.context.namespace
        if target_namespace:
            body.setdefault("metadata", {})["namespace"] = target_namespace
        if not target_namespace and self._is_namespaced(definition.api_version, definition.kind):
            raise ValueError(
                f"Namespace must be provided for {definition.kind} resources."
            )

        resource = self.dynamic.resources.get(api_version=definition.api_version, kind=definition.kind)

        resource_name = definition.name
        if not resource_name:
            _LOG.debug("Creating %s %s with generated name", definition.kind, body.get("metadata"))
            created = resource.create(body=body, namespace=target_namespace)
            return created.to_dict() if isinstance(created, ResourceInstance) else created

        try:
            existing = resource.get(name=resource_name, namespace=target_namespace)
        except ApiException as exc:
            if exc.status == 404:
                _LOG.debug("Creating %s/%s", definition.kind, resource_name)
                created = resource.create(body=body, namespace=target_namespace)
                return created.to_dict() if isinstance(created, ResourceInstance) else created
            if exc.status in (401, 403):
                _LOG.info(
                    "Insufficient permissions to read %s/%s; attempting create-or-patch",
                    definition.kind,
                    resource_name,
                )
                return self._create_or_patch_without_get(
                    resource=resource,
                    definition=definition,
                    body=body,
                    namespace=target_namespace,
                )
            raise

        existing_dict = existing.to_dict()
        resource_version = existing_dict.get("metadata", {}).get("resourceVersion")
        sanitized_existing = self._sanitize_existing(existing_dict)
        merged_body = deep_merge(sanitized_existing, body)
        if resource_version:
            merged_body.setdefault("metadata", {})["resourceVersion"] = resource_version

        _LOG.debug("Updating %s/%s", definition.kind, resource_name)
        updated = resource.replace(name=resource_name, namespace=target_namespace, body=merged_body)
        return updated.to_dict() if isinstance(updated, ResourceInstance) else updated

    def _create_or_patch_without_get(
        self,
        resource: Any,
        definition: ResourceDefinition,
        body: Dict[str, Any],
        namespace: Optional[str],
    ) -> Dict[str, Any]:
        """Fallback used when GET permission is denied."""

        resource_name = definition.name
        if not resource_name:
            created = resource.create(body=body, namespace=namespace)
            return created.to_dict() if isinstance(created, ResourceInstance) else created

        try:
            created = resource.create(body=body, namespace=namespace)
            return created.to_dict() if isinstance(created, ResourceInstance) else created
        except ApiException as exc:
            if exc.status != 409:
                raise

        patch_body = copy.deepcopy(body)
        metadata = patch_body.get("metadata")
        if metadata:
            metadata.pop("namespace", None)
            metadata.pop("resourceVersion", None)

        _LOG.debug("Patching %s/%s without prior GET", definition.kind, resource_name)
        patched = resource.patch(
            name=resource_name,
            namespace=namespace,
            body=patch_body,
            content_type="application/merge-patch+json",
        )
        return patched.to_dict() if isinstance(patched, ResourceInstance) else patched

    def delete(self, api_version: str, kind: str, name: str, namespace: Optional[str] = None) -> None:
        """Delete a resource if it exists."""

        target_namespace = namespace or self.context.namespace
        resource = self.dynamic.resources.get(api_version=api_version, kind=kind)
        try:
            resource.delete(name=name, namespace=target_namespace)
            _LOG.info("Deleted %s/%s", kind, name)
        except ApiException as exc:
            if exc.status != 404:
                raise
            _LOG.debug("Resource %s/%s not found during delete", kind, name)

    def patch_annotations(
        self,
        api_version: str,
        kind: str,
        name: str,
        annotations: Dict[str, str],
        namespace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add or update a set of annotations on a resource."""

        target_namespace = namespace or self.context.namespace
        resource = self.dynamic.resources.get(api_version=api_version, kind=kind)
        instance = resource.get(name=name, namespace=target_namespace)
        existing_annotations = instance.metadata.annotations or {}
        merged_annotations = {**existing_annotations, **annotations}
        patch_body = {"metadata": {"annotations": merged_annotations}}
        patched = resource.patch(
            name=name,
            namespace=target_namespace,
            body=patch_body,
        )
        return patched.to_dict() if isinstance(patched, ResourceInstance) else patched

    def list_pipeline_runs(
        self,
        namespace: str,
        component_name: Optional[str] = None,
        limit: int = 10,
    ) -> list[Dict[str, Any]]:
        """Return pipeline runs filtered by component name."""

        pipeline_resource = self.dynamic.resources.get(api_version="tekton.dev/v1beta1", kind="PipelineRun")
        label_selector = None
        if component_name:
            label_selector = f"appstudio.openshift.io/component={component_name}"
        result = pipeline_resource.get(namespace=namespace, label_selector=label_selector)
        items = result.to_dict().get("items", [])
        items.sort(key=lambda item: item.get("metadata", {}).get("creationTimestamp", ""), reverse=True)
        return items[:limit]

    @staticmethod
    def _sanitize_existing(body: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = copy.deepcopy(body)
        metadata = sanitized.get("metadata", {})
        for field in [
            "creationTimestamp",
            "managedFields",
            "resourceVersion",
            "selfLink",
            "uid",
            "generation",
        ]:
            metadata.pop(field, None)
        sanitized.pop("status", None)
        return sanitized

    def _is_namespaced(self, api_version: str, kind: str) -> bool:
        """Best effort check to determine if a resource is namespaced."""

        try:
            resource = self.dynamic.resources.get(api_version=api_version, kind=kind)
        except ApiException as exc:  # pragma: no cover - fails fast
            _LOG.error("Failed to discover resource %s %s: %s", api_version, kind, exc)
            raise
        return resource.namespaced
