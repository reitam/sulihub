# Biztonsági irányelvek

## Támogatott verziók

A legutóbbi kiadást (és az aktuális `main`-t) támogatjuk. Kérjük, a hibákat a
legfrissebb verzióval ellenőrizd.

## Sebezhetőség bejelentése

**Kérjük, ne nyiss nyilvános issue-t sebezhetőségről.** Használd a GitHub
**Security → Report a vulnerability** (privát sebezhetőség-bejelentés) funkcióját
a repóban. Ha ez nem elérhető, jelezd a karbantartónak egy rövid, személyes
adatot nem tartalmazó üzenetben.

A bejelentésben lehetőleg add meg:

- az érintett verziót / commitot,
- a reprodukálás lépéseit,
- a várható és a tényleges viselkedést,
- a lehetséges hatást (pl. adatszivárgás, jogosultság-emelés).

## Adatvédelem

Ez egy **nem hivatalos**, saját üzemeltetésű kliens. Ne küldj be valódi
KRÉTA-adatot, gyermeknevet, iskolaazonosítót, jelszót, tokent vagy más személyes
adatot. A hibajelentésekben és képernyőképeken használj kitalált adatokat.

## Függőségek

A futásidejű Python-csomagokat a `requirements.txt`, a vendorolt
frontend-könyvtárakat a `static/vendor/` tartalmazza. A CI `pip-audit` jobja és
a heti Dependabot-frissítések figyelik az ismert sebezhetőségeket.
