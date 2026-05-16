#!/bin/bash
# Sauvegarde complète hebdomadaire FACE.ai → USB1
# Conserve les 4 dernières sauvegardes complètes (≈ 1 mois)

set -euo pipefail

PROJECT_DIR="/Users/patrickostertag/Documents/DataForIA/FACE.ai"
BACKUP_DIR="/Volumes/USB1/FACE.ai-Backup"
KEEP=4
LOG="$BACKUP_DIR/backup-full.log"

# Vérifier que USB1 est monté
if [[ ! -d "$BACKUP_DIR" ]]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: $BACKUP_DIR non accessible (USB1 non monté ?)" >> "$LOG"
    exit 1
fi

STAMP=$(date +%Y%m%d-%H%M%S)
DEST="$BACKUP_DIR/full-backup-${STAMP}.tar.gz"

echo "$(date '+%Y-%m-%d %H:%M:%S') Démarrage sauvegarde complète → $DEST" >> "$LOG"

tar czf "$DEST" \
    -C "$PROJECT_DIR" \
    data/face_ai.db \
    static/

SIZE=$(du -sh "$DEST" | cut -f1)
echo "$(date '+%Y-%m-%d %H:%M:%S') OK: $DEST ($SIZE)" >> "$LOG"

# Rotation : conserver seulement les $KEEP dernières sauvegardes complètes
ls -t "$BACKUP_DIR"/full-backup-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
    rm -f "$old"
    echo "$(date '+%Y-%m-%d %H:%M:%S') Rotation: supprimé $old" >> "$LOG"
done
