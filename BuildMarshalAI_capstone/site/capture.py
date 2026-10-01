"""Capture the product shots the homepage uses.

Full application windows rather than cropped panels: a marketing page wants to
show the thing working, in context. Taken from the running build at 2x so they
stay sharp on a high-density display.

    python site/capture.py            # needs the demo backend on :8901
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as expect
from selenium.webdriver.support.ui import WebDriverWait

BASE = "http://127.0.0.1:8901"
EMAIL, PASSWORD = "rafiqul.islam@purbachalcon.example", "PadmaView2026!"
OUT = Path(__file__).resolve().parent / "assets"
SCALE = 2


def token() -> str:
    request = urllib.request.Request(
        f"{BASE}/api/auth/login", method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode())
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read())["token"]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    options = Options()
    for flag in ("--headless=new", "--window-size=1560,1000", "--hide-scrollbars",
                 f"--force-device-scale-factor={SCALE}", "--no-sandbox", "--disable-gpu"):
        options.add_argument(flag)
    browser = webdriver.Chrome(options=options)

    def shot(name: str, trim_bottom: int = 0) -> None:
        path = OUT / f"{name}.png"
        browser.save_screenshot(str(path))
        if trim_bottom:
            image = Image.open(path)
            image.crop((0, 0, image.width, image.height - trim_bottom)).save(path)
        print(f"  {name}.png  {Image.open(path).size}")

    def ask(text: str, settle: float = 5.0) -> None:
        browser.execute_script(
            "const p=document.getElementById('chatPanel');"
            "if(p){p.classList.add('visible');p.classList.remove('collapsed');}")
        box = browser.find_element(By.CSS_SELECTOR, "#chatInput")
        box.clear()
        box.send_keys(text)
        browser.execute_script("arguments[0].click()",
                               browser.find_element(By.CSS_SELECTOR, "#btnChatSend"))
        time.sleep(settle)

    def go(match: str, settle: float = 4.0) -> None:
        browser.execute_script(
            "const n=[...document.querySelectorAll('.nav-item')]"
            ".find(e=>new RegExp(arguments[0],'i').test(e.textContent)); if(n) n.click();", match)
        time.sleep(settle)

    try:
        browser.get(BASE)
        WebDriverWait(browser, 20).until(expect.presence_of_element_located(
            (By.CSS_SELECTOR, "input[type=password], .nav-item")))
        browser.execute_script(
            "localStorage.setItem('bmarshal_session', arguments[0]);"
            "localStorage.setItem('bmarshal_api_url', arguments[1]);"
            "localStorage.setItem('bmarshal_api_url_pinned','1');",
            json.dumps({"token": token()}), BASE)
        browser.get(BASE)
        WebDriverWait(browser, 25).until(
            expect.presence_of_element_located((By.CSS_SELECTOR, ".nav-item")))
        time.sleep(5)

        # The hero: an answer with the page it came from, beside the project.
        go("Projects", 4.5)
        ask("What concrete grade is specified for the slabs?")
        shot("app-answer")

        # The second promise: it asks rather than invents.
        browser.execute_script(
            "document.querySelectorAll('#chatMessages .chat-msg').forEach(n=>n.remove())")
        ask('Create a project called "Riverside Depot".', 5.0)
        ask("RD-2027", 4.5)
        ask("John is the project manager", 4.5)
        shot("app-asking")

        # Records, and the plan behind them.
        browser.execute_script(
            "const p=document.getElementById('chatPanel');"
            "if(p){p.classList.remove('visible');p.classList.add('collapsed');}")
        browser.execute_script(
            "document.querySelectorAll('.modal-overlay.open').forEach(m=>m.classList.remove('open'))")
        go("Onboarding", 4.5)
        shot("app-onboarding")
        go("Tasks", 4.5)
        shot("app-tasks")
    finally:
        browser.quit()
    print(f"\n  written to {OUT}")


if __name__ == "__main__":
    main()
