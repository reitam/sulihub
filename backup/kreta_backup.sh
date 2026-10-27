#!/bin/sh
# ══ KRÉTA Adatlekérő — napi validált mentés (host cron) ════════════════
#
# A RabbitApp_Svelte rabbittracker_backup.sh mintájára, a kreta-app konténerre.
# A DB pillanatfelvételt a KONTÉNERBEN készíti (sqlite3 .backup — konzisztens,
# nem sima cp), és közvetlenül a mentési kötetre írja (az /app/backup bind mount).
#
# Telepítés (a szerveren, a reitam userrel):
#   1. HDD-s példány (túléli az SSD leszakadását):
#        cp /mnt/work/Kreta/backup/kreta_backup.sh \
#           /mnt/Maxxel_HDD/ReiTam_BackUp/Kreta_backup/kreta_backup.sh
#   2. A cron TÉNYLEGES példánya (a RabbitApp mintájára — a cron innen fut):
#        cp /mnt/work/Kreta/backup/kreta_backup.sh \
#           /home/reitam/docker-backup/kreta_backup.sh
#   3. Crontab (napi, 3:30 — a RabbitApp 2:30-as mentése után):
#        crontab -e
#        30 3 * * * /home/reitam/docker-backup/kreta_backup.sh \
#                   >> /var/log/kreta_backup.log 2>&1
#      (vagy egyszerűbben: a deploy.ps1 -InstallBackup kapcsolója)
#
# Mit csinál:
#   - ellenőrzi, hogy a data (HDD) lemez MOUNTOLVA van-e; ha nem, NEM ment
#   - konzisztens DB snapshot a konténerben (sqlite3 .backup)
#   - validálja a mentést (integrity + esemenyek tábla + minimális méret)
#   - fájlok (böngészőprofil + csatolmányok + config.json) tömörített mentése
#   - alkalmazáskonfiguráció (.env + docker-compose.yml) mentése
#   - forgatás: 7 napi + 4 heti a DB mentésekből, 14 nap a fájlokból, 30 nap a konfigból
#   - hibánál ntfy push riasztás (ha NTFY_TOPIC be van állítva)

set -u

CONTAINER=kreta-app
DATA_MOUNT=/mnt/Maxxel_HDD
DATA_DIR="$DATA_MOUNT/app/Kreta/data"
BACKUP_DIR="$DATA_MOUNT/ReiTam_BackUp/Kreta_backup"
NTFY_TOPIC="${NTFY_TOPIC:-}"
KEEP_DAILY=7
KEEP_WEEKLY=4
MIN_DB_SIZE=20480   # 20 KB — ennél kisebb „valid” DB nem létezhet

log() { echo "$(date '+%F %T') $*"; }

notify() {
    if [ -n "$NTFY_TOPIC" ]; then
        if command -v curl >/dev/null 2>&1; then
            curl -fsS -H "Title: KRÉTA mentés" -d "$1" "$NTFY_TOPIC" >/dev/null 2>&1 || true
        elif command -v wget >/dev/null 2>&1; then
            wget -qO- --post-data "$1" "$NTFY_TOPIC" >/dev/null 2>&1 || true
        fi
    fi
}

fail() {
    log "HIBA: $1"
    notify "KRÉTA mentés HIBA: $1"
    exit 1
}

# ── 1. Mount ellenőrzés ─────────────────────────────────────────────
if ! mountpoint -q "$DATA_MOUNT"; then
    fail "a HDD ($DATA_MOUNT) nincs mountolva — mentés kihagyva"
fi
mkdir -p "$BACKUP_DIR"

# Az időbélyeget EGYSZER számoljuk ki, és ugyanazt kapja a DB snapshot és a
# fájl-/konfigmentés is.
timestamp=$(date '+%Y-%m-%d_%H%M%S')
db_backup="$BACKUP_DIR/kreta_adatok_${timestamp}.db"

# ── 2. DB mentés (konzisztens snapshot) ─────────────────────────────
log "DB mentés: $db_backup"
container_running=false
if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    container_running=true
    # A konténer fut → a .backup API-val konzisztens pillanatfelvétel,
    # közvetlenül a mentési kötetre (/app/backup a konténerben).
    snapshot_out=$(docker exec "$CONTAINER" sqlite3 /app/data/kreta_adatok.db \
        ".backup '/app/backup/kreta_adatok_${timestamp}.db'" 2>&1) \
        || fail "sqlite3 .backup nem futott: $snapshot_out"
else
    # A konténer nem fut → nincs aktív író, a sima cp is biztonságos.
    log "A konténer nem fut — sima cp a data kötetről."
    cp "$DATA_DIR/kreta_adatok.db" "$db_backup" || fail "a DB másolása nem sikerült"
fi

# Validálás: méret (mindig) + integrity és esemenyek tábla (a konténerben,
# ott van sqlite3 CLI — a hoston nem garantált).
size=$(stat -c %s "$db_backup" 2>/dev/null || echo 0)
if [ "$size" -lt "$MIN_DB_SIZE" ]; then
    rm -f "$db_backup"
    fail "a DB mentés gyanúsan kicsi ($size byte) — törölve"
fi
if $container_running; then
    validate_out=$(docker exec "$CONTAINER" sh -c \
        "sqlite3 'file:/app/backup/kreta_adatok_${timestamp}.db?mode=ro' 'PRAGMA integrity_check;' && \
         sqlite3 'file:/app/backup/kreta_adatok_${timestamp}.db?mode=ro' \
         \"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='esemenyek';\"" 2>&1) \
        || validate_out="hiba"
    integrity=$(echo "$validate_out" | head -n 1)
    tables=$(echo "$validate_out" | tail -n 1)
    if [ "$integrity" != "ok" ] || [ "$tables" -lt 1 ] 2>/dev/null; then
        rm -f "$db_backup"
        fail "a DB mentés érvénytelen (integrity=$integrity, esemenyek=$tables) — törölve"
    fi
else
    log "Figyelem: a konténer nem fut — integrity ellenőrzés kihagyva (csak méret)."
fi
chmod 600 "$db_backup" 2>/dev/null \
    || log "Figyelem: a mentés jogosultsága nem állítható (NTFS/CIFS mount?)"
log "DB mentés OK (${size} byte)"

# ── 3. Fájlok mentése (böngészőprofil + csatolmányok + config) ─────
run_dir="$BACKUP_DIR/${timestamp}"
mkdir -p "$run_dir"
files_tar="$run_dir/kreta_files_${timestamp}.tar.gz"
if tar -czf "$files_tar" -C "$DATA_DIR" browser_user_data csatolmanyok config.json 2>/dev/null; then
    if ! gzip -t "$files_tar" 2>/dev/null; then
        rm -f "$files_tar"
        fail "fájl archívum sérült — törölve"
    fi
    chmod 600 "$files_tar" 2>/dev/null || true
    log "Kész: $files_tar"
else
    log "Figyelem: a fájlok mentése nem sikerült"
fi

# ── 3b. Alkalmazáskonfiguráció mentése (.env, docker-compose.yml) ──
CONFIG_DIR=/mnt/work/Kreta
if [ -f "$CONFIG_DIR/.env" ] || [ -f "$CONFIG_DIR/docker-compose.yml" ]; then
    config_tar="$run_dir/kreta_config_${timestamp}.tar.gz"
    if tar -czf "$config_tar" -C "$CONFIG_DIR" .env docker-compose.yml 2>/dev/null; then
        chmod 600 "$config_tar" 2>/dev/null \
            || log "Figyelem: a config fájl jogosultsága nem állítható (NTFS/CIFS mount?)"
        log "Kész: $config_tar"
    else
        log "Figyelem: a konfiguráció mentése nem sikerült"
    fi
fi

# ── 4. Forgatás (csak validált mentések) ────────────────────────────
# 7 napon belüli DB mentés: mind megmarad.
# 7 napnál régebbi: hetente a legújabb marad meg, maximum KEEP_WEEKLY hétre.
log "Forgatás..."
last_week=""
week_count=0
for f in $(ls -1t "$BACKUP_DIR"/kreta_adatok_20*.db 2>/dev/null); do
    day=$(basename "$f" | grep -o '20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]')
    [ -n "$day" ] || continue
    age_days=$(( ($(date +%s) - $(date -d "$day" +%s)) / 86400 ))
    [ "$age_days" -le "$KEEP_DAILY" ] && continue
    week=$(date -d "$day" +%G-%V)
    if [ "$last_week" != "$week" ]; then
        last_week="$week"
        week_count=$((week_count + 1))
        if [ "$week_count" -gt "$KEEP_WEEKLY" ]; then
            rm -f "$f"
            log "Régi heti mentés törölve: $(basename "$f")"
        fi
    else
        rm -f "$f"
        log "Régi heti mentés törölve: $(basename "$f")"
    fi
done
find "$BACKUP_DIR" -name 'kreta_files_*.tar.gz' -mtime +14 -delete 2>/dev/null
find "$BACKUP_DIR" -name 'kreta_config_*.tar.gz' -mtime +30 -delete 2>/dev/null
find "$BACKUP_DIR" -mindepth 1 -type d -empty -delete 2>/dev/null

log "Mentés kész."
notify "KRÉTA mentés OK: kreta_adatok_${timestamp}.db (${size} byte)"
exit 0
