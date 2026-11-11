# ── KRÉTA Adatlekérő — Python + Playwright Chromium ──
# Építés: pip függőségek → Chromium + rendszerfüggőségek → app kód → nem-root user
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# tzdata a TZ=Europe/Budapest-hez, sqlite3 CLI (entrypoint DB-guard + mentések),
# util-linux a setpriv-hez (entrypoint jogosultságváltás), fonts-liberation a
# PDF magyar ő/ű betűkészletéhez (a ReportLab beépített Type1 betűi nem tudják).
# libatomic1: a Playwright bundle-elt Node-ja (driver/node) ezt keresi; a friss
# python:3.12-slim alapimage-bol hianyzik, es a "playwright install" a sajat
# fuggosegeinek telepitese ELOTT elszall (exit 127, libatomic.so.1).
RUN apt-get update && apt-get install -y --no-install-recommends tzdata sqlite3 util-linux fonts-liberation libatomic1 \
    && rm -rf /var/lib/apt/lists/*

# Függőségek külön rétegben (cache: kódváltozáskor nem épül újra)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Chromium + hiányzó rendszerkönyvtárak (nagy réteg, ritkán változik)
RUN playwright install --with-deps chromium

# Alkalmazáskód — config.json SZÁNDÉKOSAN NEM kerül a képbe (a data kötetből
# mountolódik a /app/data/config.json), így a jelszavak nincsenek a képben.
# Minden gyökér *.py bekerül (app.py + kreta_*.py modulok): korábban itt csak az
# app.py és a kreta_playwright.py szerepelt, ezért a v1.6.0 API-moduljai
# hiányoztak a képből (ModuleNotFoundError: kreta_api).
COPY *.py ./
COPY templates/ ./templates/
COPY static/ ./static/
COPY entrypoint.sh ./

# Építéskori füstteszt: ha egy modul vagy csomag hiányzik, már a build elszáll
# (a 2026-11-02-i hiba így azonnal kiderült volna, nem éles szinkron közben).
# Az `import app` a teljes modulgráfot behúzza (a blueprint-eket és a kiemelt
# rétegeket is), temp data-dirrel, hogy a képbe ne kerüljön adatbázis.
RUN python -c "import requests, playwright, openpyxl; import kreta_api, kreta_api_sync, kreta_sync, kreta_shadow" \
    && KRETA_DATA_DIR=/tmp/kreta-buildcheck python -c "import app" \
    && rm -rf /tmp/kreta-buildcheck


# Nem-root futás (a szerveren a reitam user uid/gid = 1000, lásd a compose args-t).
# ENV-be égetjük az ARG értékét, hogy az entrypoint futásidőben is lássa
# (a RabbitApp képénél ez a .env-ből jött — itt ne függjünk tőle).
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
