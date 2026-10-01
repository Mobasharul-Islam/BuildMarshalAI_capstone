"""Render poster.html to a print-ready PDF and a PNG proof.

Chrome is used rather than a Python PDF library because the poster is laid out
in CSS: printToPDF keeps the text as vector glyphs with the fonts embedded, so
the 18x24in sheet is genuinely print-ready rather than a large picture of one.

    python poster/render.py            # PDF + PNG proof
    python poster/render.py --png-only
"""
from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "poster.html"
PDF = HERE / "BuildMarshalAI-poster-18x24.pdf"
PNG = HERE / "BuildMarshalAI-poster-preview.png"

WIDTH_IN, HEIGHT_IN = 18, 24
#: Wide enough to judge the typography on screen, small enough to send.
PROOF_WIDTH = 1500


def browser_for(scale: float) -> webdriver.Chrome:
    options = Options()
    for flag in ("--headless=new", "--hide-scrollbars", "--no-sandbox",
                 "--disable-gpu", "--allow-file-access-from-files",
                 f"--force-device-scale-factor={scale}",
                 f"--window-size={round(WIDTH_IN * 96)},{round(HEIGHT_IN * 96)}"):
        options.add_argument(flag)
    return webdriver.Chrome(options=options)


def wait_for_paint(browser: webdriver.Chrome) -> None:
    """Fonts and images both have to be in before anything is captured."""
    browser.execute_script("return document.fonts.ready")
    for _ in range(40):
        ready = browser.execute_script(
            "return document.fonts.status === 'loaded' && "
            "[...document.images].every(i => i.complete && i.naturalWidth > 0);")
        if ready:
            break
        time.sleep(0.25)
    time.sleep(1.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--png-only", action="store_true")
    options = parser.parse_args()

    if not options.png_only:
        browser = browser_for(1)
        try:
            browser.get(SOURCE.as_uri())
            wait_for_paint(browser)
            result = browser.execute_cdp_cmd("Page.printToPDF", {
                "paperWidth": WIDTH_IN, "paperHeight": HEIGHT_IN,
                "marginTop": 0, "marginBottom": 0, "marginLeft": 0, "marginRight": 0,
                "printBackground": True, "preferCSSPageSize": True,
                "scale": 1,
            })
            PDF.write_bytes(base64.b64decode(result["data"]))
            print(f"  {PDF.name}  {PDF.stat().st_size / 1024 / 1024:.1f} MB  "
                  f"({WIDTH_IN}x{HEIGHT_IN} in, vector text)")
        finally:
            browser.quit()

    # The proof is a real render at the same size, scaled down for looking at.
    scale = PROOF_WIDTH / (WIDTH_IN * 96)
    browser = browser_for(round(scale, 4))
    try:
        browser.get(SOURCE.as_uri())
        wait_for_paint(browser)
        browser.set_window_size(round(WIDTH_IN * 96), round(HEIGHT_IN * 96))
        time.sleep(0.6)
        shot = browser.execute_cdp_cmd("Page.captureScreenshot", {
            "format": "png", "captureBeyondViewport": True,
            "clip": {"x": 0, "y": 0, "width": WIDTH_IN * 96,
                     "height": HEIGHT_IN * 96, "scale": round(scale, 4)},
        })
        PNG.write_bytes(base64.b64decode(shot["data"]))
        print(f"  {PNG.name}  {PNG.stat().st_size / 1024:.0f} KB")
    finally:
        browser.quit()


if __name__ == "__main__":
    main()
