from pathlib import Path

from konflux_automation.pipeline_editor import PipelineTweaker
from konflux_automation.cli import _discover_component_defaults


SAMPLE_PIPELINE = """apiVersion: tekton.dev/v1beta1
kind: PipelineRun
metadata:
  namespace: demo-tenant
  labels:
    appstudio.openshift.io/application: demo-app
    appstudio.openshift.io/component: demo-component
  annotations:
    build.appstudio.openshift.io/repo: https://github.com/example/repo
spec:
  params:
    - name: hermetic
      value: "false"
    - name: build-source-image
      value: "false"
    - name: dockerfile
      value: Containerfile
    - name: output-image
      value: quay.io/demo/demo-component:{{revision}}
  pipelineSpec:
    params:
      - name: path-context
        default: .
      - name: dockerfile
        default: Dockerfile
    tasks:
      - name: build
        taskRef:
          name: buildah
      - name: coverity
        taskRef:
          name: sast-coverity-check
"""


def test_pipeline_editor_sets_params_and_removes_coverity(tmp_path: Path) -> None:
    tekton_dir = tmp_path / ".tekton"
    tekton_dir.mkdir()
    pipeline_file = tekton_dir / "component-push.yaml"
    pipeline_file.write_text(SAMPLE_PIPELINE)

    tweaker = PipelineTweaker(tmp_path)
    updated = tweaker.apply_defaults()

    assert pipeline_file in updated
    content = pipeline_file.read_text()
    assert "name: hermetic" in content
    assert "value: \"true\"" in content
    assert "name: build-source-image" in content
    assert "coverity" not in content


def test_discover_component_defaults(tmp_path: Path) -> None:
    tekton_dir = tmp_path / ".tekton"
    tekton_dir.mkdir()
    pipeline_file = tekton_dir / "component-push.yaml"
    pipeline_file.write_text(SAMPLE_PIPELINE)

    detected = _discover_component_defaults(tmp_path)
    assert len(detected) == 1
    defaults = detected[0]
    assert defaults.name == "demo-component"
    assert defaults.application == "demo-app"
    assert defaults.namespace == "demo-tenant"
    assert defaults.git_url == "https://github.com/example/repo"
    assert defaults.git_context == "."
    assert defaults.dockerfile == "Containerfile"
    assert defaults.container_image == "quay.io/demo/demo-component"
