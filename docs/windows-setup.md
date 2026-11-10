# Windows Setup (Phase 0)

Status: DRAFT. Steps follow `00-architecture.md` §3 and §10 (Phase 0). Verify each step on the target machine; menu names can differ between Docker Desktop versions.

Target: Windows 11, Docker Desktop (WSL2 backend), i5-1135G7, 15.7 GB RAM, no NVIDIA GPU.

## 1. Project location

The project must live outside OneDrive: `D:\lanka-finance-ai`.

```powershell
git -C D:\lanka-finance-ai status   # confirm the repo is intact after the move
```

Check that no OneDrive "Known Folder Backup" covers `D:`. Application data lives in Docker named volumes, not in this folder.

## 2. Check prerequisites

```powershell
wsl --status
wsl -l -v          # expect a distro with VERSION 2
docker version
docker compose version
Get-PSDrive C, D   # free space
```

C: has about 32 GB free, which is too little for images and model weights. Everything Docker stores must go to D:.

## 3. Relocate Docker's WSL disk image to D:

Preferred (Docker Desktop UI):

1. Docker Desktop > Settings > Resources > Advanced.
2. Set **Disk image location** to `D:\DockerDesktopWSL`.
3. Apply & restart. Docker moves the existing image.

Confirm afterwards that the large `.vhdx` is on D: and C: is no longer growing:

```powershell
Get-ChildItem D:\DockerDesktopWSL -Recurse -Filter *.vhdx | Select FullName, @{n='GB';e={[math]::Round($_.Length/1GB,1)}}
```

If your Docker Desktop version has no such setting, use `wsl --export` / `wsl --import` for the Docker data distro. Stop Docker Desktop and run `wsl --shutdown` first. Back up before attempting this.

## 4. Cap WSL2 memory

Create or edit `%UserProfile%\.wslconfig`:

```ini
[wsl2]
memory=10GB
processors=4
swap=4GB
```

Apply:

```powershell
wsl --shutdown
```

Then restart Docker Desktop. The 10 GB cap matches the budget in `00-architecture.md` §3 (ollama 5 GB, postgres 1 GB, backend 1 GB, worker 2 GB, frontend 512 MB).

## 5. Backup location

Choose a path outside OneDrive, for example `D:\lanka-backups`. The app warns at startup if the configured backup path is under OneDrive. Backups are encrypted archives; keep the passphrase somewhere other than the backup disk.

## 6. Sample PDFs

Put real statements under `tests/fixtures/private/` (gitignored, never committed). Do not put them in cloud-synced folders. Only synthetic or authorized anonymized fixtures may be committed.

## 7. Network exposure

The frontend binds to `127.0.0.1` by default (`FRONTEND_BIND`). Binding to a LAN address requires an explicit flag; if you do, restrict it with Windows Firewall to trusted hosts.

## 8. Start the application

```powershell
Copy-Item .env.example .env      # then set POSTGRES_PASSWORD; never commit .env
docker compose up -d --build
docker compose --profile setup run --rm ollama-pull    # one-time model download
```

Open http://127.0.0.1:3000 and create your account. Optional settings in `.env`:
`OLLAMA_MODEL`, `LLM_TIMEOUT_S`, `LLM_CONFIDENCE_THRESHOLD` (see `04-categorization.md`).
A 3B model needs about 3 GB of the 5 GB given to the `ollama` container. To start from an empty
database, remove the `pgdata` volume (`docker compose down`, then
`docker volume rm lanka-finance-ai_pgdata`); the downloaded models are kept.

## 9. Verification checklist

- [ ] Project at `D:\lanka-finance-ai`, outside OneDrive
- [ ] `wsl -l -v` shows a WSL 2 distro
- [ ] Docker disk image is on D:
- [ ] `.wslconfig` applied (`wsl --shutdown`, then `free -h` inside WSL shows about 10 GB)
- [ ] Backup path chosen, outside OneDrive
- [ ] `tests/fixtures/private/` exists and is gitignored
- [ ] First-bank choice recorded (open item in `00-architecture.md` §10)


## Optional compose overrides

* **GPU** (`docker-compose.gpu.yml`): lets Ollama use an NVIDIA GPU.
  `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d`. Check with
  `docker compose exec ollama nvidia-smi`; the warm-up time on the System page should drop sharply.
* **Offline** (`docker-compose.offline.yml`): gives the backend, worker, database and Ollama no route to
  the internet (the app never needs one). Download the models first, then
  `docker compose -f docker-compose.yml -f docker-compose.offline.yml up -d`. The frontend stays on the
  outer network only because Docker cannot publish a port from an internal-only network.
* The two can be combined by listing both `-f` files after the base one.

All services have health checks (`docker compose ps` shows them). The worker proves it is alive by
touching a heartbeat file every 10 seconds (a long model call does not make it look dead).

### Prove the offline override works

```
.\scripts\check-offline.ps1
```

Starts a separate copy of the stack twice (normal, then with `docker-compose.offline.yml`) and from inside the
backend container tries to reach an outside address by number and by name. It passes only if the normal copy
CAN reach out (so the test is meaningful), the offline copy cannot, and the offline copy still reaches its own
database. Your running app is not touched. The backend tests also fail if code that opens network connections
appears outside the modules that talk to the local model (`backend/tests/test_guards.py`).
