# Scheme Saathi: How to Run

Runs the Streamlit app and the Grafana dashboard on **Windows, macOS and Linux** with one command.
The images come from Docker Hub: `singhd4/scheme-saathi` and `singhd4/scheme-saathi-grafana`. Docker Compose also pulls `prom/prometheus`.

---

## What you need first

1. **Docker** installed and **running**. The setup script does **not** install Docker.

   | OS | Install |
   |----|---------|
   | Windows | [Docker Desktop](https://www.docker.com/products/docker-desktop/) |
   | macOS | [Docker Desktop](https://www.docker.com/products/docker-desktop/) |
   | Linux | [Docker Engine + Compose v2](https://docs.docker.com/engine/install/) |

   On Windows and macOS, start Docker Desktop and wait until it shows **Engine running**.

2. An **OpenRouter API key** (`OPENROUTER_API_KEY`). It is mandatory.
3. An internet connection for the first run, to pull the images.

---

## Step 1: Extract the folder

Unzip `scheme-saathi-deploy-installer.zip`. You should see:

```
scheme-saathi-deploy/
├── install.ps1          (Windows setup)
├── install.sh           (macOS / Linux setup)
├── docker-compose.yml
├── .env-example
└── prometheus/
    ├── prometheus.yml
    ├── rules.yml
    └── alerts.yml
```

## Step 2: Open a terminal in that folder

- **Windows:** open the folder in File Explorer, click the address bar, type `powershell` and press Enter.
- **macOS:** open Terminal, type `cd ` (with a space), drag the folder into the window and press Enter.
- **Linux:** open a terminal and `cd` into the folder.

## Step 3: Set permissions

On **macOS and Linux**, make the folder writable and the script executable before running it, so the installer can write `.env` and `prometheus/metrics_token`:

```bash
chmod -R u+w . && chmod +x install.sh
```

On **Windows**, nothing is needed: the `-ExecutionPolicy Bypass` flag in the next step lets the script run.

---

## Step 4: Run ONE command

| OS | Command |
|----|---------|
| **Windows** (PowerShell or CMD) | `powershell -ExecutionPolicy Bypass -File .\install.ps1` |
| **macOS / Linux** | `bash install.sh` |

The script will:

1. Check that Docker is installed and running.
2. Ask for your **`OPENROUTER_API_KEY`**. Typing is hidden, so paste the key and press Enter.
3. Create a readable `.env` file with all settings.
4. Pull the images from Docker Hub and start the containers.
5. Print the URLs once everything is up.

---

## Step 5: Open the apps

| App | URL | Login |
|-----|-----|-------|
| **Streamlit app** | http://localhost:8501 | Auth0 login |
| **Grafana dashboard** | http://localhost:3000 | user `admin`, password `Snehal@123` |

The Grafana password is also saved in the `.env` file as `GRAFANA_ADMIN_PASSWORD`. Grafana keeps the password it was first started with: if you ran an older version on this machine, remove its data volume with `docker compose down -v` before installing again.

---

