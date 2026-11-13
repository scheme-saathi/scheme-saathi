# Docker Deployment Guide

This guide explains how to build the Scheme Saathi application from a Dockerfile and run it locally.

The Grafana image is built using [`observability/deploy/grafana/Dockerfile`](../observability/deploy/grafana/Dockerfile). Its provisioning files are included in the image. The Grafana image's registry name is formed by appending `-grafana` to the configured `DOCKERHUB_REPOSITORY` value. For example: `your-dockerhub-user/scheme-saathi-grafana`.

GitHub Actions publishes both images with branch-specific tags and `sha-<commit>` tags.

## Run Published Images on a Clean Machine

Follow these steps to pull and run the application and Grafana images from Docker Hub.

The public Docker Hub repositories are `singhd4/scheme-saathi` and `singhd4/scheme-saathi-grafana`. Both images are available with `sha-<commit>` tags. Docker Compose also pulls the Prometheus image required by the dashboard.

1. Install and start Docker Desktop on Windows, or install Docker Engine and Docker Compose v2 on Linux.

2. Extract the `scheme-saathi-deploy` folder. 
   Open PowerShell or a terminal in that folder. 
   Ensure that it contains-
    `docker-compose.yml` `.env` and a `prometheus` folder with the `prometheus.yml` `rules.yml` `alerts.yml` and `metrics_token` files.

    Rename file `.env-example` with `.env`

3. Edit the `.env` file and set the values required for your deployment:

   ```dotenv
   OPENROUTER_API_KEY=<your-provider-api-key>
   MOCK_PORTAL_AUTH_SECRET=<a-unique-random-secret>   
   GRAFANA_ADMIN_PASSWORD=<a-strong-grafana-password> 
```

4. Since these Docker Hub repositories are public, you do not need to sign in to Docker Hub. If you want to pull the images manually, run:
 
   The following images will currently be pulled during deployment:
   ```
    Scheme Saathi:
    singhd4/scheme-saathi:sha-819791b72b002769938b1b4ad615813af2e6360c
    
    Grafana:
    singhd4/scheme-saathi-grafana:sha-819791b72b002769938b1b4ad615813af2e6360c    
    
   ```
   Manual image pulls are optional. The startup command in the next step automatically pulls the required images, including Prometheus.

5. From the `scheme-saathi-deploy` folder, pull and start the services:

   ```powershell
   docker compose --env-file .\.env up -d --pull always
   ```

   This command pulls all required images, including Prometheus, and starts the containers.

## Access the Services

Open the following URLs in your browser to access the services:

- **Streamlit:** http://localhost:8501
- **Grafana:** http://localhost:3000 (Log in with the username `admin` and the password specified in the `.env` file.)

All two services are accessible only from the local machine.

## Restart and Test the Application

Whenever you make changes to files in the `scheme-saathi-deploy` repository, run the following command to recreate the containers and apply those changes:

```powershell
docker compose --env-file .\.env up -d --force-recreate
```

After the containers restart, open their respective URLs and verify that all three services are running correctly.




