import io
import os
import re
import time
from datetime import datetime, timezone, timedelta
import requests
from playwright.sync_api import sync_playwright

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "9245368816:AAHiBn2ASPmUUiOmMQ6hGqeF48pKsqJyXfc")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-5548342041")
APP_URL = os.environ.get("APP_URL", "https://targetsheet0.netlify.app/")
API_BASE = os.environ.get("API_BASE", "https://governor.pythonanywhere.com")
EAT = timezone(timedelta(hours=3))


def fetch_locked_branch_names():
    try:
        r = requests.get(f"{API_BASE}/api/get-all-branches", timeout=25)
        r.raise_for_status()
        payload = r.json()
        bmap = payload.get("branches") if isinstance(payload, dict) else {}
        if not isinstance(bmap, dict):
            return []
        locked = []
        for name, data in bmap.items():
            if not isinstance(data, dict):
                continue
            month = data.get("currentMonth") or data.get("month") or ""
            months = data.get("months") if isinstance(data.get("months"), dict) else {}
            m_obj = months.get(month) if month in months and isinstance(months.get(month), dict) else None
            if data.get("setupLocked") or (m_obj and m_obj.get("setupLocked")):
                locked.append(name)
        return locked
    except Exception as exc:
        print(f"Warning fetching locked branches from API: {exc}")
        return []


def click_if_visible(page, selectors, timeout=2500):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=timeout):
                loc.click()
                page.wait_for_timeout(800)
                return True
        except Exception:
            continue
    return False


def hide_regional_totals(page):
    page.evaluate(
        """() => {
            const keywords = ["regional total", "regional totals", "region total", "region totals"];
            const nodes = document.querySelectorAll("tr, .row, .summary-row, .totals-row, div");
            for (const el of nodes) {
                const txt = (el.innerText || "").trim().toLowerCase();
                if (!txt) continue;
                const matches = keywords.some(k => txt.includes(k));
                if (matches && txt.length < 240) {
                    const isTableRow = el.tagName === "TR";
                    const hasChildRow = !isTableRow && el.querySelector("tr, .row, .summary-row");
                    if (!hasChildRow) {
                        el.style.display = "none";
                    }
                }
            }
        }"""
    )
    page.wait_for_timeout(300)


def open_general_summary(page):
    clicked = click_if_visible(
        page,
        [
            "button:has-text('General Branches Summary')",
            "a:has-text('General Branches Summary')",
            "text=/general branches summary/i",
            "button:has-text('Branches Summary')",
            "button:has-text('Summary')",
        ],
    )
    if clicked:
        page.wait_for_timeout(1000)
    hide_regional_totals(page)


def select_branch_in_ui(page, branch_name):
    # Try native <select> dropdown first
    selects = page.locator("select")
    for i in range(selects.count()):
        sel = selects.nth(i)
        try:
            options = sel.locator("option")
            for j in range(options.count()):
                opt_text = (options.nth(j).inner_text() or "").strip()
                opt_val = (options.nth(j).get_attribute("value") or "").strip()
                if branch_name.lower() in opt_text.lower() or branch_name.lower() == opt_val.lower():
                    sel.select_option(value=opt_val if opt_val else opt_text)
                    page.wait_for_timeout(1000)
                    return True
        except Exception:
            continue

    # Try text input or searchable branch field
    inputs = page.locator("input[type='text'], input:not([type])")
    for i in range(inputs.count()):
        inp = inputs.nth(i)
        try:
            ph = (inp.get_attribute("placeholder") or "").lower()
            lbl = (inp.get_attribute("aria-label") or "").lower()
            if "branch" in ph or "branch" in lbl or i == 0:
                inp.fill(branch_name)
                inp.press("Enter")
                page.wait_for_timeout(1000)
                return True
        except Exception:
            continue

    # Fallback: click matching branch item/button
    try:
        item = page.get_by_text(re.compile(re.escape(branch_name), re.I)).first
        if item.is_visible(timeout=1500):
            item.click()
            page.wait_for_timeout(1000)
            return True
    except Exception:
        pass

    return False


def send_photo(png_bytes, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    buf = io.BytesIO(png_bytes)
    files = {"photo": ("screenshot.png", buf, "image/png")}
    data = {"chat_id": CHAT_ID, "caption": caption[:1024]}
    for _ in range(4):
        resp = requests.post(url, data=data, files=files, timeout=35)
        if resp.status_code == 429:
            retry_after = int(resp.json().get("parameters", {}).get("retry_after", 2))
            time.sleep(retry_after + 1)
            buf.seek(0)
            continue
        resp.raise_for_status()
        return


def run_dispatch():
    stamp = datetime.now(EAT).strftime("%Y-%m-%d %H:%M EAT")
    locked_branches = fetch_locked_branch_names()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1366, "height": 900}, device_scale_factor=2)
        page = context.new_page()
        page.goto(APP_URL, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(1500)

        # 1. General Branches Summary screenshot (excluding regional totals)
        open_general_summary(page)
        summary_png = page.screenshot(full_page=True)
        send_photo(summary_png, f"General Branches Summary ({stamp}) — Regional Totals Excluded")
        time.sleep(0.5)

        # 2. Independent screenshot for each locked branch
        total = len(locked_branches)
        for idx, b_name in enumerate(locked_branches, start=1):
            page.goto(APP_URL, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(1000)
            if select_branch_in_ui(page, b_name):
                branch_png = page.screenshot(full_page=True)
                send_photo(branch_png, f"[{idx}/{total}] Branch Report: {b_name} ({stamp})")
                time.sleep(0.4)

        browser.close()


if __name__ == "__main__":
    run_dispatch()
