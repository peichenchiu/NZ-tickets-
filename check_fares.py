"""每日檢查紐西蘭航空 14 天來回機票，低於門檻就通知。

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
TRIP_DAYS = int(os.getenv("TRIP_DAYS", "14"))
THRESHOLD_TWD = int(os.getenv("THRESHOLD_TWD", "100000"))
ADULTS = int(os.getenv("ADULTS", "1"))
CABIN = os.getenv("CABIN", "economy")  # economy / premiumeconomy / business
# 低於這個金額視為稅金、加購等雜項，不是整張票價
MIN_PLAUSIBLE_TWD = int(os.getenv("MIN_PLAUSIBLE_TWD", "10000"))
BOOKING_HOST = os.getenv("BOOKING_HOST", "https://flightbookings.airnewzealand.com.tw")
DATE_STEP = int(os.getenv("DATE_STEP", "1"))  # 每隔幾天查一次出發日

RESULTS = Path("results")
DEBUG = Path("debug")
ISSUE_LABEL = "cheap-fare"

# TWD 金額：NT$ 12,345 / TWD 12,345 / NTD12345 / 12,345 TWD
PRICE_RE = re.compile(
    r"(?:NT\$|TWD|NTD)\s*([\d,]{4,})(?:\.\d+)?|([\d,]{4,})(?:\.\d+)?\s*(?:TWD|NTD|元)"
)


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
    if prices:
        result.update(status="ok", min_price=min(prices))
    else:
        blocked = re.search(r"access denied|blocked|captcha|robot", title + text[:2000], re.I)
        result.update(status="blocked" if blocked else "no_price", title=title)
        # 留存畫面供調整解析規則
        DEBUG.mkdir(exist_ok=True)
        page.screenshot(path=str(DEBUG / f"{tag}.png"), full_page=True)
        (DEBUG / f"{tag}.txt").write_text(text, encoding="utf-8")
        (DEBUG / f"{tag}.json.txt").write_text("\n\n".join(json_bodies), encoding="utf-8")
    return result


def run_search() -> list[dict]:
    pairs = []
    d = DEPART_START
    while d <= DEPART_END:
        pairs.append((d, d + dt.timedelta(days=TRIP_DAYS)))
        d += dt.timedelta(days=DATE_STEP)

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
            time.sleep(8)  # 放慢速度，避免被當成機器人
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
    user, pw, to = os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD"), os.getenv("NOTIFY_EMAIL")
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
        lines = [f"- 去 {r['depart']} / 回 {r['return']}：**NT${r['min_price']:,}** "
                 f"（[訂票頁]({r['url']})）" for r in cheap[:20]]
        body = (f"紐西蘭航空 {ORIGIN}⇄{DEST} {TRIP_DAYS} 天來回（{CABIN}，{ADULTS} 位成人）\n\n"
                + "\n".join(lines)
                + f"\n\n{summary}\n價格為爬取當下頁面上的最低顯示價，請點連結確認。"
                + f"\n<!-- best:{best} -->")
        notify(f"✈️ 紐航來回機票 NT${best:,}（低於 NT${THRESHOLD_TWD:,}）", body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
