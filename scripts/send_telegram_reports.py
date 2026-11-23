import io
import os
import time
from datetime import datetime, timezone, timedelta
import requests
from PIL import Image, ImageDraw, ImageFont

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "9245368816:AAHiBn2ASPmUUiOmMQ6hGqeF48pKsqJyXfc")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-5548342041")
API_BASE = os.environ.get("BRANCH_API_URL", "https://governor.pythonanywhere.com")
EAT = timezone(timedelta(hours=3))

CATEGORIES = ["normal", "virtual", "aviator", "slot"]
LABELS = {
    "normal": "Normal Sales",
    "virtual": "Virtual Profits",
    "aviator": "Aviator Profits",
    "slot": "Slot Profits",
}


def load_font(size, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def fmt_num(v):
    try:
        return f"{float(v or 0):,.0f}"
    except (ValueError, TypeError):
        return "0"


def fmt_acc(d):
    n = round(float(d or 0))
    return f"({abs(n):,})" if n < 0 else f"{n:,}"


def fetch_all_branches():
    r = requests.get(f"{API_BASE}/api/get-all-branches", timeout=25)
    r.raise_for_status()
    j = r.json()
    return j.get("branches", {}) if isinstance(j, dict) and isinstance(j.get("branches"), dict) else {}


def get_locked_branches(bmap):
    out = []
    for name, data in bmap.items():
        if not isinstance(data, dict):
            continue
        m = data.get("currentMonth") or data.get("month") or ""
        mobj = (data.get("months") or {}).get(m) if isinstance(data.get("months"), dict) else None
        if data.get("setupLocked") or (isinstance(mobj, dict) and mobj.get("setupLocked")):
            out.append((name, data))
    return out


def month_days(m):
    try:
        y, mo = map(int, m.split("-"))
        a = datetime(y, mo, 1)
        b = datetime(y + 1, 1, 1) if mo == 12 else datetime(y, mo + 1, 1)
        return (b - a).days
    except Exception:
        return 30


def cur_week(m, total_days):
    now = datetime.now(EAT)
    day = now.day if m == now.strftime("%Y-%m") else 1
    wk = min(((day - 1) // 7) + 1, max(1, (total_days + 6) // 7))
    s = (wk - 1) * 7 + 1
    e = min(total_days, s + 6)
    return wk, s, e, e - s + 1


def build_summary_png_no_totals(locked):
    cw = [60, 250, 130, 130, 130, 140, 145]
    hdr_h, row_h, pad = 64, 36, 16
    img = Image.new("RGB", (sum(cw) + pad * 2, hdr_h + max(1, len(locked)) * row_h + pad * 2), "#ffffff")
    draw = ImageDraw.Draw(img)
    fh, fr, fb = load_font(12, True), load_font(12, False), load_font(12, True)
    x0, y0 = pad, pad
    xs, cur = [], x0
    for w in cw:
        xs.append(cur)
        cur += w

    draw.rectangle([x0, y0, x0 + sum(cw), y0 + hdr_h], fill="#161b26", outline="#2d3748")
    draw.rectangle([xs[2], y0 + 32, xs[2] + cw[2] + cw[3] + cw[4], y0 + hdr_h], fill="#f1f5f9", outline="#cbd5e1")
    draw.text((xs[0] + 18, y0 + 24), "NO", fill="#ffffff", font=fh)
    draw.text((xs[1] + 10, y0 + 24), "BRANCH", fill="#ffffff", font=fh)
    draw.text((xs[2] + 25, y0 + 10), "CURRENT WEEK TARGETS", fill="#ffffff", font=fh)
    draw.text((xs[2] + 12, y0 + 40), "Target", fill="#0f172a", font=fh)
    draw.text((xs[3] + 12, y0 + 40), "Achieved", fill="#0f172a", font=fh)
    draw.text((xs[4] + 12, y0 + 40), "Balance", fill="#0f172a", font=fh)
    draw.text((xs[5] + 10, y0 + 24), "ACHIEVED (MONTH)", fill="#ffffff", font=fh)
    draw.text((xs[6] + 10, y0 + 24), "MONTHLY VARIANCE", fill="#ffffff", font=fh)

    for idx, (bname, bdata) in enumerate(locked, 1):
        ry = y0 + hdr_h + (idx - 1) * row_h
        bg = "#f8fafc" if idx % 2 == 0 else "#ffffff"
        draw.rectangle([x0, ry, x0 + sum(cw), ry + row_h], fill=bg, outline="#e2e8f0")

        m = bdata.get("currentMonth") or bdata.get("month") or datetime.now(EAT).strftime("%Y-%m")
        ms = (bdata.get("months") or {}).get(m) or bdata
        rmap, tmap = ms.get("rows") or {}, ms.get("targets") or {}
        mt = sum(float((tmap.get(k) or {}).get("value") or 0) for k in CATEGORIES)
        tdays = month_days(m)
        _, sd, ed, dwk = cur_week(m, tdays)
        wach = mach = 0.0
        for dstr, rvals in rmap.items():
            if not isinstance(rvals, dict):
                continue
            csum = sum(float(rvals.get(k) or 0) for k in CATEGORIES)
            mach += csum
            try:
                dv = int(dstr.split("-")[-1])
                if sd <= dv <= ed:
                    wach += csum
            except Exception:
                pass

        wt = mt * (dwk / max(1, tdays))
        wb = wach - wt
        mvar = mt - mach

        draw.text((xs[0] + 18, ry + 11), str(idx), fill="#1e293b", font=fr)
        draw.text((xs[1] + 10, ry + 11), f"{bname} ({m})", fill="#0f172a", font=fb)
        draw.text((xs[2] + 10, ry + 11), fmt_num(wt), fill="#0f172a", font=fr)
        draw.text((xs[3] + 10, ry + 11), fmt_num(wach), fill="#0f172a", font=fr)
        draw.text((xs[4] + 10, ry + 11), fmt_acc(wb), fill="#dc2626" if wb < 0 else "#0f172a", font=fb)
        draw.text((xs[5] + 10, ry + 11), fmt_num(mach), fill="#0f172a", font=fb)
        draw.text((xs[6] + 10, ry + 11), fmt_acc(mvar), fill="#dc2626" if mvar < 0 else "#0f172a", font=fb)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def build_branch_card_png(bname, bdata):
    m = bdata.get("currentMonth") or bdata.get("month") or datetime.now(EAT).strftime("%Y-%m")
    ms = (bdata.get("months") or {}).get(m) or bdata
    rmap, tmap = ms.get("rows") or {}, ms.get("targets") or {}
    sdates = sorted(rmap.keys())[-10:]
    w, h = 980, 140 + max(1, len(sdates)) * 28 + 190
    img = Image.new("RGB", (w, h), "#090d16")
    draw = ImageDraw.Draw(img)
    ft, fh, fx = load_font(18, True), load_font(12, True), load_font(12, False)

    draw.rectangle([16, 16, w - 16, 84], fill="#111827", outline="#1f2937")
    draw.text((32, 28), f"CAPITALBET | {bname.upper()} ({m})", fill="#f8fafc", font=ft)
    draw.text((32, 54), "Daily Sales Data, Target Balances & Remaining to Target", fill="#94a3b8", font=fx)

    lx, ly, lw = 16, 100, 610
    draw.rectangle([lx, ly, lx + lw, h - 16], fill="#111827", outline="#1f2937")
    draw.text((lx + 14, ly + 10), "Daily Sales Data", fill="#f8fafc", font=fh)
    cols = ["DATE", "NORMAL SALES", "VIRTUAL PROFITS", "AVIATOR PROFITS", "SLOT PROFITS"]
    cx = [lx + 14, lx + 135, lx + 255, lx + 375, lx + 495]
    for x, c in zip(cx, cols):
        draw.text((x, ly + 36), c, fill="#94a3b8", font=fh)

    ctot = {k: 0.0 for k in CATEGORIES}
    for ar in rmap.values():
        if isinstance(ar, dict):
            for k in CATEGORIES:
                ctot[k] += float(ar.get(k) or 0)

    yc = ly + 62
    for dk in sdates:
        ro = rmap.get(dk) or {}
        draw.text((cx[0], yc), dk, fill="#e2e8f0", font=fx)
        for i, k in enumerate(CATEGORIES):
            val = float(ro.get(k) or 0)
            draw.text((cx[i + 1], yc), fmt_num(val), fill="#f87171" if val < 0 else "#e2e8f0", font=fx)
        yc += 26

    draw.text((cx[0], yc + 8), "TOTAL AMOUNT", fill="#ffffff", font=fh)
    for i, k in enumerate(CATEGORIES):
        draw.text((cx[i + 1], yc + 8), fmt_num(ctot[k]), fill="#38bdf8", font=fh)

    rx, ry = 642, 100
    draw.rectangle([rx, ry, w - 16, h - 16], fill="#111827", outline="#1f2937")
    draw.text((rx + 14, ry + 10), "Target Balances & Remaining", fill="#f8fafc", font=fh)

    ty = ry + 38
    for k in CATEGORIES:
        tv = float((tmap.get(k) or {}).get("value") or 0)
        rem = tv - ctot[k]
        draw.text((rx + 14, ty), f"{LABELS[k]}: Target {fmt_num(tv)}", fill="#e2e8f0", font=fx)
        rtxt = f"Remaining: {fmt_num(rem)}" if rem > 0 else f"Exceeded: {fmt_num(abs(rem))}"
        draw.text((rx + 14, ty + 18), rtxt, fill="#f87171" if rem > 0 else "#34d399", font=fx)
        ty += 46

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def send_photo(buf, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    files = {"photo": ("report.png", buf, "image/png")}
    data = {"chat_id": CHAT_ID, "caption": caption[:1024]}
    for attempt in range(4):
        r = requests.post(url, data=data, files=files, timeout=30)
        if r.status_code == 429:
            retry_after = int(r.json().get("parameters", {}).get("retry_after", 2))
            time.sleep(retry_after + 1)
            buf.seek(0)
            continue
        r.raise_for_status()
        return


def run_dispatch():
    locked = get_locked_branches(fetch_all_branches())
    stamp = datetime.now(EAT).strftime("%Y-%m-%d %H:%M EAT")

    send_photo(build_summary_png_no_totals(locked), f"General Branches Summary ({stamp}) — Regional Totals Excluded")
    time.sleep(0.5)

    total = len(locked)
    for idx, (bname, bdata) in enumerate(locked, 1):
        send_photo(build_branch_card_png(bname, bdata), f"[{idx}/{total}] Branch Report: {bname} ({stamp})")
        time.sleep(0.35)


if __name__ == "__main__":
    run_dispatch()
