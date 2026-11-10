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

## Use the app from another device (phone, laptop) on your home network

By default the app answers only on this computer (`127.0.0.1`). To open it from another device on the same
Wi-Fi or network, use the HTTPS override. Plain HTTP is not offered: your password and session cookie would
travel unprotected across the network.

```
.\scripts\lan.ps1 -OpenFirewall        # PowerShell as administrator the first time
```

What it does: starts a small Caddy proxy (`docker-compose.lan.yml`, `lan\Caddyfile`) on port 8443 that makes
its own certificate authority and signs a certificate for this computer's address (nothing is requested from
the internet); makes the session cookie HTTPS-only (`COOKIE_SECURE`); opens Windows Firewall for port 8443 from
your **local network only, on Private networks only**; and saves the authority's certificate as
`lan\lanka-local-ca.crt`. The app itself stays bound to `127.0.0.1`: only the proxy is reachable from outside.
On this computer you still use `http://127.0.0.1:3000` (browsers accept the secure cookie on localhost).

Then, on the other device, open `https://<this computer's address>:8443` (the script prints it). The first time,
install `lanka-local-ca.crt` so the browser trusts it (otherwise it warns):

| Device | Install the certificate |
|---|---|
| Windows | Double-click the file, Install Certificate, Local Machine, "Trusted Root Certification Authorities" |
| iPhone / iPad | Send the file to it (AirDrop or email), open it, Settings > Profile Downloaded > Install; then Settings > General > About > Certificate Trust Settings, switch the certificate on |
| Android | Settings > Security > Encryption and credentials > Install a certificate > CA certificate |
| Mac | Open the file (Keychain Access), set it to "Always Trust" |

The certificate is only a public certificate; copying it is safe. Do not copy anything else from the
`caddy_data` volume: it holds the authority's private key.

Things to know:

* **Give this computer a fixed address.** In your router, reserve an address for it (a DHCP reservation). If the
  address changes, run `lan.ps1` again; the certificate is made for the address it was started with. The second
  name (`<computer>.local`) works on devices that resolve such names (most Apple, Windows 10/11 and many
  Android devices) and survives an address change.
* **A timeout from the other device means the Windows Firewall is blocking it.** Two things must both be true:
  the Wi-Fi network is marked **Private** (a home network is often marked Public, and Windows blocks incoming
  connections on Public), and a rule allows port 8443. Docker Desktop can also carry its own *block* rule for
  Public networks, and a block rule beats an allow rule, so marking the network Private is the part that
  matters. `lan.ps1` tells you which case you are in. Both fixes need an administrator:
  `Set-NetConnectionProfile -InterfaceAlias Wi-Fi -NetworkCategory Private`, then the `New-NetFirewallRule` line below.
  Other causes to rule out: the device is on a guest network or has "AP/client isolation" on the router, or
  it is on mobile data instead of the same Wi-Fi.
* **No administrator rights?** Leave `-OpenFirewall` off. Docker Desktop normally has its own allow rule for
  Private networks, so another device may connect anyway. If it cannot, the rule needs someone with admin
  approval: `New-NetFirewallRule -DisplayName "Lanka Finance AI (LAN HTTPS)" -Direction Inbound -Protocol TCP -LocalPort 8443 -Profile Private -RemoteAddress LocalSubnet -Action Allow`.
* **Your computer must be on and Docker running** for the other device to reach it.
* **Anyone on your network can reach the sign-in page.** Use a strong password (sign-ins lock out after repeated
  failures). Use this only on a network you control; the firewall rule is limited to the Private profile.
  Windows marks a network Private or Public in Settings > Network & internet > (your network) > Properties.
* **Turn it off** with `.\scripts\lan.ps1 -Down` (stops the proxy, removes the firewall rule, restores the cookie
  setting). Your data is not touched either way.
* To use another port, `-Port 9443`; to bind the proxy to one adapter only, set `LAN_BIND` to that address.

