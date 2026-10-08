# VPS collector (light daily sources, 24/7)

The VPS runs the **same platform code** for the official-API sources, so they keep collecting while the Mac is off:

| Source | On the VPS | Why there |
|---|---|---|
| YouTube recent-upload searches (+ videos / channels / comments they lead to) | daily 10:15 Berlin (after the quota reset) | the daily quota is lost on days the Mac is off |
| Berlin events (berlin.de) | daily | official JSON |
| Wikipedia pageviews | Saturday 22:30 | official API |
| Reddit (Arctic Shift), last ~3 months | Saturday 22:30 | official API; history already on the Mac |

**Stays on the Mac:**
- Wolt, Lieferando, Google Maps and TikTok. They detect bots, and a datacenter address is blocked much sooner than a
  home line; we never evade bot protection.
- The YouTube statistics refresh of all 181k known videos.
- All transforms.

**Every Sunday the Mac's weekly refresh first runs `mip collector import`.** Runs, payloads (keyed by sha256) and
observations (keyed by uuid) are copied ON CONFLICT DO NOTHING: repeatable, never duplicated, raw stays immutable.

**Resources:** `collector-db` (postgres:18-alpine, 256 MB limit, loopback port 5442). `collector` runs only during a job
(512 MB limit).

## First-time setup on the VPS (deploy user)
1. **Read-only checkout** (GitHub → MarketIntelligence-Data-Platform → Settings → Deploy keys; write access OFF):
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/mip_repo -N "" -C "vps read mip" && cat ~/.ssh/mip_repo.pub
   printf 'Host github-mip\n  HostName github.com\n  User git\n  IdentityFile ~/.ssh/mip_repo\n  IdentitiesOnly yes\n' >> ~/.ssh/config
   git clone git@github-mip:shadmanArko/MarketIntelligence-Data-Platform.git /opt/dhaka-kacchi/mip-collector
   ```
2. **`.env`** (secrets stay on the VPS; MIP_HASH_SALT and the YouTube values must equal the Mac's):
   ```bash
   cd /opt/dhaka-kacchi/mip-collector/deploy/collector
   ( umask 077; { echo "COLLECTOR_DB_PASSWORD=$(openssl rand -hex 24)"; echo "MIP_SYNC_PASSWORD=$(openssl rand -hex 24)"; } > .env )
   nano .env    # add MIP_HASH_SALT=..., YOUTUBE_CLIENT_ID=..., YOUTUBE_CLIENT_SECRET=..., YOUTUBE_REFRESH_TOKEN=..., YOUTUBE_CHANNEL_ID=...
   ```
3. **Build and first run** (the build takes a few minutes the first time):
   ```bash
   docker compose build collector && ./run.sh daily
   ```
4. **Schedule** (host cron, like the harness):
   ```bash
   mkdir -p /opt/dhaka-kacchi/logs
   ( crontab -l; echo "15 10 * * * /opt/dhaka-kacchi/mip-collector/deploy/collector/run.sh daily >> /opt/dhaka-kacchi/logs/mip-collector.log 2>&1"; echo "30 22 * * 6 /opt/dhaka-kacchi/mip-collector/deploy/collector/run.sh weekly >> /opt/dhaka-kacchi/logs/mip-collector.log 2>&1" ) | crontab -
   ```
5. **Let the Mac's tunnel key also reach port 5442.** Add `permitopen="127.0.0.1:5442",` to the `intel` key line:
   ```bash
   sudo sed -i 's/permitopen="127.0.0.1:5432",/permitopen="127.0.0.1:5432",permitopen="127.0.0.1:5442",/' /home/intel/.ssh/authorized_keys
   ```
6. **On the Mac,** put into the data platform's `.env` (the password is `MIP_SYNC_PASSWORD` from step 2):
   ```
   MIP_COLLECTOR_DSN=postgresql://mip_sync:<MIP_SYNC_PASSWORD>@127.0.0.1:5436/collector
   MIP_COLLECTOR_SSH=intel@100.92.213.30
   MIP_COLLECTOR_SSH_KEY=~/.ssh/dk_intel_tunnel
   ```
   Then run `uv run mip collector import`.
   - From now on the weekly refresh imports first and skips those sources.
   - The daily YouTube job on the Mac does nothing (the VPS does it).

## Everyday
| Task | Command (in `deploy/collector`) |
|---|---|
| Log | `tail -50 /opt/dhaka-kacchi/logs/mip-collector.log` |
| Queue / raw volumes | `docker compose run --rm --no-deps collector status` |
| Run now | `./run.sh daily` or `./run.sh weekly` |
| Update code | `git -C ../.. pull --ff-only && docker compose build collector` |
| On the Mac: imports | `uv run mip collector status` |
