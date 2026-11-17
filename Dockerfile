# ── KRÉTA Adatlekérő — alap image (API-s szinkron, böngésző nélkül) ──
# A böngészős (Playwright) fallback a v2.5.0-ban kikerült (Kaneo #64): minden
# adatkör a Kréta mobil API-ból frissül. A Playwright csak a fejlesztői
# UI-tesztek függősége (requirements-playwright.txt), a képbe nem kerül.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# tzdata a TZ=Europe/Budapest-hez, sqlite3 CLI (entrypoint DB-guard + mentések),
# util-linux a setpriv-hez (entrypoint jogosultságváltás), fonts-liberation a
# PDF magyar ő/ű betűkészletéhez (a ReportLab beépített Type1 betűi nem tudják).
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata sqlite3 util-linux fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Futtatási függőségek (Playwright nélkül)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Alkalmazáskód — config.json SZÁNDÉKOSAN NEM kerül a képbe (a data kötetből
# mountolódik a /app/data/config.json), így a jelszavak nincsenek a képben.
# Minden gyökér *.py bekerül (app.py + kreta_*.py modulok).
COPY *.py ./
COPY templates/ ./templates/
COPY static/ ./static/
COPY entrypoint.sh ./

# Építéskori füstteszt: ha egy modul vagy csomag hiányzik, már a build elszáll
# (a 2026-11-02-i éles hiba így azonnal kiderült volna, nem éles szinkron közben).
# Az `import app` a teljes modulgráfot behúzza, temp data-dirrel.
RUN KRETA_DATA_DIR=/tmp/kreta-buildcheck python -c "import app" \
    && rm -rf /tmp/kreta-buildcheck

# Nem-root futás (a szerveren a reitam user uid/gid = 1000, lásd a compose args-t).
# ENV-be égetjük az ARG értékét, hogy az entrypoint futásidőben is lássa.
ARG APP_UID=1000
ARG APP_GID=1000
ENV APP_UID=$APP_UID APP_GID=$APP_GID
RUN if [ "$APP_UID" != "0" ]; then \
        groupadd -r -g $APP_GID appuser && \
        useradd -r -u $APP_UID -g appuser -d /app -s /sbin/nologin appuser; \
    fi
RUN mkdir -p /app/data /app/backup /app/data/csatolmanyok \
    && if [ "$APP_UID" != "0" ]; then chown -R appuser:appuser /app; fi \
    && chmod +x /app/entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "app.py"]
