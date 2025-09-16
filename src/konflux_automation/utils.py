"""Utility helpers shared across the Konflux automation package."""
from __future__ import annotations

import copy
from typing import Any, Dict


def deep_merge(base: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep merge of ``base`` with ``new`` without mutating the inputs."""

    merged: Dict[str, Any] = copy.deepcopy(base)
    for key, value in new.items():
        if isinstance(value, dict):
            base_sub = merged.get(key, {})
            if not isinstance(base_sub, dict):
                merged[key] = copy.deepcopy(value)
            else:
                merged[key] = deep_merge(base_sub, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged
