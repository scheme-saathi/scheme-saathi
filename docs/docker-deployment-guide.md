# Docker and AWS deployment guide

This guide covers building Scheme Saathi from a Dockerfile and running it
locally. Its ECS/Fargate section is an optional deployment alternative. The
current [CI/CD workflow](../.github/workflows/cicd.yaml) pushes to Docker Hub
and deploys to an EC2 instance with a self-hosted runner; see
[AWS EC2 CI/CD setup](aws-cicd-credentials-setup.md) for the active deployment.
Commands for your Windows development machine use PowerShell; GitHub Actions
scripts use a Linux shell.

## 1. Prerequisites

Install and start Docker Desktop, then open a terminal at the repository root.
Check that Docker is available:

```powershell
docker --version
docker info
```

The application listens on container port `8501`. The current repository
Dockerfile uses Python 3.12, installs the project and its RAG dependencies, and
runs Streamlit as a non-root user.

## 2. Create a Dockerfile from scratch

If the repository does not already have a `Dockerfile`, create one in the
repository root. This version installs the CPU build of PyTorch before the RAG
extras and copies the files needed by the application:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY .streamlit/ ./.streamlit/
COPY app/ ./app/
COPY agents/ ./agents/
COPY graph/ ./graph/
COPY servers/ ./servers/
COPY data/ ./data/

RUN python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && python -m pip install --no-cache-dir ".[rag]" \
    && mkdir -p data/private_documents \
    && addgroup --system app \
    && adduser --system --ingroup app app \
    && chown -R app:app /app

USER app

EXPOSE 8501

CMD ["streamlit", "run", "app/app_new.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
```

In this repository, the existing [Dockerfile](../Dockerfile) already contains
this configuration. Build context exclusions are controlled by
[.dockerignore](../.dockerignore); it excludes `.env`, private documents,
temporary files, and local Chroma backups. Review it before adding files or
data to an image.

### Package the ChromaDB database in the image

The Dockerfile's `COPY data/ ./data/` copies the approved local ChromaDB database
when `data/chroma/` exists in the build context. The repository's `.dockerignore`
allows that directory through. Before building, check that the database exists:

```powershell
Test-Path .\data\chroma\chroma.sqlite3
```

If the result is `False`, follow the README instructions to download or build
the approved database first. Baking the database into the image makes each
image self-contained, but changing the database requires building and
deploying a new image. Do not copy private documents, personal data, `.env`
files, or local Chroma backups into the image.

### Build without the ChromaDB database

The current Dockerfile copies all of `data/`, so a database-free image requires
changing the Dockerfile. For a separate variant, copy it first:

```powershell
Copy-Item .\Dockerfile .\Dockerfile.no-db
```

In `Dockerfile.no-db`, replace:

```dockerfile
COPY data/ ./data/
```

with explicit copies of only the reviewed runtime data required by the app:

```dockerfile
COPY data/schemes/ ./data/schemes/
COPY data/rules/ ./data/rules/
```

Only add other data directories if the deployment needs them and they contain
approved, non-personal data. Build this variant with `docker build -f
Dockerfile.no-db ...` (see the next section). With no database available,
scheme retrieval will not work; the image can still start, but the app cannot
provide database-backed search until a compatible database is supplied.

### Include the embedding model for vector search

The scheme search code loads `BAAI/bge-m3` with local-only model loading. The
current Dockerfile installs the Python packages but does not download the model
weights into the image. Therefore, a database in the image alone is not enough
for vector search in a clean container.

For an image that must support vector search, add these lines to the Dockerfile
after installing the project dependencies and before switching to `USER app`:

```dockerfile
ENV HF_HOME=/opt/huggingface

RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3', device='cpu')" \
    && chown -R app:app /opt/huggingface
```

This downloads a large model during the image build. Allow sufficient build
time, network access, and image storage. Keep `HF_HOME` the same at build and
runtime so the non-root application process can find the downloaded files.
If you use keyword search only, you can omit the model download.

## 3. Build the image

Run from the repository root so Docker can access the Dockerfile and files it
copies. Use a versioned tag in addition to `latest`:

```powershell
docker build -t scheme-saathi:local .
```

For the database-free variant:

```powershell
docker build -f .\Dockerfile.no-db -t scheme-saathi:local-no-db .
```

Check that the image was created:

```powershell
docker image ls scheme-saathi
```

Docker downloads the base image and dependencies on the first build. Later
builds may reuse cached layers. For a clean rebuild after changing dependencies
or diagnosing a stale build, use `--no-cache`:

```powershell
docker build --no-cache -t scheme-saathi:local .
```

## 4. Configure and run locally

Create a local environment file from the example and edit it with the values
needed for your test. Do not commit `.env` or put secrets in Docker build
arguments:

```powershell
Copy-Item .\.env.example .\.env
```

The model configuration uses `SUPERVISOR_MODEL`, `SPECIALIST_MODEL`, and either
`OPENROUTER_API_KEY` or `OPENAI_API_KEY`. Auth0 and mock-portal settings are
needed only for the corresponding features; see the README for their required
values. Use synthetic test data, never real identity or bank details.

Run the app, mapping host port 8501 to the container's port 8501. A named volume
keeps uploaded documents when the container is removed:

```powershell
docker run --name scheme-saathi `
  -p 8501:8501 `
  --env-file .env `
  --mount source=scheme-saathi-documents,target=/app/data/private_documents `
  scheme-saathi:local
```

Open <http://localhost:8501>. Stop the foreground container with `Ctrl+C`.
To stop it later from another terminal:

```powershell
docker stop scheme-saathi
```

Check the Streamlit health endpoint, container status, and logs:

```powershell
Invoke-WebRequest http://localhost:8501/_stcore/health
docker ps -a --filter name=scheme-saathi
docker logs scheme-saathi
```

To run a second instance without replacing the first, choose another container
name and host port, for example `-p 8502:8501`.

The ChromaDB database baked into the image is not changed by a Docker volume.
For local development with a separately mounted database instead, remove the
database from the image and mount a compatible directory at
`/app/data/chroma`. Do not run multiple writers against the same ChromaDB
directory.

## 5. Update or upgrade the image

When application code, dependencies, reviewed scheme data, the ChromaDB
database, or the embedding model changes:

1. Make and test the change in the repository.
2. Update dependency declarations in `pyproject.toml` when needed.
3. Build the image with a new, traceable tag:

   ```powershell
   docker build -t scheme-saathi:2026-11-09 .
   ```

4. Run and check the new image locally using the steps above. Confirm the
   expected database and model are available, and test the key application
   flow before replacing the old image.
5. Once the new image passes, stop and remove the old container, then start a
   container from the new tag with the same environment and document volume:

   ```powershell
   docker stop scheme-saathi
   docker rm scheme-saathi
   docker run --name scheme-saathi `
     -p 8501:8501 `
     --env-file .env `
     --mount source=scheme-saathi-documents,target=/app/data/private_documents `
     scheme-saathi:2026-11-09
   ```

For a dependency refresh without source changes, `docker build --no-cache` forces
Docker to rerun build steps, but it does not upgrade pinned or constrained
dependencies automatically. Change and review `pyproject.toml` explicitly.
Keep the previous image tag until the upgraded container is confirmed healthy
so you can start it again as a rollback.

## 6. Optional: deploy from GitHub to AWS ECS/Fargate

The instructions in this section describe an ECS/Fargate alternative, not the
repository's current workflow. The current workflow deploys directly to an EC2
host using a self-hosted runner. Do not configure ECS-specific variables for
the current workflow; follow the linked EC2 setup guide instead.

For step-by-step instructions to configure GitHub credentials, the EC2 runner,
and application settings, see
[AWS EC2 CI/CD setup](aws-cicd-credentials-setup.md).

### 6.1 Prepare AWS resources

1. Choose an AWS region and create an ECS cluster. Create a Docker Hub
   repository for the image. A public repository can be pulled by ECS without
   extra credentials; for a private repository, configure ECS repository
   credentials as described below.
2. Create a Fargate task definition with a container named `scheme-saathi`.
   Configure it to:
   - listen on container port `8501` using TCP;
   - allocate enough CPU and memory for Streamlit, ChromaDB, and (if included)
     the BGE-M3 model;
   - use an Application Load Balancer (ALB) for public HTTPS access, with its
     target group forwarding to port `8501`;
   - use `/_stcore/health` as the ALB health-check path;
   - put model/API credentials in AWS Secrets Manager or Systems Manager
     Parameter Store, and reference them from the task definition's `secrets`
     entries, not plain text `environment` values.
3. Create an ECS service using the task definition and the ALB. Configure HTTPS
   with an ACM certificate and a domain name. Do not expose port 8501 directly
   to the public internet. Allow the task to make outbound connections to the
   configured model provider; use a NAT gateway or the appropriate VPC
   endpoints for private subnets.
4. Add an EFS mount or another approved persistent store for uploaded documents
   if those must survive a task replacement, and set
   `SCHEME_SAATHI_DOCUMENT_STORE_DIR` to its mounted path. Restrict access,
   enable encryption, and apply the documented retention policy. The default
   Fargate task filesystem is ephemeral; local uploaded files can be lost when
   a task is replaced. Do not assume EFS is a safe shared writable location for
   ChromaDB's SQLite database. For this project's ChromaDB, bake the reviewed
   database into each image or select and validate an appropriate database
   service/storage design.
5. If using Auth0, configure the public HTTPS URL as an allowed callback URL and
   configure `AUTH0_REDIRECT_URI` to that URL. Set the required Auth0 values in
   the ECS task definition using secret references or non-secret environment
   settings as appropriate.
6. Create an IAM role for GitHub Actions using GitHub's OIDC provider. Its trust
   policy should restrict `token.actions.githubusercontent.com` to this
   repository and the deployment branch or GitHub Environment. Grant only the
   permissions needed to register task definitions, update the selected ECS
   service, and pass its task roles. The ECS task execution role separately
   needs permission to read the referenced secrets.

### 6.2 Configure GitHub

In repository **Settings → Secrets and variables → Actions**, add:

- Secret `AWS_ROLE_TO_ASSUME`: the ARN of the GitHub OIDC deployment role.
- Secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`: Docker Hub credentials
  for a token that can push to the repository.
- Variables `AWS_REGION`, `DOCKERHUB_REPOSITORY`, `ECS_CLUSTER`, `ECS_SERVICE`,
  `ECS_TASK_DEFINITION`, and `ECS_CONTAINER_NAME`.
- Set `DOCKERHUB_REPOSITORY` to the full image name, such as
  `your-dockerhub-user/scheme-saathi`.

For example, `ECS_TASK_DEFINITION` can be `aws/task-definition.json` and
`ECS_CONTAINER_NAME` can be `scheme-saathi`. Protect the deployment branch and
consider requiring approval through a GitHub Environment for production.

Create `aws/task-definition.json` in the repository with the ECS task definition
for the service. It must include the same container name as
`ECS_CONTAINER_NAME`, port mapping `8501`, the ECS task and execution role ARNs,
and `secrets` references for the environment variables needed by the app. Do
not put secret values in this file. ECS deployment needs these settings and
resources defined before the workflow can successfully start a task.

For a private Docker Hub repository, add `repositoryCredentials` to the ECS
container definition, pointing to an AWS Secrets Manager secret whose JSON
value has `username` and `password` fields. Use a Docker Hub read-only token
for this secret, and allow the ECS task execution role to read it. This is
separate from the GitHub `DOCKERHUB_TOKEN`, which needs permission to push.
Public Docker Hub repositories do not need `repositoryCredentials`.

For example, the container definition can follow this pattern; replace the
account, region, role, log-group, and secret ARN placeholders with real AWS
resource identifiers. This is a fragment for the container definition, not a
complete task definition:

```json
{
  "name": "scheme-saathi",
  "image": "REPLACED_BY_GITHUB_ACTIONS",
  "essential": true,
  "portMappings": [
    {
      "containerPort": 8501,
      "hostPort": 8501,
      "protocol": "tcp"
    }
  ],
  "environment": [
    {
      "name": "SUPERVISOR_MODEL",
      "value": "your-configured-model-id"
    },
    {
      "name": "SPECIALIST_MODEL",
      "value": "your-configured-model-id"
    }
  ],
  "secrets": [
    {
      "name": "OPENROUTER_API_KEY",
      "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT_ID:secret:scheme-saathi/openrouter-api-key"
    },
    {
      "name": "MOCK_PORTAL_AUTH_SECRET",
      "valueFrom": "arn:aws:secretsmanager:REGION:ACCOUNT_ID:secret:scheme-saathi/mock-portal-auth-secret"
    }
  ],
  "logConfiguration": {
    "logDriver": "awslogs",
    "options": {
      "awslogs-group": "/ecs/scheme-saathi",
      "awslogs-region": "REGION",
      "awslogs-stream-prefix": "ecs"
    }
  }
}
```

Create the CloudWatch log group and the secrets before registering the task
definition. Include Auth0 settings and either the OpenRouter or OpenAI key
required by your chosen configuration. The ECS task execution role needs
`secretsmanager:GetSecretValue` (and `kms:Decrypt` for a customer-managed KMS
key) for only the referenced secrets.

### 6.3 ECS workflow note

To use ECS/Fargate instead, create a separate ECS-specific workflow and configure
its ECR/ECS deployment settings. Do not overwrite
`.github/workflows/cicd.yaml`, which deploys to EC2. The ECS task definition,
GitHub OIDC role, task execution role, and task secrets described above are
specific to that alternative.

### 6.4 Deploy and verify

For the optional ECS/Fargate alternative, deploy using the separate ECS
workflow and verify the resulting ECS service. For the active EC2 deployment,
follow the run and troubleshooting steps in
[AWS EC2 CI/CD setup](aws-cicd-credentials-setup.md).

Deployments must use synthetic test profiles until privacy, authentication,
retention, access controls, and operational monitoring have been reviewed.
The current portal includes a mock submission workflow; it is not a connection
to a real government submission service.
