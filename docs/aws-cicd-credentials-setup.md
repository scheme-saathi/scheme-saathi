# AWS CI/CD credentials setup

This guide explains where to configure credentials and deployment settings for
`.github/workflows/cicd.yaml`. It uses GitHub Actions to test the application,
push a Docker image to Docker Hub, and deploy that image to Amazon ECS on
Fargate.

Never put real credentials in this repository, workflow YAML, task-definition
JSON, or logs. Store GitHub credentials in GitHub Actions secrets and
application/runtime credentials in AWS Secrets Manager.

## 1. Create the required AWS and Docker resources

Before configuring GitHub, create:

1. A Docker Hub repository for the image. Record its full name in the form
   `dockerhub-username/image-name`.
2. An AWS region, ECS cluster, Fargate service, and task definition.
3. An Application Load Balancer (recommended for public access) with HTTPS,
   forwarding to container port `8501`. Use `/_stcore/health` for the target
   group health check. Do not expose port `8501` directly to the public
   internet.
4. An ECS task execution role and an ECS task role. The task execution role
   lets ECS pull images and retrieve configured secrets. The task role is for
   AWS API calls made by the application, if any.
5. A CloudWatch log group for the ECS service.

The workflow expects the task-definition file to exist in the repository. Set
`ECS_TASK_DEFINITION` to its repository-relative path, for example
`aws/task-definition.json`, and commit that file. Make sure its container name
matches `ECS_CONTAINER_NAME`, its port mapping includes `8501`, and it has the
task and execution role ARNs, log configuration, and application environment
settings.

The workflow replaces the container image with the SHA-tagged Docker Hub image
before registering the updated task definition. Do not store credentials or
secret values in the task-definition file.

## 2. Create Docker Hub push credentials

1. Sign in to Docker Hub and create the image repository.
2. Create a Docker Hub access token that has permission to push to that
   repository. Use a dedicated token rather than your account password.
3. Keep the token value private. You will add it to GitHub in the next section.

The `DOCKERHUB_REPOSITORY` GitHub variable must be the full image name, such as
`dockerhub-username/scheme-saathi`; do not include a tag or registry hostname.

If the Docker Hub repository is public, ECS can pull it without registry
credentials. If it is private, also create a separate **read-only** Docker Hub
token for ECS. In AWS Secrets Manager, create a secret with JSON content:

```json
{
  "username": "dockerhub-username",
  "password": "DOCKER_HUB_READ_ONLY_TOKEN"
}
```

In the ECS container definition, set `repositoryCredentials.credentialsParameter`
to that secret's ARN. Grant the ECS task execution role permission to read that
secret. Do not reuse the GitHub push token for ECS pulls.

## 3. Add GitHub Actions secrets and variables

In GitHub, open the repository, then go to **Settings → Environments**. Create
an environment named `production`. Configure its deployment branch rule to
allow only `main`; optionally require a reviewer before deployments.

Open the `production` environment's **Environment secrets** and add these
secrets:

| Secret name | Value |
|---|---|
| `DOCKERHUB_USERNAME` | Docker Hub account or organization username that can push to the image repository |
| `DOCKERHUB_TOKEN` | Docker Hub access token with push permission |
| `AWS_ROLE_TO_ASSUME` | ARN of the AWS IAM role for GitHub Actions OIDC, created in section 4 |

Add these **Environment variables** to the same `production` environment:

| Variable name | Example format / meaning |
|---|---|
| `AWS_REGION` | AWS region containing the ECS service, such as `ap-south-1` |
| `DOCKERHUB_REPOSITORY` | Full Docker Hub image name, `namespace/image` |
| `ECS_CLUSTER` | Existing ECS cluster name |
| `ECS_SERVICE` | ECS service name in that cluster |
| `ECS_TASK_DEFINITION` | Repository-relative JSON path, such as `aws/task-definition.json` |
| `ECS_CONTAINER_NAME` | Container name inside the task definition, such as `scheme-saathi` |

Use the exact names above; the workflow's preflight step checks that each value
is present before logging in or deploying. It reports missing names but never
prints secret values. It also checks that the task-definition file exists.

## 4. Configure AWS GitHub OIDC access

OIDC lets GitHub Actions assume an AWS role using a short-lived token; do not
create or store long-lived AWS access keys in GitHub.

### 4.1 Add the GitHub OIDC provider to AWS

In the AWS console, open **IAM → Identity providers**. If it does not already
exist in the AWS account, add an OpenID Connect provider with:

- Provider URL: `https://token.actions.githubusercontent.com`
- Audience: `sts.amazonaws.com`

An OIDC provider is generally created once per AWS account.

### 4.2 Create the GitHub Actions role

In **IAM → Roles → Create role**, choose **Web identity**, select the GitHub
OIDC provider, and use audience `sts.amazonaws.com`. Set the role's trust
relationship so it accepts tokens only for this repository's `production`
GitHub Environment. The expected subject for this repository is:

```text
repo:saurabh-sriva01/scheme-saathi:environment:production
```

The trust policy should include conditions equivalent to the following; review
the account's provider ARN and repository before saving:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::AWS_ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:saurabh-sriva01/scheme-saathi:environment:production"
        }
      }
    }
  ]
}
```

Replace `AWS_ACCOUNT_ID` with the AWS account ID. Do not broaden the subject
condition to all repositories. Because the workflow job uses the `production`
environment, the environment-form subject above is required. Restrict that
environment to the `main` branch in GitHub as described in section 3.

### 4.3 Grant only the deployment permissions

Attach a least-privilege policy to this role. It needs to register the task
definition, update and inspect the selected ECS service, and pass only the ECS
task and execution roles to ECS tasks. A starting permission set is:

- `ecs:RegisterTaskDefinition`
- `ecs:DescribeTaskDefinition`
- `ecs:DescribeServices`
- `ecs:UpdateService`
- `iam:PassRole`, restricted to the task role and task execution role ARNs,
  with `iam:PassedToService` set to `ecs-tasks.amazonaws.com`

Scope ECS service actions to the intended cluster/service where supported.
`ecs:RegisterTaskDefinition` may require `"Resource": "*"`; limit `iam:PassRole`
to the exact roles used by this task definition. The GitHub role does not need
Docker Hub or ECR permissions because the image is pushed to Docker Hub.

After creating the role, copy its ARN into the GitHub `AWS_ROLE_TO_ASSUME`
environment secret.

## 5. Put application credentials in AWS Secrets Manager

GitHub secrets are used by the build/deploy workflow; they are not automatically
passed into the running application. Add runtime settings to the ECS task
definition instead:

1. In AWS, open **Secrets Manager → Store a new secret**.
2. Create a separate secret for each sensitive application value. Copy each
   secret's ARN.
3. In the ECS container definition's `secrets` list, map each environment
   variable to its Secrets Manager ARN. For example:

   ```json
   "secrets": [
     {
       "name": "OPENROUTER_API_KEY",
       "valueFrom": "arn:aws:secretsmanager:AWS_REGION:AWS_ACCOUNT_ID:secret:scheme-saathi/openrouter-api-key"
     },
     {
       "name": "MOCK_PORTAL_AUTH_SECRET",
       "valueFrom": "arn:aws:secretsmanager:AWS_REGION:AWS_ACCOUNT_ID:secret:scheme-saathi/mock-portal-auth-secret"
     }
   ]
   ```

4. Grant the ECS **task execution role** `secretsmanager:GetSecretValue` for
   only the secrets referenced by this task. If a secret uses a customer
   managed KMS key, grant `kms:Decrypt` for that key as well.
5. Create a new task-definition revision and deploy it. ECS injects these
   values into the container when the task starts.

For model access, use one provider key:

- `OPENROUTER_API_KEY`, with `OPENROUTER_BASE_URL` set to
  `https://openrouter.ai/api/v1` if needed; or
- `OPENAI_API_KEY`, optionally with `OPENAI_BASE_URL` for an OpenAI-compatible
  endpoint.

Set `SUPERVISOR_MODEL` and `SPECIALIST_MODEL` to model IDs supported by the
selected provider. These model IDs and base URLs are configuration, not
credentials, and can be set in the task definition's `environment` list.
`MOCK_PORTAL_AUTH_SECRET` is needed for the mock approval/submission flow.

If Auth0 is enabled, set the following in the ECS task definition and Auth0
application/API configuration:

- `AUTH0_DOMAIN`
- `AUTH0_CLIENT_ID`
- `AUTH0_AUDIENCE`
- `AUTH0_REDIRECT_URI` set to the deployed HTTPS application URL
- `AUTH0_HOUSEHOLD_CLAIM`
- `AUTH0_ROLE_CLAIM` only if operator roles are used

The client ID, domain, audience, and claim names are not client secrets and may
be task-definition environment values. This app uses the Auth0 Authorization
Code flow with PKCE and does not use an Auth0 client secret. In the Auth0
application settings, add the exact deployed HTTPS URL as an allowed callback
URL. Configure the API to issue the configured household claim; do not accept
household identifiers from request input.

Do not set both provider keys unless the application is intentionally
configured to prefer OpenAI; its model factory selects `OPENAI_API_KEY` first
when both keys are present.

## 6. Run and verify deployment

1. Confirm the production environment secrets and variables are present.
2. Confirm `ECS_TASK_DEFINITION` points to a committed file and that its
   `ECS_CONTAINER_NAME` matches `ECS_CONTAINER_NAME` in GitHub.
3. Confirm the ECS service, roles, secrets, log group, network, and load
   balancer are ready.
4. Push a change to `main`, or use **Actions → CI/CD to AWS ECS → Run
   workflow** and select `main`.
5. In the workflow run, verify the tests pass, the configuration preflight
   passes, Docker Hub login and image push succeed, and ECS reaches a stable
   state.
6. Verify the ALB target is healthy and the HTTPS app URL loads. Check ECS
   service events and CloudWatch logs if the task fails to start.

The workflow serializes production deployments with the `deploy-production`
concurrency group and does not cancel an in-progress deployment. The preflight
only checks whether settings exist; Docker Hub login, AWS OIDC authentication,
and ECS deployment determine whether credentials and permissions are valid.

## 7. Secret handling checklist

- Never commit `.env`, access tokens, secret values, or real personal data.
- Use a Docker Hub access token, not an account password.
- Use GitHub OIDC rather than static AWS access keys.
- Keep GitHub push credentials separate from ECS pull credentials.
- Keep model and application secrets in AWS Secrets Manager, not plain task
  definition environment values.
- Restrict GitHub Environment deployment to `main` and consider requiring
  production approval.
- Rotate credentials if they are exposed, and update the corresponding GitHub
  secret or AWS Secrets Manager value.
