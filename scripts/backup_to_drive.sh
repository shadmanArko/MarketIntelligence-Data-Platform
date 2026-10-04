#!/usr/bin/env bash
# Verified backup to an external drive:
#   export snapshot -> add source-code bundle -> SHA-256 of every file -> copy -> re-read and verify on the drive
#   -> append to BACKUP_LOG.md.  Nothing on the drive is overwritten: each backup is a new dated folder.
# Usage: bash scripts/backup_to_drive.sh ["/Volumes/ARKO HDD/Work/Dhaka Kacchi - Market Intelligence Data"]
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="${1:-/Volumes/ARKO HDD/Work/Dhaka Kacchi - Market Intelligence Data}"
[ -d "$(dirname "$DEST")" ] || { echo "Drive not mounted: $DEST"; exit 1; }
DAY=$(date +%Y-%m-%d)
[ -e "$DEST/snapshots/$DAY" ] && { echo "$DEST/snapshots/$DAY already exists; not overwriting"; exit 1; }
uv run mip export snapshot --to data/exports
SNAP="data/exports/mip-snapshot-$(date -u +%Y%m%d)"
git bundle create "$SNAP/source_code.bundle" --all
(cd "$SNAP" && find . -type f ! -name SHA256SUMS.txt ! -name .DS_Store | sed 's|^\./||' | sort | tr '\n' '\0' \
   | xargs -0 shasum -a 256 > SHA256SUMS.txt)
mkdir -p "$DEST/snapshots"
COPYFILE_DISABLE=1 rsync -rt --exclude .DS_Store --exclude "._*" "$SNAP/" "$DEST/snapshots/$DAY/"
sync; find "$DEST" -name "._*" -type f -delete   # macOS metadata files on exFAT
(cd "$DEST/snapshots/$DAY" && shasum -a 256 -c --quiet SHA256SUMS.txt)
SIZE=$(du -sh "$DEST/snapshots/$DAY" | cut -f1); FILES=$(wc -l < "$SNAP/SHA256SUMS.txt" | tr -d ' ')
COMMIT=$(git rev-parse --short HEAD)
[ -f "$DEST/BACKUP_LOG.md" ] || printf '# Backup log\n\n| Snapshot | Created | Size | Files | Git commit | Verified on drive |\n|---|---|---|---|---|---|\n' > "$DEST/BACKUP_LOG.md"
echo "| $DAY | $(date '+%Y-%m-%d %H:%M %Z') | $SIZE | $FILES | $COMMIT | OK (SHA-256, all files) |" >> "$DEST/BACKUP_LOG.md"
echo "Backup verified: $DEST/snapshots/$DAY ($SIZE, $FILES files). Eject the drive before unplugging."
