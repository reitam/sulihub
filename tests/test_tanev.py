# -*- coding: utf-8 -*-
"""Tanév-számítás egységtesztjei (Kaneo #40, 0. fázis).

Tiszta függvények: nincs DB, nincs hálózat. A tanév szabálya: szept. 1. – aug. 31.
"""
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import kreta_tanev as t  # noqa: E402

_hibak = []


def ok(c, m):
    print(("  OK   " if c else "  HIBA ") + m)
    if not c:
        _hibak.append(m)


print("\n1) tanev_of: tanévhatárok")
ok(t.tanev_of("2026-08-31") == "2025/2026", "08-31 -> előző tanév")
ok(t.tanev_of("2026-09-01") == "2026/2027", "09-01 -> új tanév")
ok(t.tanev_of("2027-08-31") == "2026/2027", "a tanév utolsó napja (08-31)")
ok(t.tanev_of("2027-09-01") == "2027/2028", "következő tanév első napja")
ok(t.tanev_of("2027-01-15") == "2026/2027", "tanév közbeni dátum")
ok(t.tanev_of("2028-02-29") == "2027/2028", "szökőév: 02-29")
ok(t.tanev_of("") == "" and t.tanev_of(None) == "" and t.tanev_of("hibás") == "",
   "hiányzó/értelmezhetetlen dátum -> üres")

print("\n2) Dátumformátumok (KRÉTA magyar + ISO)")
ok(t.tanev_of("2026. 09. 22. 1:33") == "2026/2027", "magyar időbélyeg az üzeneteknél")
ok(t.tanev_of("2026. 08. 31.") == "2025/2026", "magyar dátum, tanévhatáron")
ok(t.tanev_of("2026-09-13T22:00:00Z") == "2026/2027", "ISO időbélyeg")
ok(t.parse_date("2026. 10. 05.") == date(2026, 10, 5), "parse_date magyar")
ok(t.parse_date("2026-10-05") == date(2026, 10, 5), "parse_date ISO")
ok(t.parse_date("nem dátum") is None, "parse_date hibás bemenetre None")

print("\n3) tanev_bounds")
ok(t.tanev_bounds("2026/2027") == (date(2026, 9, 1), date(2027, 8, 31)),
   "2026/2027 -> 2026-09-01 .. 2027-08-31")
ok(t.tanev_bounds("2026/2028") == (None, None), "nem egymást követő év -> (None, None)")
ok(t.tanev_bounds("hibás") == (None, None), "hibás bemenet -> (None, None)")
ok(t.tanev_bounds("") == (None, None), "üres bemenet -> (None, None)")

print("\n4) current_tanev (injektált dátummal)")
ok(t.current_tanev(date(2026, 11, 2)) == "2026/2027", "november: aktuális tanév")
ok(t.current_tanev(date(2027, 6, 30)) == "2026/2027", "nyáron a záruló tanév")
ok(t.current_tanev(date(2027, 9, 1)) == "2027/2028", "szeptember 1-jétől az új")

print("\n5) KRETA_TODAY env (a tanévváltás szimulációjának alapja)")
os.environ["KRETA_TODAY"] = "2027-09-01"
ok(t.today() == date(2027, 9, 1), "a today() az env-ből jön")
ok(t.current_tanev() == "2027/2028", "az aktuális tanév is az env szerint")
os.environ["KRETA_TODAY"] = "2027-08-31"
ok(t.current_tanev() == "2026/2027", "a váltás előtti nap: előző tanév")
os.environ.pop("KRETA_TODAY", None)

print("\n6) KRETA_TANEV_KEZDO env (iskolánként eltérő tanévkezdés)")
os.environ["KRETA_TANEV_KEZDO"] = "08-15"
ok(t.tanev_of("2026-08-14") == "2025/2026", "kezdés előtti nap: előző tanév")
ok(t.tanev_of("2026-08-15") == "2026/2027", "kezdés napja: új tanév")
os.environ.pop("KRETA_TANEV_KEZDO", None)
ok(t.tan_ev_kezdo() == (9, 1), "alapértelmezés: 09-01")

print("\n7) row_tanev: táblánkénti dátummező")
ok(t.row_tanev("esemenyek", {"esemeny_tipus": "Értékelés", "bej_datum": "2026. 10. 05."})
   == "2026/2027", "jegy: bej_datum")
ok(t.row_tanev("esemenyek", {"esemeny_tipus": "Házi feladat", "bej_datum": "2026. 08. 30.",
                             "hatarido": "2026. 09. 05."}) == "2026/2027",
   "házi: a határidő dönt (K5)")
ok(t.row_tanev("esemenyek", {"esemeny_tipus": "Bejelentett számonkérés",
                             "bej_datum": "2026. 08. 30.", "hatarido": "2027. 01. 10."})
   == "2026/2027", "számonkérés: a határidő dönt")
ok(t.row_tanev("esemenyek", {"esemeny_tipus": "Házi feladat", "bej_datum": "2026. 08. 30.",
                             "hatarido": ""}) == "2025/2026", "hiányzó határidő -> bej_datum")
ok(t.row_tanev("hianyzasok", {"mulasztas_datum": "2026-10-05"}) == "2026/2027", "hiányzás dátuma")
ok(t.row_tanev("igazolasok", {"kezdete": "2026-06-10", "vege": "2026-06-12"}) == "2025/2026",
   "igazolás kezdete")
ok(t.row_tanev("igazolasok", {"kezdete": "", "vege": "2026-09-05"}) == "2026/2027",
   "üres kezdet -> a vége dönt")
ok(t.row_tanev("uzenetek", {"idopont": "2026. 09. 22. 1:33"}) == "2026/2027", "üzenet időpontja")
ok(t.row_tanev("kifizetesek", {"kezdo_datum": "2026-10-01"}) == "2026/2027", "kifizetés kezdete")
ok(t.row_tanev("esemenyek", {"esemeny_tipus": "Értékelés", "bej_datum": ""}) == "",
   "ismeretlen dátum -> üres")

print("\n8) teljesen_lekert: a törlés előfeltétele")
ok(t.teljesen_lekert("2026/2027", "2026-09-01", "2027-06-30", today_value="2026-11-02") is True,
   "a tanév elejétől kértük, a mai napig: teljes")
ok(t.teljesen_lekert("2026/2027", "2026-10-01", "2027-06-30", today_value="2026-11-02") is False,
   "később kezdődő ablak: nem teljes")
ok(t.teljesen_lekert("2026/2027", "2026-09-01", "2026-09-30", today_value="2026-11-02") is False,
   "a mai napot sem éri el: nem teljes")
ok(t.teljesen_lekert("", "2026-09-01", "2027-06-30") is False, "ismeretlen tanév: soha")
ok(t.teljesen_lekert("2026/2027", None, None) is False, "hiányzó ablak: soha")

print("\n" + "=" * 60)
if _hibak:
    print(f"BUKOTT ({len(_hibak)} hiba)")
    sys.exit(1)
print("MINDEN ELLENŐRZÉS OK")
