# ── KRÉTA Adatlekérő — alap image (API-s szinkron, böngésző nélkül) ──
# A Chromiumos fallback külön targetben van (`--target playwright`), így az
# alap image karcsú marad. A deploy a compose `KRETA_BUILD_TARGET` változójával
# választ (alap: runtime).
#
# Építés:
#   docker build -t kreta-app:runtime .                     # alap (API)
#   docker build --target playwright -t kreta-app:playwright .  # fallback
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# tzdata a TZ=Europe/Budapest-hez, sqlite3 CLI (entrypoint DB-guard + mentések),
# util-linux a setpriv-hez (entrypoint jogosultságváltás), fonts-liberation a
# PDF magyar ő/ű betűkészletéhez (a ReportLab beépített Type1 betűi nem tudják).
# A libatomic1 csak a Playwright stage-ben kell (a bundle-elt Node miatt).
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata sqlite3 util-linux fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Alap függőségek (Playwright nélkül — az a külön targetben jön)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Alkalmazáskód — config.json SZÁNDÉKOSAN NEM kerül a képbe (a data kötetből
# mountolódik a /app/data/config.json), így a jelszavak nincsenek a képben.
# Minden gyökér *.py bekerül (app.py + kreta_*.py modulok).
COPY *.py ./
COPY templates/ ./templates/
COPY static/ ./static/
COPY entrypoint.sh ./

# Építéskori füstteszt: ha egy modul vagy csomag hiányzik, már a build elszáll.
# A Playwright szándékosan NINCS itt: az alap image böngésző nélkül is indul.
RUN python -c "import requests, openpyxl; import kreta_api, kreta_api_sync, kreta_sync, kreta_shadow" \
    && KRETA_DATA_DIR=/tmp/kreta-buildcheck python -c "import app" \
    && rm -rf /tmp/kreta-buildcheck

# Nem-root futás (a szerveren a reitam user uid/gid = 1000, lásd a compose args-t).
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


# ── Playwrightos fallback image (csak a böngészős fallbackhez) ──
# A deploy rollbackje: KRETA_BUILD_TARGET=playwright + KRETA_IMAGE_TAG=playwright
# a szerver .env-jében, majd `docker compose up -d --build`.
FROM runtime AS playwright

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# libatomic1: a Playwright bundle-elt Node-ja (driver/node) ezt keresi; a friss
# python:3.12-slim alapimage-bol hianyzik, es a "playwright install" a sajat
# fuggosegeinek telepitese ELOTT elszall (exit 127, libatomic.so.1).
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-playwright.txt ./
RUN pip install --no-cache-dir -r requirements-playwright.txt

# Chromium + hiányzó rendszerkönyvtárak (nagy réteg, ritkán változik)
RUN playwright install --with-deps chromium

# Építéskori füstteszt: a böngészős csomag valóban importálható
RUN python -c "import playwright"
