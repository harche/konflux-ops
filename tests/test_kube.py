from unittest.mock import MagicMock
from kubernetes.client import ApiException

from konflux_automation.config import KonfluxContext
from konflux_automation.kube import KonfluxAPI
from konflux_automation.resources.base import ResourceDefinition


def _build_definition() -> ResourceDefinition:
    return ResourceDefinition(
        api_version="appstudio.redhat.com/v1alpha1",
        kind="ReleasePlanAdmission",
        metadata={"name": "example", "namespace": "tenant", "labels": {}},
        spec={"key": "value"},
    )


def _make_api() -> KonfluxAPI:
    api = KonfluxAPI.__new__(KonfluxAPI)
    api.context = KonfluxContext(namespace="tenant")
    api.dynamic = MagicMock()
    return api


def test_apply_creates_when_get_forbidden():
    api = _make_api()
    resource = MagicMock()
    api.dynamic.resources.get.return_value = resource
    resource.get.side_effect = ApiException(status=403, reason="forbidden")

    result = api.apply(_build_definition())

    assert result is resource.create.return_value
    resource.create.assert_called_once()
    resource.patch.assert_not_called()


def test_apply_patches_when_create_conflicts_on_forbidden_get():
    api = _make_api()
    resource = MagicMock()
    api.dynamic.resources.get.return_value = resource
    resource.get.side_effect = ApiException(status=403, reason="forbidden")

    resource.create.side_effect = ApiException(status=409, reason="conflict")

    result = api.apply(_build_definition())

    assert result is resource.patch.return_value
    resource.patch.assert_called_once()
