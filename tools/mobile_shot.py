# -*- coding: utf-8 -*-
"""
Mobil UI felmérés: képernyőképek + túlcsordulás-mérés minden fülnél.

A mérést FIX 393 CSS px széles viewporttal végezzük (Redmi 12/13/14 ~1080 px
fizikai / DPR 3), így a valódi túlcsordulás látszik (nem "kicsinyít" a böngésző).

Használat: python tools/mobile_shot.py [címke]   (az app a 5080-as porton fusson)
"""
import asyncio, os, sys, json
from pathlib import Path
from playwright.async_api import async_playwright

BASE = os.environ.get("SHOT_URL", "http://127.0.0.1:5080")
LABEL = sys.argv[1] if len(sys.argv) > 1 else "shot"
OUT = Path(r"C:\Users\tamas.reiner\AppData\Local\Temp\opencode\shots")
OUT.mkdir(parents=True, exist_ok=True)

TABS = [
    ("esemenyek", "esemenyek-tab"),
    ("orarend", "orarend-tab"),
    ("naptar", "naptar-tab"),
    ("uzenetek", "uzenetek-tab"),
    ("rewards", "rewards-tab"),
    ("logs", "logs-tab"),
]

MEASURE = """() => {
    const vw = window.innerWidth;
    const over = [];
    document.querySelectorAll('body *').forEach(el => {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        if (r.width > 0 && cs.position !== 'fixed' && r.right > vw + 1) {
            const cls = (el.className && typeof el.className === 'string') ? el.className.slice(0,60) : '';
            over.push({tag: el.tagName, cls: cls, right: Math.round(r.right), w: Math.round(r.width)});
        }
    });
    over.sort((a, b) => b.right - a.right);
    const small = [];
    document.querySelectorAll('button, .nav-link, input, select, .btn').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0 && r.height < 32) small.push(el.tagName + '.' + String(el.className).slice(0, 40));
    });
    const fs = parseFloat(getComputedStyle(document.body).fontSize);
    return {
        innerWidth: vw,
        scrollWidth: document.documentElement.scrollWidth,
        bodyFontSize: fs,
        overflowCount: over.length,
        overflowTop: over.slice(0, 6),
        smallTargets: small.slice(0, 6),
    };
}"""


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": 393, "height": 873},
            device_scale_factor=3,
            has_touch=True,
        )
        page = await ctx.new_page()
        await page.goto(BASE, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(2500)

        report = {"_alap": await page.evaluate(MEASURE)}
        await page.screenshot(path=str(OUT / f"{LABEL}_00_alap.png"))

        for name, tab_id in TABS:
            shown = await page.evaluate(
                """(id) => {
                    const el = document.getElementById(id);
                    if (!el) return 'nincs ilyen fül: ' + id;
                    if (window.bootstrap && bootstrap.Tab) {
                        bootstrap.Tab.getOrCreateInstance(el).show();
                        return 'ok';
                    }
                    el.click();
                    return 'click';
                }""", tab_id)
            await page.wait_for_timeout(1500)
            # a fül tartalmához görgetünk, hogy a képen a tartalom látszódjon
            await page.evaluate("""() => {
                const pane = document.querySelector('.tab-pane.active');
                if (pane) {
                    const y = pane.getBoundingClientRect().top + window.scrollY - 8;
                    window.scrollTo(0, Math.max(0, y));
                }
            }""")
            await page.wait_for_timeout(800)
            report[name] = await page.evaluate(MEASURE)
            report[name]["_switch"] = shown
            await page.screenshot(path=str(OUT / f"{LABEL}_{name}.png"))
            await page.screenshot(path=str(OUT / f"{LABEL}_{name}_full.png"), full_page=True)

        (OUT / f"{LABEL}_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        await browser.close()


asyncio.run(main())
