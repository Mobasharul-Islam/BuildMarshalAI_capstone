"""Rasterise the poster's vector artwork for the PowerPoint version.

The PDF keeps the artwork as vectors. PowerPoint cannot be handed SVG through
the file format we build with, so the three pieces are rendered once here at
print resolution and placed as images. Only the art is flattened — every word
in the deck stays an editable text box, which is the point of that version.

    python poster/rasterise.py
"""
from __future__ import annotations

import base64
import sys
import tempfile
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import artwork as art  # noqa: E402
import build_poster as bp  # noqa: E402

OUT = HERE / "assets"
DPI = 200


def shoot(svg: str, width_px: int, height_px: int, target: Path,
          background: str = "transparent") -> None:
    page = (f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
            f'html,body{{margin:0;padding:0;background:{background};'
            f'width:{width_px}px;height:{height_px}px;overflow:hidden}}'
            f'svg{{width:{width_px}px;height:{height_px}px;display:block}}'
            f'</style></head><body>{svg}</body></html>')
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "art.html"
        source.write_text(page, encoding="utf-8")
        options = Options()
        for flag in ("--headless=new", "--hide-scrollbars", "--no-sandbox",
                     "--disable-gpu", "--force-device-scale-factor=1",
                     f"--window-size={width_px},{height_px}"):
            options.add_argument(flag)
        browser = webdriver.Chrome(options=options)
        try:
            browser.get(source.as_uri())
            time.sleep(1.2)
            shot = browser.execute_cdp_cmd("Page.captureScreenshot", {
                "format": "png", "captureBeyondViewport": True,
                "clip": {"x": 0, "y": 0, "width": width_px, "height": height_px,
                         "scale": 1},
            })
        finally:
            browser.quit()
    target.write_bytes(base64.b64decode(shot["data"]))
    print(f"  {target.name}  {width_px}x{height_px}  "
          f"{target.stat().st_size / 1024:.0f} KB")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # The hero, minus the headline: field, corona and the lit sheet, in the
    # one image so their overlaps stay exactly as the PDF has them.
    hero_w, hero_h = int(18 * DPI), int(bp.HERO_IN * DPI)
    layered = (art.page_field(bp.HERO_W, bp.HERO_H, columns=22, rows=13, uid="rf")
               + art.lit_page(bp.HERO_W, bp.HERO_H, bp.PAGE_CX, bp.PAGE_CY,
                              bp.PAGE_W, bp.PAGE_H, bp.PAGE_ANGLE, uid="rc",
                              part="corona")
               + art.lit_page(bp.HERO_W, bp.HERO_H, bp.PAGE_CX, bp.PAGE_CY,
                              bp.PAGE_W, bp.PAGE_H, bp.PAGE_ANGLE, uid="rs",
                              part="sheet"))
    stacked = "".join(
        f'<div style="position:absolute;inset:0">{piece}</div>'
        for piece in layered.replace("</svg><svg", "</svg>|<svg").split("|"))
    shoot(f'<div style="position:relative;width:{hero_w}px;height:{hero_h}px">'
          f'{stacked}</div>', hero_w, hero_h, OUT / "hero.png", art.INK)

    side = int(3.08 * DPI)
    shoot(art.cited_page(620, 560, columns=8, rows=6, lit_col=5, lit_row=3, uid="r1"),
          side, int(side * 560 / 620), OUT / "art-01.png", art.INK)
    shoot(art.honest_gap(620, 560, teeth=24, missing=(3, 4, 11, 18), uid="r2"),
          side, int(side * 560 / 620), OUT / "art-02.png", art.INK)


if __name__ == "__main__":
    main()
