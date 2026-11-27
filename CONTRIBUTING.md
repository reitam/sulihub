# Hozzájárulás a SuliHubhoz

Köszönjük, hogy segítenél! Ez a projekt egy nem hivatalos, saját üzemeltetésű
KRÉTA-kliens. Kérjük, tartsd be az alábbiakat.

## Hibabejelentés és ötletek

- Nyiss GitHub issue-t a megfelelő sablonnal.
- **Ne tegyél közzé személyes adatot** (gyermeknév, iskola, KRÉTA-azonosító,
  jelszó, token, valódi képernyőkép). Használj kitalált adatokat.
- Biztonsági problémát **ne** nyilvános issue-ban jelents; lásd
  [`SECURITY.md`](SECURITY.md).

## Fejlesztés

1. Forkold a repót, és készíts egy branchet:
   - `feat/<rövid-név>` – új funkció,
   - `fix/<rövid-név>` – hiba javítása,
   - `docs/<rövid-név>` – dokumentáció.
2. Fejlessz a meglévő stílusban; a Python 3.12 az alap.
3. Futtasd a teszteket:
   ```bash
   pip install -r requirements.txt
   python tests/run_all.py --fast
   # UI-változásnál:
   pip install -r requirements-playwright.txt
   python -m playwright install chromium
   python tests/run_all.py --browser
   ```
4. Nyiss Pull Requestet a `main`-re. A PR-nak zöld CI-t kell hoznia.

## Tilos a repóban

- `config.json`, `.env`, `*.db`, `api_tokens.json`, `sync.log`, csatolmányok,
  valódi KRÉTA-adat vagy személyes adat.
- Belső szervernevek, IP-címek, Samba/SSH útvonalak vagy üzemeltetési hivatkozások.
- Valódi nevek/iskolák a tesztfixture-ökben vagy a dokumentációban.

## Kiadás

- A verziózás SemVer (`vX.Y.Z`).
- Minden felhasználói változáshoz készüljön release note a
  `docs/releasenotes/vX.Y.Z.md` alá.
- A kiadás tag + GitHub Release; a tagot a karbantartó állítja ki.
- A `main` ágra force push tilos.

## Magatartás

Légy tiszteletteljes és konstruktív. A zaklatást, a személyes adatok közzétételét
és a rosszindulatú viselkedést nem toleráljuk.
