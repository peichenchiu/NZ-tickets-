"""每日檢查紐西蘭航空 14～20 天來回機票（全家總價），低於門檻就通知。

設定都可以用環境變數覆寫（見 README）。
"""
import datetime as dt
import json
import os
import re
import smtplib
import sys
import time
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urlencode

import requests
from playwright.sync_api import sync_playwright

ORIGIN = os.getenv("ORIGIN", "TPE")
DEST = os.getenv("DEST", "AKL")
DEPART_START = dt.date.fromisoformat(os.getenv("DEPART_START", "2027-02-20"))
DEPART_END = dt.date.fromisoformat(os.getenv("DEPART_END", "2027-03-31"))
TRIP_DAYS_MIN = int(os.getenv("TRIP_DAYS_MIN", "14"))
TRIP_DAYS_MAX = int(os.getenv("TRIP_DAYS_MAX", "20"))
THRESHOLD_TWD = int(os.getenv("THRESHOLD_TWD", "100000"))  # 全部乘客的總價
ADULTS = int(os.getenv("ADULTS", "2"))
CHILDREN = int(os.getenv("CHILDREN", "1"))  # 2～11 歲
CABIN = os.getenv("CABIN", "economy")  # economy / premiumeconomy / business
# 低於這個金額視為稅金、加購等雜項，不是整張票價
MIN_PLAUSIBLE_TWD = int(os.getenv("MIN_PLAUSIBLE_TWD", "10000"))
BOOKING_HOST = os.getenv("BOOKING_HOST", "https://flightbookings.airnewzealand.com.tw")
# 出發日×天數共約 280 組，全部每天查會超過 private repo 每月免費的 Actions 分鐘數，
# 所以每天只查 1/ROTATE 的出發日並輪替，ROTATE 天內會把所有組合查過一輪。
ROTATE = int(os.getenv("ROTATE", "3"))
LIMIT = int(os.getenv("LIMIT") or "0")  # 只查前幾組（診斷用），0 = 不限

RESULTS = Path("results")
DEBUG = Path("debug")
ISSUE_LABEL = "cheap-fare"

# TWD 金額：NT$ 12,345 / TWD 12,345 / NTD12345 / 12,345 TWD
PRICE_RE = re.compile(
    r"(?:NT\$|TWD|NTD)\s*([\d,]{4,})(?:\.\d+)?|([\d,]{4,})(?:\.\d+)?\s*(?:TWD|NTD|元)"
)
# 「總計 NT$ 123,456」這類標示全體乘客總價的字樣
TOTAL_RE = re.compile(r"總計|總價|總金額|合計|總額|Total", re.I)


def search_url(depart: dt.date, ret: dt.date) -> str:
    params = {
        "searchLegs[0].originPoint": ORIGIN,
        "searchLegs[0].destinationPoint": DEST,
        "searchLegs[0].tripStartMonth": depart.strftime("%b").upper(),
        "searchLegs[0].tripStartDate": depart.day,
        "searchLegs[1].originPoint": DEST,
        "searchLegs[1].destinationPoint": ORIGIN,
        "searchLegs[1].tripStartMonth": ret.strftime("%b").upper(),
        "searchLegs[1].tripStartDate": ret.day,
        "tripType": "return",
        "adults": ADULTS,
        "children": CHILDREN,
        "bookingClass": CABIN,
    }
    return f"{BOOKING_HOST}/vbook/actions/ext-search?{urlencode(params)}"


def extract_prices(text: str) -> list[int]:
    prices = []
    for m in PRICE_RE.finditer(text):
        value = int((m.group(1) or m.group(2)).replace(",", ""))
        if MIN_PLAUSIBLE_TWD <= value <= 2_000_000:
            prices.append(value)
    return prices


def extract_total_prices(text: str) -> list[int]:
    """只取緊接在「總計／Total」後面的金額。"""
    return [p for m in TOTAL_RE.finditer(text) for p in extract_prices(text[m.end():m.end() + 40])[:1]]


def check_one(page, depart: dt.date, ret: dt.date) -> dict:
    url = search_url(depart, ret)
    result = {"depart": depart.isoformat(), "return": ret.isoformat(), "url": url}
    json_bodies = []

    def on_response(resp):
        if "json" in resp.headers.get("content-type", ""):
            try:
                json_bodies.append(resp.text())
            except Exception:
                pass

    page.on("response", on_response)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        try:
            page.wait_for_load_state("networkidle", timeout=60_000)
        except Exception:
            pass
        page.wait_for_timeout(5_000)
        text = page.inner_text("body")
        title = page.title()
    except Exception as e:
        result.update(status="error", error=str(e)[:300])
        return result
    finally:
        page.remove_listener("response", on_response)

    prices = extract_prices(text) + [p for b in json_bodies for p in extract_prices(b)]
    tag = f"{depart.isoformat()}_{ret.isoformat()}"
    totals = extract_total_prices(text)
    if totals:
        result.update(status="ok", min_price=min(totals), price_kind="total")
    elif prices:
        # 頁面沒有「總計」字樣時，最低價可能只是每人價格；保守起見乘上人數估算總價，
        # 避免把每人 3 萬誤判成全家低於 10 萬
        result.update(status="ok", min_price=min(prices) * (ADULTS + CHILDREN),
                      price_kind="estimated", shown_price=min(prices))
    else:
        blocked = re.search(r"access denied|blocked|captcha|robot", title + text[:2000], re.I)
        result.update(status="blocked" if blocked else "no_price", title=title)
        # 留存畫面供調整解析規則
        DEBUG.mkdir(exist_ok=True)
        page.screenshot(path=str(DEBUG / f"{tag}.png"), full_page=True)
        (DEBUG / f"{tag}.txt").write_text(text, encoding="utf-8")
        (DEBUG / f"{tag}.json.txt").write_text("\n\n".join(json_bodies), encoding="utf-8")
        # 也印到 log，方便不下載 artifact 就能看頁面長相
        print(f"---- page text {tag} ----\n{text[:3000]}\n---- end ----", flush=True)
        money = sorted({m.group(0) for b in json_bodies
                        for m in re.finditer(r'"[^"]{0,40}"\s*:\s*"?[\d.,]{4,}"?', b)})
        print(f"---- json numeric fields {tag} ----\n" + "\n".join(money[:80]), flush=True)
    return result


def run_search() -> list[dict]:
    offset = dt.date.today().toordinal() % ROTATE
    pairs = []
    d = DEPART_START
    while d <= DEPART_END:
        if d.toordinal() % ROTATE == offset:
            for days in range(TRIP_DAYS_MIN, TRIP_DAYS_MAX + 1):
                pairs.append((d, d + dt.timedelta(days=days)))
        d += dt.timedelta(days=1)
    if LIMIT:
        pairs = pairs[:LIMIT]

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            viewport={"width": 1366, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()
        for depart, ret in pairs:
            r = check_one(page, depart, ret)
            print(json.dumps(r, ensure_ascii=False), flush=True)
            results.append(r)
            time.sleep(5)  # 放慢速度，避免被當成機器人
        browser.close()
    return results


# ---------- 通知 ----------

def notify_github(title: str, body: str) -> None:
    token, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY")
    if not (token and repo):
        return
    api = f"https://api.github.com/repos/{repo}"
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    issues = requests.get(
        f"{api}/issues", headers=h, params={"labels": ISSUE_LABEL, "state": "open"}, timeout=30
    ).json()
    if issues:
        requests.post(f"{api}/issues/{issues[0]['number']}/comments",
                      headers=h, json={"body": body}, timeout=30)
    else:
        requests.post(f"{api}/issues", headers=h,
                      json={"title": title, "body": body, "labels": [ISSUE_LABEL]}, timeout=30)


def previous_best() -> int | None:
    """已通知過的最低價（存在 open issue 的留言標記中），用來避免每天重複通知同樣價格。"""
    token, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY")
    if not (token and repo):
        return None
    api = f"https://api.github.com/repos/{repo}"
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    issues = requests.get(
        f"{api}/issues", headers=h, params={"labels": ISSUE_LABEL, "state": "open"}, timeout=30
    ).json()
    if not issues:
        return None
    texts = [issues[0].get("body") or ""]
    comments = requests.get(f"{api}/issues/{issues[0]['number']}/comments",
                            headers=h, params={"per_page": 100}, timeout=30).json()
    texts += [c.get("body") or "" for c in comments]
    found = [int(x) for t in texts for x in re.findall(r"<!-- best:(\d+) -->", t)]
    return min(found) if found else None


def notify_email(subject: str, body: str) -> None:
    user, pw = os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD")
    to = os.getenv("NOTIFY_EMAIL") or user  # 沒設定收件人就寄給自己
    if not (user and pw and to):
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.send_message(msg)


def notify_telegram(body: str) -> None:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if token and chat:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": body[:4000]}, timeout=30)


def notify(title: str, body: str) -> None:
    for fn in (lambda: notify_github(title, body),
               lambda: notify_email(title, body),
               lambda: notify_telegram(f"{title}\n\n{body}")):
        try:
            fn()
        except Exception as e:
            print(f"notify failed: {e}", file=sys.stderr)


def format_line(r: dict) -> str:
    days = (dt.date.fromisoformat(r["return"]) - dt.date.fromisoformat(r["depart"])).days
    note = ""
    if r.get("price_kind") != "total":
        note = f"（估算：頁面最低價 NT${r['shown_price']:,} × {ADULTS + CHILDREN} 人）"
    return f"- 去 {r['depart']} / 回 {r['return']}（{days} 天）：NT${r['min_price']:,}{note}\n  {r['url']}"


def main() -> int:
    results = run_search()
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "latest.json").write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                         encoding="utf-8")

    ok = [r for r in results if r["status"] == "ok"]
    cheap = sorted((r for r in ok if r["min_price"] < THRESHOLD_TWD), key=lambda r: r["min_price"])
    summary = (f"查詢 {len(results)} 組日期，成功取得價格 {len(ok)} 組，"
               f"低於 NT${THRESHOLD_TWD:,} 的有 {len(cheap)} 組。")
    print(summary)

    if not ok:
        # 全部失敗多半是網站擋爬蟲或版面改了，要讓使用者知道，而不是默默沒通知
        print("沒有抓到任何價格，請查看 artifact 中的 debug 截圖。", file=sys.stderr)
        return 1

    if cheap:
        best = cheap[0]["min_price"]
        prev = previous_best()
        if prev is not None and best >= prev:
            print(f"最低價 NT${best:,} 未低於已通知過的 NT${prev:,}，不重複通知。")
            return 0
        lines = [format_line(r) for r in cheap[:20]]
        body = (f"紐西蘭航空 {ORIGIN}⇄{DEST} {TRIP_DAYS_MIN}～{TRIP_DAYS_MAX} 天來回"
                f"（{CABIN}，{ADULTS} 成人 + {CHILDREN} 兒童）\n\n"
                + "\n".join(lines)
                + f"\n\n{summary}\n價格為爬取當下的頁面價格，實際以訂票頁為準，請點連結確認。"
                + f"\n<!-- best:{best} -->")
        notify(f"✈️ 紐航來回機票 {ADULTS + CHILDREN} 人 NT${best:,}（低於 NT${THRESHOLD_TWD:,}）", body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
