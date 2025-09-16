from konflux_automation.resources.application import ApplicationConfig
from konflux_automation.resources.component import ComponentConfig, GitSource, PipelineConfig
from konflux_automation.resources.release import ReleaseConfig
from konflux_automation.utils import deep_merge


def test_application_manifest():
    cfg = ApplicationConfig(name="demo", namespace="tenant", display_name="Demo")
    definition = cfg.to_resource()
    body = definition.to_dict()
    assert body["metadata"]["name"] == "demo"
    assert body["spec"]["displayName"] == "Demo"


def test_component_pipeline_annotation():
    cfg = ComponentConfig(
        name="comp",
        application="demo",
        namespace="tenant",
        git=GitSource(url="https://github.com/example/repo.git"),
        pipeline=PipelineConfig(name="custom", bundle="latest"),
    )
    body = cfg.to_resource().to_dict()
    annotations = body["metadata"]["annotations"]
    assert annotations["build.appstudio.openshift.io/request"] == "configure-pac"
    assert "custom" in annotations["build.appstudio.openshift.io/pipeline"]


def test_release_requires_name_or_generate_name():
    cfg = ReleaseConfig(generateName="demo-", releasePlan="plan", snapshot="snap", namespace="tenant")
    body = cfg.to_resource().to_dict()
    assert body["metadata"]["generateName"] == "demo-"


def test_deep_merge_preserves_existing_keys():
    base = {"metadata": {"annotations": {"a": "1"}, "labels": {"x": "y"}}, "spec": {"field": "old"}}
    new = {"metadata": {"annotations": {"b": "2"}}, "spec": {"field": "new"}}
    merged = deep_merge(base, new)
    assert merged["metadata"]["annotations"] == {"a": "1", "b": "2"}
    assert merged["metadata"]["labels"] == {"x": "y"}
    assert merged["spec"]["field"] == "new"
