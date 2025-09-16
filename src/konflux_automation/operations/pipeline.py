"""Operations for interrogating pipeline runs."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from ..config import KonfluxContext
from ..kube import KonfluxAPI

_LOG = logging.getLogger(__name__)


class PipelineOperations:
    """Helpers for Tekton PipelineRun visibility."""

    def __init__(self, api: KonfluxAPI, context: KonfluxContext) -> None:
        self.api = api
        self.context = context

    def list_component_runs(
        self,
        component_name: str,
        namespace: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, object]]:
        target_namespace = namespace or self.context.namespace
        if not target_namespace:
            raise ValueError("Namespace must be provided to list pipeline runs.")
        _LOG.debug(
            "Listing latest %s pipeline runs for component %s in namespace %s",
            limit,
            component_name,
            target_namespace,
        )
        runs = self.api.list_pipeline_runs(target_namespace, component_name=component_name, limit=limit)
        return [self._summarise_pipeline_run(item) for item in runs]

    @staticmethod
    def _summarise_pipeline_run(item: Dict[str, object]) -> Dict[str, object]:
        metadata: Dict[str, object] = item.get("metadata", {})
        status: Dict[str, object] = item.get("status", {})
        condition_summary = PipelineOperations._extract_condition(status)
        return {
            "name": metadata.get("name"),
            "startTime": status.get("startTime"),
            "completionTime": status.get("completionTime"),
            "reason": condition_summary.get("reason"),
            "status": condition_summary.get("status"),
            "message": condition_summary.get("message"),
        }

    @staticmethod
    def _extract_condition(status: Dict[str, object]) -> Dict[str, Optional[str]]:
        conditions = status.get("conditions", []) or []
        if not isinstance(conditions, list):
            return {"status": None, "reason": None, "message": None}
        for condition in conditions:
            if condition.get("type") == "Succeeded":
                return {
                    "status": condition.get("status"),
                    "reason": condition.get("reason"),
                    "message": condition.get("message"),
                }
        if conditions:
            first = conditions[0]
            return {
                "status": first.get("status"),
                "reason": first.get("reason"),
                "message": first.get("message"),
            }
        return {"status": None, "reason": None, "message": None}
