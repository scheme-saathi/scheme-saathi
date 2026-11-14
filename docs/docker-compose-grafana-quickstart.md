# Run Streamlit and Grafana with Docker Compose

This quick start runs Streamlit, Prometheus, and Grafana together with one
Docker Compose command. Run the PowerShell commands from the repository root.

## One-time setup

1. Install and start Docker Desktop.
2. Rotate `METRICS_BEARER_TOKEN` if its previous value was shared or exposed.
   Generate a replacement:
   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   Set `OBSERVABILITY_ENABLED=true` and the new `METRICS_BEARER_TOKEN` in the
   repository-root `.env`. Keep the token private; do not put it in this
   document or commit `.env`.
3. Give Prometheus the same token in
   `observability\deploy\secrets\metrics_token`. Create the file with no
   trailing newline:
   ```powershell
   Set-Content -NoNewline -Path observability\deploy\secrets\metrics_token -Value "<your-new-token>"
   ```
   Replace the placeholder locally with the token from step 2.
4. If `observability\deploy\.env` does not already exist, copy the example:
   ```powershell
   Copy-Item observability\deploy\.env.example observability\deploy\.env
   ```
   Set `GRAFANA_ADMIN_PASSWORD` in `observability\deploy\.env`. Do not replace
   an existing file; edit it and preserve any settings you already use.

## Start the services

From the repository root, run:

```powershell
docker compose --env-file observability\deploy\.env -f observability\deploy\docker-compose.yml --profile app up -d --build
```

Compose builds the app and provisioned Grafana images, then starts all three
services. The app reads model and other runtime settings from the root `.env`.

Open:

- Streamlit: <http://localhost:8501>
- Grafana: <http://localhost:3000> (default username `admin`; use the password
  from `observability\deploy\.env`)
- Prometheus targets: <http://localhost:9090/targets> (the `scheme-saathi` job
  should become **UP**)

In Grafana, open **Dashboards > Scheme Saathi > Scheme Saathi**. Generate some
app activity; panels can take a minute to show data.

## Run prebuilt images from Docker Hub

Use this option to start the app and dashboard without building images locally.
Run the commands from the repository root in PowerShell.

1. Make sure the Docker Hub repositories have been published by CI. The
   application repository is the value of the GitHub Actions variable
   `DOCKERHUB_REPOSITORY` (format `namespace/image`). The Grafana repository
   appends `-grafana` to that name. For example, if the application image is
   `my-docker-user/scheme-saathi`, the Grafana image is
   `my-docker-user/scheme-saathi-grafana`.
2. Choose a tag that CI has pushed. For example, a successful push on the
   `main` branch publishes the `main` tag for both images. CI also publishes
   immutable `sha-<commit>` tags; use the same tag for the app and Grafana.
3. If either Docker Hub repository is private, sign in before continuing:
   ```powershell
   docker login
   ```
4. Configure the environment files from the one-time setup above:
   - In the root `.env`, provide the app's required model settings and set
     `OBSERVABILITY_ENABLED=true` and `METRICS_BEARER_TOKEN`.
   - In `observability\deploy\.env`, set `GRAFANA_ADMIN_PASSWORD`,
     `APP_IMAGE`, and `GRAFANA_IMAGE`. Use the same tag for both images, for
     example:
     ```dotenv
     APP_IMAGE=my-docker-user/scheme-saathi:main
     GRAFANA_IMAGE=my-docker-user/scheme-saathi-grafana:main
     ```
     Replace the example namespace and image names with the actual
     `DOCKERHUB_REPOSITORY` and its `-grafana` repository. These values are
     image references, not credentials.
5. From the repository root, run one command to pull the images and start the
   services without a local build:
   ```powershell
   docker compose --env-file observability\deploy\.env -f observability\deploy\docker-compose.yml --profile app up --pull always --no-build -d
   ```
6. Open Streamlit at <http://localhost:8501> and Grafana at
   <http://localhost:3000>. Sign into Grafana with username `admin` (unless
   `GRAFANA_ADMIN_USER` was changed) and the password from the deploy `.env`.
   In Grafana, open **Dashboards > Scheme Saathi > Scheme Saathi**. Check
   <http://localhost:9090/targets> and confirm the `scheme-saathi` target is
   **UP**.

## Stop the services

From the repository root:

```powershell
docker compose --env-file observability\deploy\.env -f observability\deploy\docker-compose.yml down
```

This stops the containers and keeps their named data volumes. Add `-v` only
when you intend to delete the Prometheus history, Grafana state, and app
document, memory, and checkpoint data.

## Troubleshooting

- **Compose asks for `GRAFANA_ADMIN_PASSWORD`:** confirm
  `observability\deploy\.env` exists and has a non-empty password.
- **The Prometheus target is down or Grafana shows no metrics:** confirm the
  root `.env` has `OBSERVABILITY_ENABLED=true` and the same
  `METRICS_BEARER_TOKEN` as `observability\deploy\secrets\metrics_token`.
  Recreate the app container after changing the root `.env`:
  ```powershell
  docker compose --env-file observability\deploy\.env -f observability\deploy\docker-compose.yml --profile app up -d
  ```
- **Grafana keeps using its old password:** changing the environment file does
  not reset the password in an existing Grafana volume. Reset it from the
  container or remove the Grafana volume only if its saved state can be
  discarded.
