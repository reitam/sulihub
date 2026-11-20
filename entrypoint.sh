#!/bin/sh
set -e

# ══ KRÉTA DB/config guard — a RabbitApp entrypoint.sh mintájára ══════════
# A data/ kötet (DB + config.json + böngészőprofil + csatolmányok) egy másik
# lemezen (HDD) él. Ha az a lemez pillanatnyi leszakadása közben indul újra a
# konténer, a bind mount ÜRES könyvtárat lát. Ilyenkor NEM szabad üres
# adatbázist létrehozni, hanem várni kell a visszacsatolásra, végső esetben
# visszaállítani a mentésből.

DB_FILE=${GUARD_DB_FILE:-/app/data/kreta_adatok.db}
CONFIG_FILE=${GUARD_CONFIG_FILE:-/app/data/config.json}
STATE_FILE=${GUARD_STATE_FILE:-/app/backup/.kreta_db_state}
BACKUP_DIR=${GUARD_BACKUP_DIR:-/app/backup}
MAX_WAIT_SECS=${GUARD_MAX_WAIT_SECS:-300}
FIRST_WAIT_SECS=${GUARD_FIRST_WAIT_SECS:-30}

log() { echo "[guard] $(date '+%F %T') $*"; }

# DB érvényesség: megnyitható, integrity OK, van esemenyek tábla, és a mérete
# nem lehet drasztikusan kisebb az állapotfájlban rögzítettnél (a DB csak nő —
# egy „frissen létrejött üres” DB is sokkal kisebb lenne).
db_valid() {
    [ -f "$DB_FILE" ] || return 1
    integrity=$(sqlite3 "file:$DB_FILE?mode=ro" "PRAGMA integrity_check;" 2>/dev/null || echo "hiba")
    [ "$integrity" = "ok" ] || return 1
    tables=$(sqlite3 "file:$DB_FILE?mode=ro" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='esemenyek';" 2>/dev/null || echo "0")
    [ "$tables" -ge 1 ] 2>/dev/null || return 1
    if [ -f "$STATE_FILE" ]; then
        prev=$(head -c 32 "$STATE_FILE" | cut -d' ' -f1)
        case "$prev" in
            ''|*[!0-9]*) prev=0 ;;
        esac
        size=$(stat -c %s "$DB_FILE" 2>/dev/null || echo 0)
        if [ "$prev" -gt 0 ] && [ "$size" -lt $((prev / 2)) ]; then
            return 1
        fi
    fi
    return 0
}

# Állapotfájl frissítése: DB méret + időbélyeg (best effort).
write_state() {
    size=$(stat -c %s "$DB_FILE" 2>/dev/null || echo 0)
    echo "$size $(date +%s)" > "$STATE_FILE" 2>/dev/null || true
}

# config.json megléte: enélkül a szinkronizáció úgysem tudna futni, és a hiánya
# (egy korábbi állapotfájl mellett) a leszakadt HDD legjobb jele.
config_ok() { [ -f "$CONFIG_FILE" ]; }

if db_valid && config_ok; then
    log "DB + config rendben — indítás."
    write_state
elif [ -f "$STATE_FILE" ]; then
    log "DB/config hiányzik vagy sérült, de korábban volt működő adat."
    log "Várok a tároló visszacsatolására (max ${MAX_WAIT_SECS}s)..."
    waited=0
    while ! db_valid || ! config_ok; do
        if [ "$waited" -ge "$MAX_WAIT_SECS" ]; then
            break
        fi
        sleep 5
        waited=$((waited + 5))
    done
    if db_valid && config_ok; then
        log "Az adatok visszatértek — indítás."
        write_state
    else
        log "A várakozás lejárt — visszaállítás a legutóbbi DB-mentésből..."
        latest=$(ls -1t "$BACKUP_DIR"/kreta_adatok_*.db 2>/dev/null | head -n 1)
        if [ -n "$latest" ]; then
            log "Visszaállítás: $latest"
            cp "$latest" "$DB_FILE"
            write_state
            log "DB visszaállítva — indítás."
        else
            log "NINCS érvényes DB-mentés. Üres DB-t NEM hozok létre — kilépek." >&2
            exit 1
        fi
    fi
else
    log "Első indítás (nincs állapotfájl) — rövid várakozás az adatkötetre..."
    waited=0
    while [ "$waited" -lt "$FIRST_WAIT_SECS" ]; do
        if db_valid && config_ok; then
            log "Az adatok megjelentek — indítás."
            write_state
            break
        fi
        sleep 5
        waited=$((waited + 5))
    done
    if ! config_ok; then
        log "NINCS config.json a data kötetben (/app/data/config.json)." >&2
        log "Egyszeri beállítás: másold a config.json-t a data kötetre," >&2
        log "vagy futtasd a karbantartói deploy script -MigrateLocalData kapcsolóját." >&2
        log "Kilépek." >&2
        exit 1
    fi
    if ! db_valid; then
        log "Nincs DB — az alkalmazás létrehozza (első telepítés)."
    fi
fi

# ══ Env-szivárgás ellen (a RabbitApp 2026-10-27-i „üres db” tanulsága) ═══
# A .env-beli DATA_DIR/BACKUP_DIR a HOST oldali kötet-útvonal (a compose
# interpolálja). Ha ezek kiszivárognának az app környezetébe, az app egy
# NEM LÉTEZŐ konténerbeli útvonalat kapna és ott ÜRES adatbázist hozna létre.
# Ezért a konténerben SOHA ne lássa az app ezeket a változókat.
unset DATA_DIR BACKUP_DIR

# Kötet-jogosultságok (NTFS mounton halkan hibázhat, ezért || true)
if [ "$APP_UID" != "0" ]; then
    chown -R $APP_UID:$APP_GID /app/data 2>/dev/null || true
    chown -R $APP_UID:$APP_GID /app/backup 2>/dev/null || true
    chmod 700 /app/data 2>/dev/null || true
    chmod 600 /app/data/kreta_adatok.db 2>/dev/null || true
    exec setpriv --reuid=$APP_UID --regid=$APP_GID --clear-groups "$@"
else
    exec "$@"
fi
