import io
import json
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


def fetch_all_branches_realtime():
    ts = int(time.time() * 1000)
    r = requests.get(
        f"{API_BASE}/api/get-all-branches",
        params={"_ts": ts},
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        timeout=25,
    )
    r.raise_for_status()
    payload = r.json()
    bmap = payload.get("branches") if isinstance(payload, dict) else {}
    return bmap if isinstance(bmap, dict) else {}


def get_locked_branches(bmap):
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


def dismiss_admin_modal(page):
    page.evaluate(
        """() => {
            const buttons = Array.from(document.querySelectorAll("button, a"));
            for (const btn of buttons) {
                const t = (btn.innerText || "").trim().toLowerCase();
                if (t === "cancel" || t === "close" || t === "×" || t === "x") {
                    const modal = btn.closest("[role='dialog'], .modal, .popup, div");
                    const mText = (modal ? modal.innerText : document.body.innerText || "").toLowerCase();
                    if (mText.includes("admin password") || mText.includes("supervisor / admin access")) {
                        btn.click();
                    }
                }
            }
        }"""
    )
    page.wait_for_timeout(300)


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
    page.wait_for_timeout(250)


def hydrate_realtime_data(page, bmap):
    page.evaluate(
        """(branchesObj) => {
            try {
                const keys = Object.keys(localStorage || {});
                for (const k of keys) {
                    const lk = k.toLowerCase();
                    if (lk.includes("branch") || lk.includes("target") || lk.includes("sheet") || lk.includes("capitalbet")) {
                        try {
                            const existing = JSON.parse(localStorage.getItem(k));
                            if (existing && typeof existing === "object" && !Array.isArray(existing)) {
                                if ("branches" in existing && typeof existing.branches === "object") {
                                    existing.branches = Object.assign({}, existing.branches, branchesObj);
                                    localStorage.setItem(k, JSON.stringify(existing));
                                } else {
                                    localStorage.setItem(k, JSON.stringify(Object.assign({}, existing, branchesObj)));
                                }
                            }
                        } catch (_) {}
                    }
                }
                if (!localStorage.getItem("capitalbet_branches")) {
                    localStorage.setItem("capitalbet_branches", JSON.stringify(branchesObj));
                }
            } catch (_) {}
        }""",
        bmap,
    )


def open_non_modal_summary(page):
    dismiss_admin_modal(page)
    summary_re = re.compile(r"general\s*branches?\s*summary|branches?\s*summary", re.I)
    for role in ("button", "link", "tab"):
        loc = page.get_by_role(role, name=summary_re)
        for i in range(loc.count()):
            item = loc.nth(i)
            if item.is_visible():
                item.click()
                page.wait_for_timeout(1200)
                if page.get_by_text(re.compile(r"admin\s*password", re.I)).count() > 0:
                    dismiss_admin_modal(page)
                else:
                    hide_regional_totals(page)
                    return True
    hide_regional_totals(page)
    return False


def apply_branch_to_sheet(page, branch_name, branch_data):
    month_str = (branch_data or {}).get("currentMonth") or (branch_data or {}).get("month") or ""
    year_val, month_num = "", ""
    if re.match(r"^\d{4}-\d{2}$", str(month_str)):
        year_val, month_num = str(month_str).split("-")

    page.evaluate(
        """({ branchName, yearVal, monthNum, branchData }) => {
            // Set branch input
            const inputs = Array.from(document.querySelectorAll("input"));
            for (const inp of inputs) {
                const ph = (inp.getAttribute("placeholder") || "").toLowerCase();
                const lbl = (inp.getAttribute("aria-label") || "").toLowerCase();
                if (ph.includes("branch") || lbl.includes("branch") || inp === document.querySelector("input[type='text'], input:not([type])")) {
                    inp.value = branchName;
                    inp.dispatchEvent(new Event("input", { bubbles: true }));
                    inp.dispatchEvent(new Event("change", { bubbles: true }));
                    inp.dispatchEvent(new Event("blur", { bubbles: true }));
                    break;
                }
            }

            // Set year input/select if present
            if (yearVal) {
                for (const el of document.querySelectorAll("input, select")) {
                    const v = (el.value || "").trim();
                    if (/^202\d$/.test(v) || (el.getAttribute("placeholder") || "").includes("202")) {
                        el.value = yearVal;
                        el.dispatchEvent(new Event("input", { bubbles: true }));
                        el.dispatchEvent(new Event("change", { bubbles: true }));
                    }
                }
            }

            // Set month select if present
            if (monthNum) {
                const monthNames = {
                    "01": "january", "02": "february", "03": "march", "04": "april",
                    "05": "may", "06": "june", "07": "july", "08": "august",
                    "09": "september", "10": "october", "11": "november", "12": "december"
                };
                const targetM = monthNames[monthNum] || "";
                for (const sel of document.querySelectorAll("select")) {
                    const opts = Array.from(sel.options || []);
                    const match = opts.find(o => {
                        const t = (o.text || "").trim().toLowerCase();
                        const val = (o.value || "").trim().toLowerCase();
                        return val === monthNum || val === String(parseInt(monthNum, 10)) || (targetM && t.startsWith(targetM));
                    });
                    if (match) {
                        sel.value = match.value;
                        sel.dispatchEvent(new Event("change", { bubbles: true }));
                    }
                }
            }
        }""",
        {
            "branchName": branch_name,
            "yearVal": year_val,
            "monthNum": month_num,
            "branchData": branch_data,
        },
    )
    page.wait_for_timeout(1500)


def reveal_last_filled_date_rows(page):
    # Expand scroll containers and scroll down so the last filled date rows & totals are fully visible
    page.evaluate(
        """() => {
            const containers = Array.from(document.querySelectorAll("div, section, table, tbody"));
            for (const el of containers) {
                const style = window.getComputedStyle(el);
                const canScrollY = (style.overflowY === "auto" || style.overflowY === "scroll" || el.scrollHeight > el.clientHeight + 20);
                if (canScrollY && el.scrollHeight > el.clientHeight) {
                    // Expand table/card container if it's a sales table wrapper so no rows are clipped
                    const txt = (el.innerText || "").toLowerCase();
                    if (txt.includes("normal sales") && (txt.includes("nov 2026") || txt.includes("total amount") || el.tagName === "DIV")) {
                        el.style.maxHeight = "none";
                        el.style.height = "auto";
                        el.style.overflowY = "visible";
                    } else {
                        el.scrollTop = el.scrollHeight;
                    }
                }
            }
            window.scrollTo(0, document.body.scrollHeight);
        }"""
    )
    page.wait_for_timeout(500)


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
    all_branches = fetch_all_branches_realtime()
    locked_branches = get_locked_branches(all_branches)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100}, device_scale_factor=2)
        page = context.new_page()

        def load_app():
            page.goto(APP_URL, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
            hydrate_realtime_data(page, all_branches)
            page.wait_for_timeout(600)

        # 1. General Branches Summary screenshot (excluding regional totals, avoiding password modal)
        load_app()
        open_non_modal_summary(page)
        reveal_last_filled_date_rows(page)
        summary_png = page.screenshot(full_page=True)
        send_photo(summary_png, f"General Branches Summary ({stamp}) — Regional Totals Excluded")
        time.sleep(0.5)

        # 2. Independent screenshot for each locked branch with last filled date rows visible
        total = len(locked_branches)
        for idx, (b_name, b_data) in enumerate(locked_branches, start=1):
            load_app()
            apply_branch_to_sheet(page, b_name, b_data)
            reveal_last_filled_date_rows(page)
            branch_png = page.screenshot(full_page=True)
            send_photo(branch_png, f"[{idx}/{total}] Branch Report: {b_name} ({stamp})")
            time.sleep(0.4)

        browser.close()


if __name__ == "__main__":
    run_dispatch()
