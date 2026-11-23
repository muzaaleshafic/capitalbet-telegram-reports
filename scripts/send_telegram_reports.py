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
        print(f"Locked branches from API ({len(locked)}): {locked}")
        return locked
    except Exception as exc:
        print(f"Warning fetching locked branches from API: {exc}")
        return []


def wait_for_app_ready(page):
    page.goto(APP_URL, wait_until="domcontentloaded", timeout=45000)
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(2500)


def hide_regional_totals(page):
    # Only hide specific table rows or small row-like elements—never broad container divs
    page.evaluate(
        """() => {
            const keywords = ["regional total", "regional totals", "region total", "region totals"];
            const candidates = document.querySelectorAll("tr, [role='row'], .summary-row, .totals-row, li");
            for (const el of candidates) {
                const txt = (el.innerText || "").trim().toLowerCase();
                if (!txt || txt.length > 300) continue;
                if (keywords.some(k => txt.includes(k))) {
                    el.style.setProperty("display", "none", "important");
                }
            }
        }"""
    )
    page.wait_for_timeout(300)


def open_general_summary(page):
    candidates = [
        page.get_by_role("button", name=re.compile(r"general\s*branches?\s*summary|branches?\s*summary|summary", re.I)),
        page.get_by_role("link", name=re.compile(r"general\s*branches?\s*summary|branches?\s*summary|summary", re.I)),
        page.get_by_role("tab", name=re.compile(r"general\s*branches?\s*summary|branches?\s*summary|summary", re.I)),
        page.locator("button, a, [role='button'], .btn, .tab").filter(has_text=re.compile(r"general\s*branches?\s*summary|branches?\s*summary|summary", re.I)),
    ]
    for loc in candidates:
        try:
            count = loc.count()
            for i in range(count):
                item = loc.nth(i)
                if item.is_visible():
                    label = (item.inner_text() or "").strip()
                    print(f"Clicking summary control: '{label}'")
                    item.click()
                    page.wait_for_timeout(1500)
                    hide_regional_totals(page)
                    return True
        except Exception as exc:
            print(f"Summary click candidate failed: {exc}")

    hide_regional_totals(page)
    return False


def select_branch_in_ui(page, branch_name):
    # 1. Native <select> dropdowns
    selects = page.locator("select")
    for i in range(selects.count()):
        sel = selects.nth(i)
        try:
            if not sel.is_visible():
                continue
            options = sel.locator("option")
            for j in range(options.count()):
                opt_text = (options.nth(j).inner_text() or "").strip()
                opt_val = (options.nth(j).get_attribute("value") or "").strip()
                if branch_name.lower() == opt_text.lower() or branch_name.lower() in opt_text.lower() or branch_name.lower() == opt_val.lower():
                    sel.select_option(value=opt_val if opt_val else opt_text)
                    page.wait_for_timeout(1500)
                    return True
        except Exception:
            continue

    # 2. Visible text/search inputs
    inputs = page.locator("input[type='text'], input[type='search'], input:not([type])")
    for i in range(inputs.count()):
        inp = inputs.nth(i)
        try:
            if not inp.is_visible():
                continue
            ph = (inp.get_attribute("placeholder") or "").lower()
            lbl = (inp.get_attribute("aria-label") or "").lower()
            if "branch" in ph or "branch" in lbl or "search" in ph or i == 0:
                inp.fill(branch_name)
                inp.press("Enter")
                page.wait_for_timeout(1500)
                return True
        except Exception:
            continue

    # 3. Clickable branch item/button
    try:
        item = page.locator("button, a, [role='button'], li, .branch-item").filter(has_text=re.compile(rf"^{re.escape(branch_name)}$", re.I)).first
        if item.is_visible(timeout=1500):
            item.click()
            page.wait_for_timeout(1500)
            return True
    except Exception:
        pass

    return False


def capture_best_png(page):
    # Ensure page is scrolled to top and visible before capturing
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(400)
    body_len = page.evaluate("() => (document.body ? document.body.innerText.trim().length : 0)")
    print(f"Page body text length before screenshot: {body_len}")
    return page.screenshot(full_page=True)


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

        # 1. General Branches Summary screenshot (excluding regional totals)
        wait_for_app_ready(page)
        open_general_summary(page)
        summary_png = capture_best_png(page)
        send_photo(summary_png, f"General Branches Summary ({stamp}) — Regional Totals Excluded")
        time.sleep(0.5)

        # 2. Independent screenshot for each locked branch
        total = len(locked_branches)
        for idx, b_name in enumerate(locked_branches, start=1):
            wait_for_app_ready(page)
            if select_branch_in_ui(page, b_name):
                branch_png = capture_best_png(page)
                send_photo(branch_png, f"[{idx}/{total}] Branch Report: {b_name} ({stamp})")
                time.sleep(0.4)
            else:
                print(f"Could not select branch in UI: {b_name}")

        browser.close()


if __name__ == "__main__":
    run_dispatch()
