# Konflux Automation Toolkit

Automation and orchestration helpers for Konflux custom resources built on top of the Kubernetes API. The package
translates the operational flows described in the Konflux documentation into repeatable Python and CLI workflows.

## Features

- Declarative configuration (YAML) for Applications, Components, ImageRepositories, Secrets, ReleasePlans,
  ReleasePlanAdmissions, and Releases.
- Safe create/update behaviour via the Kubernetes dynamic client, preserving existing metadata.
- Pipeline controls: trigger Pipelines-as-Code rebuilds and inspect recent Tekton PipelineRuns.
- Secret helpers for linking registry credentials to build service accounts.

## Installation

### Option 1: Virtual Environment (Recommended)

Create and activate a virtual environment to isolate dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

To deactivate when done:
```bash
deactivate
```

### Option 2: System-wide Installation

Use your existing Python environment (3.9 or newer):

```bash
pip install -e .
```

The toolkit depends on `kubernetes`, `typer`, `pydantic`, `PyYAML`, and `rich`. Access to the target Konflux cluster
relies on your Kubernetes configuration (`~/.kube/config` by default).

## Guided tenant and component workflows

The CLI is organised into focused command groups so you only see options relevant to the task at hand.

### 1. Create or update tenant namespaces

```bash
konflux-ops tenant create
```

This clones (or reuses) `git@gitlab.cee.redhat.com:releng/konflux-release-data.git` to `/tmp/konflux-release-data` (configurable with `--workdir`), collects cluster/namespace details,
assigns admins/contributors/maintainers/codeowners, and executes `tenants-config/add-namespace.sh create`. After the tenant manifests are generated, the CLI automatically runs
`tenants-config/build-manifests.sh` so the `auto-generated/` content stays in sync. A summary of the next GitOps steps (review, commit, push, open an MR) is printed at the end.

### 2. Configure resources inside an existing tenant

- `konflux-ops tenant configure component add` – add an Application/Component/ImageRepository definition. Defaults are
  autodetected from `.tekton/` and you can choose whether to update Pipelines-as-Code after writing the YAML snippet.
- `konflux-ops tenant configure component add-fbc` – generate ReleasePlan/ReleasePlanAdmission pairs for File-Based Catalog (FBC) releases (stage/prod, version labels, etc.).
- `konflux-ops tenant configure release` – generate ReleasePlan and ReleasePlanAdmission manifests.
- `konflux-ops tenant configure secret` – scaffold Secrets with either base64 `data` or plaintext `stringData` keys.
- `konflux-ops tenant configure wizard` – run the end-to-end workflow (components + releases) in one session.

Every subcommand emits YAML snippets (`konflux-*.yaml` by default) that you can copy into the GitOps repository.

### 3. Operational helpers

- Trigger a Pipelines-as-Code build

  ```bash
  konflux-ops build trigger web --namespace dev-tenant
  ```

- Inspect recent Tekton PipelineRuns

  ```bash
  konflux-ops pipeline runs web --namespace dev-tenant --limit 5
  ```

- Link a registry secret to build service accounts

  ```bash
  konflux-ops secret link quay-robot build-pipeline-web --namespace dev-tenant
  ```

### 4. Work from declarative configuration

When you already have a YAML definition, add it to your GitOps checkout under the appropriate tenant directory and rerun `tenants-config/build-manifests.sh`. Review the changes, commit,
and open a merge request so ArgoCD applies them on the cluster.

## Declarative configuration

Create a YAML file describing the desired Konflux resources. Example:

```yaml
context:
  namespace: dev-tenant
  kubeconfig: ~/.kube/config
  context: konflux-cluster

application:
  name: demo-app
  display_name: Demo Application

components:
  - name: web
    application: demo-app
    git:
      url: https://github.com/example/demo.git
      revision: main
      context: services/web
      dockerfileUrl: Containerfile
    pipeline:
      name: konflux-default
      bundle: latest
    containerImage: quay.io/example/demo-web:latest

image_repositories:
  - name: web
    application: demo-app
    component: web
    image: quay.io/example/demo-web
    visibility: public

release_plan_admissions:
  - name: sre-production
    namespace: rhtap-releng-tenant
    applications: [demo-app]
    origin: dev-tenant
    pipelineRef: managed-release-pipeline
    policy: '@redhat'

release_plans:
  - name: sre-production
    application: demo-app
    target: rhtap-releng-tenant
    pipelineRef: managed-release-pipeline
    serviceAccount: release-sre

releases:
  - generateName: demo-app-release-
    releasePlan: sre-production
    snapshot: demo-app-2024-05-01
    author: demo-user

secrets:
  - name: quay-robot
    type: kubernetes.io/dockerconfigjson
    stringData:
      .dockerconfigjson: "${QUAY_DOCKERCONFIGJSON}"
```

To apply the definition, place it in the GitOps repository (for example under `tenants-config/cluster/<cluster>/tenants/<tenant>/`), reference it from the tenant `kustomization.yaml`, run
`tenants-config/build-manifests.sh`, then commit and push the resulting changes.

You can override the namespace, kubeconfig, or kube-context at the command line.
