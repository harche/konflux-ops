"""Operations for managing secrets and linking them to service accounts."""
from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

from ..config import KonfluxContext
from ..kube import KonfluxAPI
from ..resources.secret import SecretConfig

_LOG = logging.getLogger(__name__)


class SecretOperations:
    """Manage creation of secrets and their association with service accounts."""

    def __init__(self, api: KonfluxAPI, context: KonfluxContext) -> None:
        self.api = api
        self.context = context

    def ensure_secret(self, cfg: SecretConfig) -> Dict[str, object]:
        definition = cfg.to_resource(self.context.namespace)
        _LOG.info("Ensuring Secret %s", definition.metadata.get("name"))
        return self.api.apply(definition)

    def link_secret_to_service_accounts(
        self,
        secret_name: str,
        service_accounts: Iterable[str],
        namespace: Optional[str] = None,
        image_pull_secret: bool = True,
    ) -> None:
        target_namespace = namespace or self.context.namespace
        if not target_namespace:
            raise ValueError("Namespace must be provided for linking secrets to service accounts.")

        for sa_name in service_accounts:
            _LOG.info("Linking Secret %s to ServiceAccount %s", secret_name, sa_name)
            self._link_secret_to_service_account(secret_name, sa_name, target_namespace, image_pull_secret)

    def _link_secret_to_service_account(
        self,
        secret_name: str,
        service_account: str,
        namespace: str,
        image_pull_secret: bool,
    ) -> None:
        service_account_obj = self.api.core_v1.read_namespaced_service_account(service_account, namespace)
        existing_secrets = [ref.name for ref in service_account_obj.secrets or []]
        if secret_name not in existing_secrets:
            existing_secrets.append(secret_name)
        existing_image_pull_secrets = [ref.name for ref in service_account_obj.image_pull_secrets or []]
        if image_pull_secret and secret_name not in existing_image_pull_secrets:
            existing_image_pull_secrets.append(secret_name)

        body: Dict[str, List[Dict[str, str]]] = {
            "secrets": [{"name": name} for name in existing_secrets],
        }
        if image_pull_secret:
            body["imagePullSecrets"] = [{"name": name} for name in existing_image_pull_secrets]

        self.api.core_v1.patch_namespaced_service_account(service_account, namespace, body)
