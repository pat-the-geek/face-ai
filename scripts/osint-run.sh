#!/bin/bash
# Wrapper launchd pour les ingestions OSINT FACE.ai (v030).
# Lance le script Python passé en argument DANS le conteneur api.
# Appelé par les agents launchd ~/Library/LaunchAgents/ai.face.osint.*.plist
# (remplace l'ancien crontab — launchd relance au réveil si la machine dormait
# et n'a pas le souci de Full Disk Access de /usr/sbin/cron).
#
# Usage : osint-run.sh scripts/ingest_opensanctions.py [args...]
set -euo pipefail

DOCKER=/usr/local/bin/docker
CONTAINER=faceai-api-1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] osint-run: $*"

# Ne rien faire si le conteneur api n'est pas up (Docker Desktop éteint, etc.)
if ! "$DOCKER" inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
  echo "  conteneur $CONTAINER non démarré — abandon (Docker Desktop lancé ?)."
  exit 0
fi

exec "$DOCKER" exec "$CONTAINER" python "$@"
