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

## 8. Verification checklist

- [ ] Project at `D:\lanka-finance-ai`, outside OneDrive
- [ ] `wsl -l -v` shows a WSL 2 distro
- [ ] Docker disk image is on D:
- [ ] `.wslconfig` applied (`wsl --shutdown`, then `free -h` inside WSL shows about 10 GB)
- [ ] Backup path chosen, outside OneDrive
- [ ] `tests/fixtures/private/` exists and is gitignored
- [ ] First-bank choice recorded (open item in `00-architecture.md` §10)
