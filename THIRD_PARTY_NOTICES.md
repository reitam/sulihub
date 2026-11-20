# Harmadik féltől származó kódok és licencek

Ez a projekt az alábbi nyílt forráskódú projektekből származó ismereteket,
illetve újraírt kódrészleteket tartalmaz. A MIT licenc megköveteli a
szerzői jogi értesítés és az engedély szövegének megőrzését a másolatokban
(így a forráskiadásban és a Docker image-ben is).

## hun0r/e-kreta-hun0r-2.0

- **Forrás:** https://github.com/hun0r/e-kreta-hun0r-2.0
- **Licenc:** MIT
- **Copyright:** Copyright (c) 2025 hun0r
- **Felhasználás:** a böngésző nélküli KRÉTA login/OAuth-flow
  (`src/kreta/idp/login.py`) alapján, **újraírva** a `kreta_api.py`-ban
  (IDP-végpontok, `__RequestVerificationToken`, `InstituteLogin`, callback- és
  tokenkérés). A kód nem másolat, hanem a flow újraimplementálása.

## blazsmaster/kreta.js

- **Forrás:** https://github.com/blazsmaster/kreta.js
- **Licenc:** MIT
- **Copyright:** Copyright (c) 2023 blazsmaster
- **Felhasználás:** a mobil v3 API hívásaihoz használt `apiKey` fejléc
  ismerete ihlette a `kreta_api.py` megfelelő részét.

## majorcs/kreta-homeassistant

- **Forrás:** https://github.com/majorcs/kreta-homeassistant
- **Licenc:** MIT
- **Copyright:** Copyright (c) 2026 Csaba Major
- **Felhasználás:** csak **ötlet/minta** (architektúra, adatkörök); a
  projektbe **nem került át kód**.

## B3ni15/kreta-api-new

- **Forrás:** https://github.com/B3ni15/kreta-api-new
- **Licenc:** nincs megadva (minden jog fenntartva)
- **Felhasználás:** **nem** használtuk fel, és a jövőben sem használható fel
  a projektben a licenc hiánya miatt.

## Frontend (vendorolt) könyvtárak

A `static/vendor/` alatt ezek a könyvtárak vannak a repóban (internet nélküli
indításhoz, Kaneo #12):

| Könyvtár | Verzió | Licenc | Copyright |
|---|---|---|---|
| Bootstrap | 5.3.0 | MIT | Copyright (c) 2011–2023 The Bootstrap Authors |
| DataTables | 1.13.6 | MIT | Copyright (c) 2008–2023 SpryMedia Ltd. |
| DataTables Responsive | 2.5.0 | MIT | Copyright (c) 2008–2023 SpryMedia Ltd. |
| jQuery | 3.7.0 | MIT | Copyright OpenJS Foundation és közreműködők |
| FullCalendar | 6.1.8 | MIT | Copyright (c) 2010–2023 Adam Shaw |
| Font Awesome Free | 6.4.0 | kód: MIT; ikonok: CC BY 4.0; betűtípusok: SIL OFL 1.1 | Copyright (c) Fonticons, Inc. |

## Python függőségek (pip)

- **Flask**, Werkzeug, Jinja2, itsdangerous, click, MarkupSafe — BSD-3-Clause
- **requests** — Apache-2.0; urllib3 — MIT; certifi — MPL-2.0;
  charset-normalizer — MIT; idna — BSD-3-Clause
- **reportlab**, **pypdf** — BSD-3-Clause
- **openpyxl**, et-xmlfile — MIT
- **waitress** — ZPL-2.1
- **tzdata** — Apache-2.0

A csomagok teljes licencszövege a telepített csomagokban, illetve a projekt
oldalán érhető el. A MIT licenc szövege alább található.

## MIT License szövege

A fenti hun0r, blazsmaster és majorcs projektek az alábbi MIT licenc alatt
érhetők el:

```
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## A projekt saját licence

A SuliHub saját kódja a [`LICENSE`](LICENSE) fájl szerint **MIT licenc** alatt
áll (Copyright (c) 2026 Reiner Tamás). A harmadik féltől származó részekre a
fenti licencek érvényesek.
