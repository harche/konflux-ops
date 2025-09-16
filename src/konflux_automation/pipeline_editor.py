"""Helpers to update Tekton PipelineRun definitions in component repositories."""
from __future__ import annotations

from pathlib import Path
from typing import List

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

yaml = YAML()
yaml.preserve_quotes = True
yaml.explicit_start = False
yaml.width = 120
yaml.indent(mapping=2, sequence=4, offset=2)


class PipelineTweaker:
    """Apply opinionated defaults to Pipelines-as-Code definitions."""

    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root
        self.tekton_dir = repository_root / ".tekton"

    def apply_defaults(self) -> List[Path]:
        """Ensure hermetic builds, source image builds, and remove Coverity tasks."""

        if not self.tekton_dir.is_dir():
            return []

        updated_files: List[Path] = []
        for path in sorted(self.tekton_dir.glob("*.y*ml")):
            original = path.read_text()
            data = yaml.load(original)
            if not isinstance(data, dict) or data.get("kind") != "PipelineRun":
                continue
            changed = False
            changed |= self._ensure_param(data, "hermetic", "true")
            changed |= self._ensure_param(data, "build-source-image", "true")
            changed |= self._remove_coverity_tasks(data)
            if changed:
                with path.open("w") as stream:
                    yaml.dump(data, stream)
                updated_files.append(path)
        return updated_files

    def _ensure_param(self, data: CommentedMap, name: str, value: str) -> bool:
        spec = data.setdefault("spec", CommentedMap())
        params = spec.setdefault("params", CommentedSeq())
        if not isinstance(params, CommentedSeq):
            params = CommentedSeq(params or [])
            spec["params"] = params
        for entry in params:
            if isinstance(entry, dict) and entry.get("name") == name:
                if entry.get("value") != value:
                    entry["value"] = value
                    return True
                return False
        new_entry = CommentedMap()
        new_entry["name"] = name
        new_entry["value"] = value
        params.append(new_entry)
        return True

    def _remove_coverity_tasks(self, data: CommentedMap) -> bool:
        spec = data.get("spec")
        if not isinstance(spec, dict):
            return False
        pipeline_spec = spec.get("pipelineSpec")
        if not isinstance(pipeline_spec, dict):
            return False
        changed = False
        for key in ("tasks", "finally"):
            seq = pipeline_spec.get(key)
            if isinstance(seq, list):
                kept: List[CommentedMap] = []
                removed = False
                for task in seq:
                    if self._is_coverity_task(task):
                        removed = True
                        continue
                    kept.append(task)
                if removed:
                    pipeline_spec[key] = CommentedSeq(kept)
                    changed = True
        return changed

    @staticmethod
    def _is_coverity_task(task: CommentedMap) -> bool:
        if not isinstance(task, dict):
            return False
        name = str(task.get("name", "")).lower()
        if "coverity" in name:
            return True
        task_ref = task.get("taskRef")
        if isinstance(task_ref, dict):
            ref_name = str(task_ref.get("name", "")).lower()
            if "coverity" in ref_name or "sast-coverity" in ref_name:
                return True
        return False
