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


def fetch_locked_branches():
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
                locked.append((name, data))
        print(f"Locked branches ({len(locked)}): {[n for n, _ in locked]}")
        return locked
    except Exception as exc:
        print(f"Warning fetching locked branches: {exc}")
        return []


def wait_for_app_ready(page):
    page.goto(APP_URL, wait_until="domcontentloaded", timeout=45000)
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(2000)


def hide_regional_totals(page):
    page.evaluate(
        """() => {
            const keywords = ["regional total", "regional totals", "region total", "region totals"];
            const rows = document.querySelectorAll("tr, [role='row'], .summary-row, .totals-row");
            for (const el of rows) {
                const txt = (el.innerText || "").trim().toLowerCase();
                if (txt && txt.length < 400 && keywords.some(k => txt.includes(k))) {
                    el.style.setProperty("display", "none", "important");
                }
            }
        }"""
    )
    page.wait_for_timeout(300)


def open_general_summary(page):
    # First check if a summary button/tab is already visible
    summary_patterns = re.compile(r"general\s*branches?\s*summary|branches?\s*summary|summary", re.I)
    for role in ("button", "link", "tab"):
        loc = page.get_by_role(role, name=summary_patterns)
        for i in range(loc.count()):
            item = loc.nth(i)
            if item.is_visible():
                item.click()
                page.wait_for_timeout(1500)
                hide_regional_totals(page)
                return

    # Otherwise open Admin Portal and look for summary inside it
    admin_btn = page.locator("button, a").filter(has_text=re.compile(r"admin\s*portal", re.I)).first
    if admin_btn.count() and admin_btn.is_visible():
        admin_btn.click()
        page.wait_for_timeout(1500)
        for role in ("button", "link", "tab"):
            loc = page.get_by_role(role, name=summary_patterns)
            for i in range(loc.count()):
                item = loc.nth(i)
                if item.is_visible():
                    item.click()
                    page.wait_for_timeout(1500)
                    break

    hide_regional_totals(page)


def select_branch_and_load(page, branch_name, branch_data=None):
    # 1. Native <select> dropdowns
    selects = page.locator("select")
    for i in range(selects.count()):
        sel = selects.nth(i)
        if not sel.is_visible():
            continue
        options = sel.locator("option")
        for j in range(options.count()):
            opt_text = (options.nth(j).inner_text() or "").strip()
            opt_val = (options.nth(j).get_attribute("value") or "").strip()
            if branch_name.lower() == opt_text.lower() or branch_name.lower() == opt_val.lower():
                sel.select_option(value=opt_val if opt_val else opt_text)
                page.wait_for_timeout(2000)
                return True

    # 2. Branch name text input: dispatch input, change, blur, and Enter so React/JS listeners load saved data
    inputs = page.locator("input[type='text'], input:not([type])")
    for i in range(inputs.count()):
        inp = inputs.nth(i)
        if not inp.is_visible():
            continue
        ph = (inp.get_attribute("placeholder") or "").lower()
        lbl = (inp.get_attribute("aria-label") or "").lower()
        if "branch" in ph or "branch" in lbl or i == 0:
            inp.click()
            inp.fill("")
            inp.type(branch_name, delay=40)
            inp.evaluate(
                """el => {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.blur();
                }"""
            )
            page.wait_for_timeout(2000)

            # If a load/open/view button exists next to branch selection, click it
            for btn_re in [r"load\s*branch", r"open\s*branch", r"view\s*sheet", r"load\s*sheet"]:
                b = page.locator("button").filter(has_text=re.compile(btn_re, re.I)).first
                if b.count() and b.is_visible():
                    b.click()
                    page.wait_for_timeout(2000)
                    break
            return True

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
    locked_branches = fetch_locked_branches()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1366, "height": 900}, device_scale_factor=2)
        page = context.new_page()

        # 1. General Branches Summary screenshot (excluding regional totals)
        wait_for_app_ready(page)
        open_general_summary(page)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(400)
        summary_png = page.screenshot(full_page=True)
        send_photo(summary_png, f"General Branches Summary ({stamp}) — Regional Totals Excluded")
        time.sleep(0.5)

        # 2. Independent screenshot for each locked branch
        total = len(locked_branches)
        for idx, (b_name, b_data) in enumerate(locked_branches, start=1):
            wait_for_app_ready(page)
            if select_branch_and_load(page, b_name, b_data):
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(400)
                branch_png = page.screenshot(full_page=True)
                send_photo(branch_png, f"[{idx}/{total}] Branch Report: {b_name} ({stamp})")
                time.sleep(0.4)

        browser.close()


if __name__ == "__main__":
    run_dispatch()
