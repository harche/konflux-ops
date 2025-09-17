"""Command line entry point for Konflux automation."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import typer
from rich import box
from rich import print as rich_print
from rich.logging import RichHandler
from rich.table import Table

import yaml as pyyaml

from .config import AutomationConfig, KonfluxContext
from .kube import KonfluxAPI
from .operations.build import BuildOperations
from .operations.pipeline import PipelineOperations
from .operations.releases import ReleaseOperations
from .operations.secrets import SecretOperations
from .pipeline_editor import PipelineTweaker, yaml as tekton_yaml

TENANTS_REPO_URL = "git@gitlab.cee.redhat.com:releng/konflux-release-data.git"

app = typer.Typer(help="Automation tools for common Konflux operations.")


tenant_app = typer.Typer(help="Manage Konflux tenant namespaces and GitOps onboarding.")
app.add_typer(tenant_app, name="tenant")

tenant_configure_app = typer.Typer(help="Configure resources within an existing tenant.")
tenant_app.add_typer(tenant_configure_app, name="configure")

tenant_component_app = typer.Typer(help="Component helpers for a tenant.")
tenant_configure_app.add_typer(tenant_component_app, name="component")

build_app = typer.Typer(help="Trigger and inspect Konflux build activity.")
app.add_typer(build_app, name="build")

pipeline_app = typer.Typer(help="Work with Tekton pipelines in Konflux.")
app.add_typer(pipeline_app, name="pipeline")

secret_app = typer.Typer(help="Secret management helpers.")
app.add_typer(secret_app, name="secret")


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, log_time_format="%X")],
    )


def _create_api(context: KonfluxContext) -> KonfluxAPI:
    return KonfluxAPI(context)


def _run_apply(automation_config: AutomationConfig) -> None:
    context = automation_config.context
    api = _create_api(context)

    build_ops = BuildOperations(api, context)
    release_ops = ReleaseOperations(api, context)
    secret_ops = SecretOperations(api, context)

    if automation_config.secrets:
        for secret in automation_config.secrets:
            secret_ops.ensure_secret(secret)

    if automation_config.application:
        build_ops.ensure_application(automation_config.application)

    for component in automation_config.components:
        build_ops.ensure_component(component)

    for repo in automation_config.image_repositories:
        build_ops.ensure_image_repository(repo)

    for plan_admission in automation_config.release_plan_admissions:
        release_ops.ensure_release_plan_admission(plan_admission)

    for plan in automation_config.release_plans:
        release_ops.ensure_release_plan(plan)

    for release in automation_config.releases:
        release_ops.create_release(release)


@app.command("apply-config")
def apply_config(
    config_path: Path = typer.Argument(..., help="Path to the automation configuration file."),
    namespace: Optional[str] = typer.Option(None, help="Override the namespace defined in the config."),
    kube_context: Optional[str] = typer.Option(None, "--context", help="Override kubeconfig context."),
    kubeconfig: Optional[Path] = typer.Option(None, help="Path to kubeconfig file."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Apply the configuration file to the target Konflux cluster."""

    _configure_logging(verbose)
    automation_config = AutomationConfig.from_file(config_path)
    if namespace:
        automation_config.context.namespace = namespace
    if kube_context:
        automation_config.context.context = kube_context
    if kubeconfig:
        automation_config.context.kubeconfig = str(kubeconfig)

    _run_apply(automation_config)
    rich_print("[green]Configuration applied successfully.[/green]")


def _prompt_non_empty(message: str, default: Optional[str] = None) -> str:
    while True:
        value = typer.prompt(message, default=default)
        if value:
            return value
        typer.echo("Value cannot be empty. Please try again.")


def _prompt_user_list(
    role_label: str,
    *,
    required: bool = True,
    default_user: Optional[str] = None,
) -> List[str]:
    """Prompt the user for a list of usernames for the given role."""

    entries: List[str] = []
    index = 1
    while True:
        default_value = default_user if index == 1 and default_user else ""
        prompt = f"{role_label} user #{index} (leave blank to finish)"
        value = typer.prompt(prompt, default=default_value).strip()
        if not value:
            if entries or not required:
                break
            typer.echo(f"At least one {role_label.lower()} is required.")
            continue
        entries.append(value)
        index += 1
    return entries


def _write_config_file(config: AutomationConfig, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = config.model_dump(mode="json", exclude_none=True, by_alias=True)
    with destination.open("w") as stream:
        pyyaml.safe_dump(serialized, stream, sort_keys=False)


def _prompt_key_value_pairs(prompt_prefix: str) -> dict[str, str]:
    """Collect arbitrary key/value pairs from the user."""

    entries: dict[str, str] = {}
    index = 1
    while True:
        key_prompt = f"{prompt_prefix} key #{index} (leave blank to finish)"
        key = typer.prompt(key_prompt, default="").strip()
        if not key:
            break
        value = typer.prompt(f"Value for '{key}'").strip()
        entries[key] = value
        index += 1
    return entries


@dataclass
class ComponentDefaults:
    name: Optional[str] = None
    application: Optional[str] = None
    namespace: Optional[str] = None
    git_url: Optional[str] = None
    git_revision: Optional[str] = None
    git_context: Optional[str] = None
    dockerfile: Optional[str] = None
    container_image: Optional[str] = None


def _discover_component_defaults(repo_path: Path) -> List[ComponentDefaults]:
    tekton_dir = repo_path / ".tekton"
    if not tekton_dir.is_dir():
        return []

    discovered: dict[str, ComponentDefaults] = {}

    for pipeline_file in sorted(tekton_dir.glob("*.y*ml")):
        try:
            data = tekton_yaml.load(pipeline_file.read_text())
        except Exception:  # pragma: no cover - malformed YAML should not abort the wizard
            continue

        if not isinstance(data, dict):
            continue

        metadata = data.get("metadata", {}) or {}
        annotations = metadata.get("annotations", {}) or {}
        labels = metadata.get("labels", {}) or {}

        application = annotations.get("appstudio.openshift.io/application") or labels.get(
            "appstudio.openshift.io/application"
        )
        component_name = annotations.get("appstudio.openshift.io/component") or labels.get(
            "appstudio.openshift.io/component"
        )
        if not component_name:
            continue
        component_key = str(component_name)
        defaults = discovered.get(component_key)
        if not defaults:
            defaults = ComponentDefaults(name=component_key)
            discovered[component_key] = defaults

        if application and not defaults.application:
            defaults.application = str(application)

        namespace = metadata.get("namespace")
        if namespace and not defaults.namespace:
            defaults.namespace = str(namespace)

        repo = annotations.get("build.appstudio.openshift.io/repo")
        if repo and not defaults.git_url:
            repo_value = str(repo).split("?")[0]
            if "{{" not in repo_value:
                defaults.git_url = repo_value

        spec = data.get("spec", {}) or {}
        params = spec.get("params", []) or []

        def _param_value(name: str) -> Optional[str]:
            for entry in params:
                if isinstance(entry, dict) and entry.get("name") == name:
                    return entry.get("value")
            return None

        git_url_value = _param_value("git-url")
        if git_url_value and "{{" not in str(git_url_value) and not defaults.git_url:
            defaults.git_url = str(git_url_value)

        revision_value = _param_value("revision")
        if revision_value and "{{" not in str(revision_value) and not defaults.git_revision:
            defaults.git_revision = str(revision_value)

        dockerfile_value = _param_value("dockerfile")
        if dockerfile_value and "{{" not in str(dockerfile_value):
            defaults.dockerfile = str(dockerfile_value)

        output_image_value = _param_value("output-image")
        if output_image_value and not defaults.container_image:
            container = str(output_image_value)
            if ":{{" in container:
                container = container.split(":{{", 1)[0]
            if "{{" not in container:
                defaults.container_image = container

        pipeline_spec = spec.get("pipelineSpec", {}) or {}
        pipeline_params = pipeline_spec.get("params", []) or []

        def _pipeline_default(name: str) -> Optional[str]:
            for entry in pipeline_params:
                if isinstance(entry, dict) and entry.get("name") == name:
                    default_value = entry.get("default")
                    if default_value and "{{" not in str(default_value):
                        return str(default_value)
            return None

        if not defaults.git_context:
            defaults.git_context = _pipeline_default("path-context") or defaults.git_context
        if not defaults.dockerfile:
            defaults.dockerfile = _pipeline_default("dockerfile") or defaults.dockerfile

    return list(discovered.values())


def _select_component_defaults(options: List[ComponentDefaults]) -> Optional[ComponentDefaults]:
    if not options:
        return None
    if len(options) == 1:
        selected = options[0]
        rich_print(
            f"[cyan]Detected component {selected.name} (application: {selected.application or 'unknown'}, namespace: {selected.namespace or 'unknown'}).[/cyan]"
        )
        return selected

    rich_print("[cyan]Detected multiple components in .tekton/:[/cyan]")
    for index, entry in enumerate(options, start=1):
        rich_print(
            f"  {index}. {entry.name} (application: {entry.application or 'unknown'}, namespace: {entry.namespace or 'unknown'})"
        )

    while True:
        choice = typer.prompt(
            "Select component number to pre-fill defaults (0 to skip)",
            default="1",
        )
        if not choice.isdigit():
            rich_print("[yellow]Please enter a numeric choice.[/yellow]")
            continue
        index = int(choice)
        if index == 0:
            return None
        if 1 <= index <= len(options):
            return options[index - 1]
        rich_print("[yellow]Invalid selection. Try again.[/yellow]")


def _build_config_interactively(
    namespace_override: Optional[str],
    detected_defaults: Optional[ComponentDefaults] = None,
    *,
    allow_releases: bool = True,
) -> AutomationConfig:
    namespace_default = namespace_override or (detected_defaults.namespace if detected_defaults else None)
    namespace = _prompt_non_empty("Konflux tenant namespace", default=namespace_default)

    application_default = detected_defaults.application if detected_defaults else None
    application_name = _prompt_non_empty("Application name", default=application_default)
    display_name_default = detected_defaults.application if detected_defaults and detected_defaults.application else application_name
    display_name = typer.prompt("Application display name", default=display_name_default)

    component_default = detected_defaults.name if detected_defaults and detected_defaults.name else application_name
    component_name = _prompt_non_empty("Component name", default=component_default)

    git_url_default = detected_defaults.git_url if detected_defaults else None
    git_url = _prompt_non_empty("Component Git URL", default=git_url_default)

    revision_default = detected_defaults.git_revision if detected_defaults and detected_defaults.git_revision else "main"
    git_revision = typer.prompt("Git revision", default=revision_default)

    context_default = detected_defaults.git_context if detected_defaults and detected_defaults.git_context else "."
    git_context = typer.prompt("Git context (relative path)", default=context_default)

    dockerfile_default = detected_defaults.dockerfile if detected_defaults and detected_defaults.dockerfile else "Dockerfile"
    dockerfile = typer.prompt("Containerfile path", default=dockerfile_default)

    container_default = detected_defaults.container_image if detected_defaults and detected_defaults.container_image else ""
    container_image = typer.prompt(
        "Container image (leave blank to rely on ImageRepository/controller)",
        default=container_default,
    ).strip()

    create_image_repo = typer.confirm(
        "Create an ImageRepository resource?",
        default=bool(container_image or (detected_defaults and detected_defaults.container_image)),
    )
    image_repo_config = []
    if create_image_repo:
        image_repo_name = typer.prompt("ImageRepository name", default=component_name)
        default_image_repo = (
            container_image
            or (detected_defaults.container_image if detected_defaults and detected_defaults.container_image else None)
            or f"quay.io/ORG/{component_name}"
        )
        image_repo_path = _prompt_non_empty(
            "Image repository (e.g., quay.io/org/component)",
            default=default_image_repo,
        )
        visibility = typer.prompt("Image visibility", default="public")
        image_repo_config.append(
            {
                "name": image_repo_name,
                "application": application_name,
                "component": component_name,
                "image_name": image_repo_path,
                "visibility": visibility,
            }
        )

    release_plans: List[dict] = []
    release_plan_admissions: List[dict] = []
    if allow_releases:
        configure_releases = typer.confirm("Configure ReleasePlan and ReleasePlanAdmission?", default=True)
        if configure_releases:
            release_plan_name = typer.prompt("ReleasePlan name", default="sre-production")
            target_namespace = _prompt_non_empty("Managed target namespace", default=f"{namespace}-managed")
            pipeline_ref = typer.prompt("Release pipelineRef", default="managed-release")
            service_account = typer.prompt("Release pipeline serviceAccount", default="release-service-account")
            auto_release = typer.confirm("Enable automatic releases when tests pass?", default=True)
            release_plans.append(
                {
                    "name": release_plan_name,
                    "application": application_name,
                    "target_namespace": target_namespace,
                    "pipeline_ref": pipeline_ref,
                    "service_account": service_account or None,
                    "auto_release": auto_release,
                }
            )
            admission_namespace = typer.prompt(
                "ReleasePlanAdmission namespace",
                default=target_namespace,
            )
            policy = typer.prompt("Enterprise contract policy", default="@redhat")
            release_plan_admissions.append(
                {
                    "name": release_plan_name,
                    "namespace": admission_namespace,
                    "applications": [application_name],
                    "origin_namespace": namespace,
                    "pipeline_ref": pipeline_ref,
                    "policy": policy,
                }
            )

    context = KonfluxContext(namespace=namespace)

    application = {
        "name": application_name,
        "namespace": namespace,
        "display_name": display_name,
    }

    component = {
        "name": component_name,
        "application": application_name,
        "namespace": namespace,
        "git": {
            "url": git_url,
            "revision": git_revision,
            "context": git_context,
            "dockerfile": dockerfile,
        },
    }
    if container_image:
        component["container_image"] = container_image

    config = AutomationConfig.model_validate(
        {
            "context": context.model_dump(exclude_none=True),
            "application": application,
            "components": [component],
            "image_repositories": image_repo_config,
            "release_plans": release_plans,
            "release_plan_admissions": release_plan_admissions,
        }
    )
    return config


@tenant_app.command("create")
def tenant_create(
    workdir: Path = typer.Option(
        Path(tempfile.gettempdir()) / "konflux-release-data",
        "--workdir",
        help="Path where the konflux-release-data repository should live (default: /tmp/konflux-release-data).",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Clone konflux-release-data and run the tenant creation helper."""

    _configure_logging(verbose)

    if not shutil.which("git"):
        raise typer.Exit("git is required to create a tenant namespace.")

    destination = workdir.expanduser().resolve()
    repo_exists = destination.exists()
    if repo_exists:
        git_dir = destination / ".git"
        if not git_dir.is_dir():
            raise typer.Exit(
                f"{destination} exists but is not a git repository. Please choose an empty directory or remove it first."
            )
        rich_print(f"[cyan]Reusing existing konflux-release-data clone at {destination}.\n[/cyan]")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        rich_print(f"[cyan]Cloning konflux-release-data into {destination}...[/cyan]")
        clone_result = subprocess.run(
            ["git", "clone", TENANTS_REPO_URL, str(destination)],
            check=False,
        )
        if clone_result.returncode != 0:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            raise typer.Exit("Failed to clone konflux-release-data repository.")
    rich_print(f"[cyan]Using konflux-release-data repository at {destination}. Remove it manually when finished if desired.[/cyan]")

    tenants_dir = destination / "tenants-config"
    script_path = tenants_dir / "add-namespace.sh"
    if not script_path.exists():
        raise typer.Exit("Could not find add-namespace.sh inside tenants-config. Verify the repository layout.")

    clusters: List[str] = []
    clusters_result = subprocess.run(
        ["bash", str(script_path), "clusters"],
        cwd=str(tenants_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    cluster_options: List[str] = []
    if clusters_result.returncode == 0:
        cluster_options = [line.strip() for line in clusters_result.stdout.splitlines() if line.strip()]
        if cluster_options:
            rich_print(
                "\n[bold]Available clusters (see https://konflux.pages.redhat.com/docs/users/deployments.html for details):[/bold]"
            )
            rich_print("  [cyan]0[/cyan]. [italic]Enter cluster manually[/italic]")
            for idx, entry in enumerate(cluster_options, start=1):
                rich_print(f"  [cyan]{idx}[/cyan]. {entry}")
    else:
        message = clusters_result.stderr.strip() or "add-namespace.sh clusters did not complete successfully."
        rich_print(
            f"[yellow]Unable to list clusters automatically: {message} "
            "(you can still enter the cluster name manually).[/yellow]"
        )

    default_user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    rich_print("\n[bold]Tenant namespace details[/bold]")
    cluster: Optional[str] = None
    if cluster_options:
        while cluster is None:
            choice = typer.prompt("Select cluster number", default="0").strip()
            if choice.isdigit():
                idx = int(choice)
                if idx == 0:
                    cluster = _prompt_non_empty("Target Konflux cluster")
                elif 1 <= idx <= len(cluster_options):
                    cluster = cluster_options[idx - 1]
                else:
                    rich_print("[yellow]Invalid selection. Choose a number from the list or 0 for manual entry.[/yellow]")
            else:
                rich_print("[yellow]Please enter a numeric selection.[/yellow]")
    else:
        cluster = _prompt_non_empty("Target Konflux cluster")
    namespace = _prompt_non_empty("Tenant namespace (e.g., my-team-tenant)")
    if not namespace.endswith("-tenant"):
        if typer.confirm("Namespace does not end with '-tenant'. Append '-tenant'?", default=True):
            namespace = f"{namespace}-tenant"

    size_options: List[str] = []
    sizes_result = subprocess.run(
        ["bash", str(script_path), "sizes"],
        cwd=str(tenants_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if sizes_result.returncode == 0:
        size_options = [line.strip() for line in sizes_result.stdout.splitlines() if line.strip()]
        if size_options:
            rich_print("\n[bold]Available quota sizes (use 0 to enter manually):[/bold]")
            rich_print("  [cyan]0[/cyan]. [italic]Enter size manually[/italic]")
            for idx, entry in enumerate(size_options, start=1):
                rich_print(f"  [cyan]{idx}[/cyan]. {entry}")
    else:
        message = sizes_result.stderr.strip() or "add-namespace.sh sizes did not complete successfully."
        rich_print(
            f"[yellow]Unable to list sizes automatically: {message} (you can still enter the size manually).[/yellow]"
        )

    size: Optional[str] = None
    if size_options:
        while size is None:
            choice = typer.prompt("Select quota size number", default="1").strip()
            if choice.isdigit():
                idx = int(choice)
                if idx == 0:
                    size = _prompt_non_empty("Quota size", default=None)
                elif 1 <= idx <= len(size_options):
                    size = size_options[idx - 1]
                else:
                    rich_print("[yellow]Invalid selection. Choose a number from the list or 0 for manual entry.[/yellow]")
            else:
                rich_print("[yellow]Please enter a numeric selection.[/yellow]")
    else:
        size = _prompt_non_empty("Quota size (run add-namespace.sh sizes for options)", default="1.small")

    rich_print("\n[bold]Assign users to roles[/bold]")
    primary_user = typer.prompt("Default username for role prompts", default=default_user).strip()
    admins = _prompt_user_list("Admin", default_user=primary_user or None)
    contributors = _prompt_user_list("Contributor", default_user=primary_user or None)
    maintainers = _prompt_user_list("Maintainer", default_user=primary_user or None)
    codeowners = _prompt_user_list("Codeowner", default_user=primary_user or None)

    rich_print("\n[bold]Labels[/bold]")
    cost_center = _prompt_non_empty("Cost center (numeric string)", default="000")

    rich_print("\n[bold]Summary[/bold]")
    summary_table = Table(
        title="[bold]Tenant configuration summary[/bold]",
        show_header=True,
        header_style="bold magenta",
        box=box.ROUNDED,
    )
    summary_table.add_column("Field", style="cyan", no_wrap=True)
    summary_table.add_column("Value", style="green")
    summary_table.add_row("Repository", str(destination))
    summary_table.add_row("Cluster", cluster)
    summary_table.add_row("Namespace", namespace)
    summary_table.add_row("Size", size)
    summary_table.add_row("Admins", ", ".join(admins))
    summary_table.add_row("Contributors", ", ".join(contributors))
    summary_table.add_row("Maintainers", ", ".join(maintainers))
    summary_table.add_row("Codeowners", ", ".join(codeowners))
    summary_table.add_row("Labels", f"cost-center:{cost_center}")
    rich_print(summary_table)

    if not typer.confirm("Proceed with tenant creation?", default=True):
        rich_print("[yellow]Aborted by user.[/yellow]")
        raise typer.Exit()

    command = [
        "bash",
        str(script_path),
        "create",
        "--cluster",
        cluster,
        "--namespace",
        namespace,
        "--size",
        size,
    ]
    for admin in admins:
        command.extend(["--admin", admin])
    for contributor in contributors:
        command.extend(["--contributor", contributor])
    for maintainer in maintainers:
        command.extend(["--maintainer", maintainer])
    for codeowner in codeowners:
        command.extend(["--codeowner", codeowner])
    command.extend(["--label", f"cost-center:{cost_center}"])

    rich_print("\n[cyan]Running add-namespace.sh...[/cyan]")
    result = subprocess.run(command, cwd=str(tenants_dir), check=False)
    if result.returncode != 0:
        raise typer.Exit("add-namespace.sh failed. Review the output above for details.")

    rich_print("\n[green]Tenant manifests generated successfully.[/green]")

    build_script = tenants_dir / "build-manifests.sh"
    if build_script.exists():
        rich_print("[cyan]Running build-manifests.sh to refresh auto-generated manifests...[/cyan]")
        build_result = subprocess.run(
            ["bash", str(build_script)],
            cwd=str(tenants_dir),
            check=False,
        )
        if build_result.returncode == 0:
            rich_print("[green]Auto-generated manifests updated.[/green]")
        else:
            rich_print(
                "[yellow]build-manifests.sh reported an error; review its output and rerun manually.[/yellow]"
            )
    else:
        rich_print(
            f"[yellow]Skipping build-manifests.sh; script not found at {build_script}."
        )

    rich_print("Next steps:")
    rich_print(f"  1. [cyan]cd {destination}[/cyan]")
    rich_print("  2. Review changes with `git status` and `git diff`")
    rich_print("  3. Commit, push, and open a merge request for konflux-release-data")
    rich_print("  4. Wait for ArgoCD to apply the new tenant namespace after merge")


@tenant_component_app.command("add")
def tenant_add_component(
    namespace: Optional[str] = typer.Option(None, help="Tenant namespace to target."),
    repo_path: Path = typer.Option(Path("."), help="Repository containing .tekton/ for defaults."),
    output: Optional[Path] = typer.Option(None, "--output", help="Where to write the generated config."),
    update_pipelines: Optional[bool] = typer.Option(
        None,
        "--update-pipelines/--skip-pipelines",
        help="Update Pipelines-as-Code defaults in the repository.",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Interactively add an application/component pair for an existing tenant."""

    _configure_logging(verbose)

    repo = repo_path.expanduser().resolve()
    detected_components = _discover_component_defaults(repo)
    selected_defaults = _select_component_defaults(detected_components)
    automation_config = _build_config_interactively(
        namespace,
        selected_defaults,
        allow_releases=False,
    )

    output_path = output or Path(
        typer.prompt(
            "Where should we write the generated configuration?",
            default="konflux-component.yaml",
        )
    ).expanduser().resolve()
    _write_config_file(automation_config, output_path)
    rich_print(f"[green]Saved configuration to {output_path}.[/green]")

    update_choice = (
        update_pipelines
        if update_pipelines is not None
        else typer.confirm("Update Pipelines-as-Code defaults?", default=True)
    )
    if update_choice:
        tweaker = PipelineTweaker(repo)
        updated = tweaker.apply_defaults()
        if updated:
            relative_paths = ", ".join(str(path.relative_to(repo)) for path in updated)
            rich_print(
                f"[green]Updated Pipelines-as-Code defaults in: {relative_paths}.[/green]"
            )
        else:
            rich_print(
                "[yellow]No Pipelines-as-Code files were updated (check the repository path or the presence of .tekton/).[/yellow]"
            )


@tenant_component_app.command("add-fbc")
def tenant_add_component_fbc(
    namespace: Optional[str] = typer.Option(None, help="Tenant namespace to target."),
    application: Optional[str] = typer.Option(None, help="Application name associated with the catalog."),
    ocp_minor: Optional[str] = typer.Option(None, help="OCP minor version (e.g., 4.19)."),
    stage: str = typer.Option("stage", help="Release stage (stage or prod)."),
    output: Optional[Path] = typer.Option(None, "--output", help="Where to write the generated config."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Scaffold File-Based Catalog release resources for a tenant component."""

    _configure_logging(verbose)

    tenant_namespace = _prompt_non_empty("Tenant namespace", default=namespace)
    application_name = _prompt_non_empty("Application name", default=application)
    ocp_version = _prompt_non_empty("OCP minor version (e.g., 4.19)", default=ocp_minor)
    sanitized_version = ocp_version.replace(".", "")
    catalog_identifier = f"{application_name}-fbc-{sanitized_version}-{stage}"
    release_plan_name = f"{catalog_identifier}-release-plan"
    default_target = f"{tenant_namespace}-{stage}" if stage else tenant_namespace
    target_namespace = _prompt_non_empty("Target namespace for releases", default=default_target)
    pipeline_ref = typer.prompt("Release pipelineRef", default="managed-release")
    service_account = typer.prompt("Release pipeline serviceAccount", default="release-service-account")
    auto_release = typer.confirm("Enable automatic releases when tests pass?", default=True)
    admission_namespace = typer.prompt(
        "ReleasePlanAdmission namespace",
        default=target_namespace,
    )
    policy = typer.prompt("Enterprise contract policy", default="@redhat")

    catalog_labels = {
        "konflux.appstudio.redhat.com/catalog": catalog_identifier,
        "konflux.appstudio.redhat.com/catalog-stage": stage,
        "konflux.appstudio.redhat.com/catalog-version": ocp_version,
    }

    context = KonfluxContext(namespace=tenant_namespace)
    config = AutomationConfig.model_validate(
        {
            "context": context.model_dump(exclude_none=True),
            "release_plans": [
                {
                    "name": release_plan_name,
                    "application": application_name,
                    "target_namespace": target_namespace,
                    "pipeline_ref": pipeline_ref,
                    "service_account": service_account or None,
                    "auto_release": auto_release,
                    "labels": catalog_labels,
                }
            ],
            "release_plan_admissions": [
                {
                    "name": release_plan_name,
                    "namespace": admission_namespace,
                    "applications": [application_name],
                    "origin_namespace": tenant_namespace,
                    "pipeline_ref": pipeline_ref,
                    "policy": policy,
                    "labels": catalog_labels,
                }
            ],
        }
    )

    output_path = output or Path(
        typer.prompt(
            "Where should we write the generated configuration?",
            default=f"konflux-release-{catalog_identifier}.yaml",
        )
    ).expanduser().resolve()
    _write_config_file(config, output_path)
    rich_print(f"[green]Saved FBC release configuration to {output_path}.[/green]")


@tenant_configure_app.command("release")
def tenant_add_release(
    namespace: Optional[str] = typer.Option(None, help="Tenant namespace containing the application."),
    output: Optional[Path] = typer.Option(None, "--output", help="Where to write the generated config."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Add ReleasePlan and ReleasePlanAdmission definitions for an existing tenant."""

    _configure_logging(verbose)

    tenant_namespace = _prompt_non_empty("Tenant namespace", default=namespace)
    application_name = _prompt_non_empty("Application name")
    release_plan_name = typer.prompt("ReleasePlan name", default=f"{application_name}-release")
    target_namespace = _prompt_non_empty(
        "Managed target namespace",
        default=f"{tenant_namespace}-managed",
    )
    pipeline_ref = typer.prompt("Release pipelineRef", default="managed-release")
    service_account = typer.prompt("Release pipeline serviceAccount", default="release-service-account")
    auto_release = typer.confirm("Enable automatic releases when tests pass?", default=True)
    admission_namespace = typer.prompt(
        "ReleasePlanAdmission namespace",
        default=target_namespace,
    )
    policy = typer.prompt("Enterprise contract policy", default="@redhat")

    context = KonfluxContext(namespace=tenant_namespace)
    config = AutomationConfig.model_validate(
        {
            "context": context.model_dump(exclude_none=True),
            "release_plans": [
                {
                    "name": release_plan_name,
                    "application": application_name,
                    "target_namespace": target_namespace,
                    "pipeline_ref": pipeline_ref,
                    "service_account": service_account or None,
                    "auto_release": auto_release,
                }
            ],
            "release_plan_admissions": [
                {
                    "name": release_plan_name,
                    "namespace": admission_namespace,
                    "applications": [application_name],
                    "origin_namespace": tenant_namespace,
                    "pipeline_ref": pipeline_ref,
                    "policy": policy,
                }
            ],
        }
    )

    output_path = output or Path(
        typer.prompt(
            "Where should we write the generated configuration?",
            default="konflux-release.yaml",
        )
    ).expanduser().resolve()
    _write_config_file(config, output_path)
    rich_print(f"[green]Saved configuration to {output_path}.[/green]")


@tenant_configure_app.command("secret")
def tenant_add_secret(
    namespace: Optional[str] = typer.Option(None, help="Tenant namespace where the secret will live."),
    output: Optional[Path] = typer.Option(None, "--output", help="Where to write the generated config."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Create a Konflux automation config snippet for a Kubernetes secret."""

    _configure_logging(verbose)

    tenant_namespace = _prompt_non_empty("Tenant namespace", default=namespace)
    secret_name = _prompt_non_empty("Secret name")
    secret_type = typer.prompt("Secret type", default="Opaque")
    rich_print("\n[bold]Provide base64 encoded values in data or plain text in stringData.[/bold]")
    data_entries = _prompt_key_value_pairs("data")
    string_data_entries = _prompt_key_value_pairs("stringData")
    if not data_entries and not string_data_entries:
        rich_print("[yellow]No key/value pairs provided; generating an empty secret wrapper.[/yellow]")

    context = KonfluxContext(namespace=tenant_namespace)
    config = AutomationConfig.model_validate(
        {
            "context": context.model_dump(exclude_none=True),
            "secrets": [
                {
                    "name": secret_name,
                    "namespace": tenant_namespace,
                    "type": secret_type,
                    "data": data_entries or None,
                    "string_data": string_data_entries or None,
                }
            ],
        }
    )

    output_path = output or Path(
        typer.prompt(
            "Where should we write the generated configuration?",
            default="konflux-secret.yaml",
        )
    ).expanduser().resolve()
    _write_config_file(config, output_path)
    rich_print(f"[green]Saved configuration to {output_path}.[/green]")


@tenant_configure_app.command("wizard")
def tenant_wizard(
    namespace: Optional[str] = typer.Option(None, help="Default namespace to pre-fill during the wizard."),
    config_path: Optional[Path] = typer.Option(None, help="Advanced: path to an existing config YAML to use instead of the wizard."),
    repo_path: Path = typer.Option(Path("."), help="Path to the component repository containing the .tekton/ directory."),
    skip_pipeline: bool = typer.Option(False, help="Do not update Pipelines-as-Code files."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Full interactive wizard to configure components and release artifacts."""

    _configure_logging(verbose)

    repo = repo_path.expanduser().resolve()

    if config_path:
        automation_config = AutomationConfig.from_file(config_path)
        output_path = config_path
    else:
        detected_components = _discover_component_defaults(repo)
        selected_defaults = _select_component_defaults(detected_components)
        automation_config = _build_config_interactively(namespace, selected_defaults)
        default_path = Path("konflux-config.yaml")
        path_str = typer.prompt(
            "Where should we write the generated configuration?",
            default=str(default_path),
        )
        output_path = Path(path_str).expanduser().resolve()
        _write_config_file(automation_config, output_path)
        rich_print(f"[green]Saved configuration to {output_path}.[/green]")

    if not skip_pipeline:
        tweaker = PipelineTweaker(repo)
        updated = tweaker.apply_defaults()
        if updated:
            relative_paths = ", ".join(str(path.relative_to(repo)) for path in updated)
            rich_print(
                f"[green]Updated Pipelines-as-Code defaults in: {relative_paths}.[/green]"
            )
        else:
            rich_print(
                "[yellow]No Pipelines-as-Code files were updated (check the repository path or the presence of .tekton/).[/yellow]"
            )


@build_app.command("trigger")
def trigger_build(
    component_name: str = typer.Argument(..., help="Component name to trigger a PaC build for."),
    namespace: Optional[str] = typer.Option(None, help="Namespace containing the component."),
    kube_context: Optional[str] = typer.Option(None, "--context", help="Override kubeconfig context."),
    kubeconfig: Optional[Path] = typer.Option(None, help="Path to kubeconfig file."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Trigger a Konflux Pipelines-as-Code build for a component."""

    _configure_logging(verbose)
    context = KonfluxContext(
        namespace=namespace,
        context=kube_context,
        kubeconfig=str(kubeconfig) if kubeconfig else None,
    )
    api = _create_api(context)
    build_ops = BuildOperations(api, context)
    build_ops.trigger_component_build(component_name, namespace=namespace)
    rich_print(f"[green]Triggered build for component {component_name}.[/green]")


@pipeline_app.command("runs")
def pipeline_runs(
    component_name: str = typer.Argument(..., help="Component name to query pipeline runs for."),
    namespace: Optional[str] = typer.Option(None, help="Namespace containing the pipeline runs."),
    limit: int = typer.Option(5, help="Number of recent pipeline runs to display."),
    kube_context: Optional[str] = typer.Option(None, "--context", help="Override kubeconfig context."),
    kubeconfig: Optional[Path] = typer.Option(None, help="Path to kubeconfig file."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """List recent Tekton pipeline runs for a component."""

    _configure_logging(verbose)
    context = KonfluxContext(
        namespace=namespace,
        context=kube_context,
        kubeconfig=str(kubeconfig) if kubeconfig else None,
    )
    api = _create_api(context)
    pipeline_ops = PipelineOperations(api, context)
    summaries = pipeline_ops.list_component_runs(component_name, namespace=namespace, limit=limit)

    table = Table(title=f"Latest pipeline runs for {component_name}")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Reason")
    table.add_column("Start")
    table.add_column("Completion")

    for run in summaries:
        table.add_row(
            str(run.get("name", "")),
            str(run.get("status", "")),
            str(run.get("reason", "")),
            str(run.get("startTime", "")),
            str(run.get("completionTime", "")),
        )

    rich_print(table)


@secret_app.command("link")
def link_secret(
    secret_name: str = typer.Argument(..., help="Secret to link to service accounts."),
    service_accounts: List[str] = typer.Argument(..., help="Service account names to update."),
    namespace: Optional[str] = typer.Option(None, help="Namespace containing the service accounts."),
    kube_context: Optional[str] = typer.Option(None, "--context", help="Override kubeconfig context."),
    kubeconfig: Optional[Path] = typer.Option(None, help="Path to kubeconfig file."),
    skip_image_pull: bool = typer.Option(False, help="Do not add the secret to imagePullSecrets."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Link a secret to component-specific service accounts."""

    _configure_logging(verbose)
    context = KonfluxContext(
        namespace=namespace,
        context=kube_context,
        kubeconfig=str(kubeconfig) if kubeconfig else None,
    )
    api = _create_api(context)
    secret_ops = SecretOperations(api, context)
    secret_ops.link_secret_to_service_accounts(
        secret_name=secret_name,
        service_accounts=service_accounts,
        namespace=namespace,
        image_pull_secret=not skip_image_pull,
    )
    rich_print(
        f"[green]Secret {secret_name} linked to service accounts: {', '.join(service_accounts)}.[/green]"
    )
