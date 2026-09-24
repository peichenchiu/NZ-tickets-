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
BOOKING_HOST = os.getenv("BOOKING_HOST", "https://flightbookings.airnewzealand.com.tw")
# 每天只查 1/ROTATE 的出發日並輪替（省 Actions 分鐘數用）；1 = 每天全查（約 280 組、50 分鐘）
ROTATE = int(os.getenv("ROTATE", "1"))
LIMIT = int(os.getenv("LIMIT") or "0")  # 只查前幾組（診斷用），0 = 不限

RESULTS = Path("results")
DEBUG = Path("debug")
ISSUE_LABEL = "cheap-fare"

# 選票頁每個票價格子：經濟艙是 data-automation="leg-option-cost-le"
FARE_CELL = '[data-automation="leg-option-cost-le"].vui-si-cost-available'
# 頁首「Total cost / TWD $56,009.00」：已選航段的全體乘客含稅總價
TOTAL_RE = re.compile(r"Total cost\s*TWD\s*\$([\d,]+)")
# 標出每個票價格子屬於去程(0)或回程(1)，並回傳其價格
MARK_CELLS_JS = """sel => {
  const ret = [...document.querySelectorAll('h1,h2,h3,h4,div,span')]
    .find(e => e.children.length === 0 && /Select your return flight/.test(e.textContent));
  return [...document.querySelectorAll(sel)].map((e, i) => {
    const leg = ret && (ret.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING) ? 1 : 0;
    const m = e.innerText.match(/\\$\\s*([\\d,]+)/);
    e.setAttribute('data-nz-idx', i);
    return {idx: i, leg, price: m ? parseInt(m[1].replace(/,/g, '')) : null};
  });
}"""


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


def read_total(page) -> int | None:
    m = TOTAL_RE.search(page.inner_text("body"))
    return int(m.group(1).replace(",", "")) if m else None


def wait_total_change(page, before: int | None) -> int | None:
    for _ in range(30):
        page.wait_for_timeout(500)
        now = read_total(page)
        if now and now != before:
            return now
    return read_total(page)


def check_one(page, depart: dt.date, ret: dt.date) -> dict:
    """點選去程、回程各自最便宜的經濟艙票價，讀取頁首的全家含稅總價。"""
    url = search_url(depart, ret)
    result = {"depart": depart.isoformat(), "return": ret.isoformat(), "url": url}
    tag = f"{depart.isoformat()}_{ret.isoformat()}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        try:
            page.wait_for_selector(FARE_CELL, timeout=60_000)
        except Exception:
            pass
        cells = page.evaluate(MARK_CELLS_JS, FARE_CELL)
        legs = {leg: [c for c in cells if c["leg"] == leg and c["price"]] for leg in (0, 1)}
        if not legs[0] or not legs[1]:
            text = page.inner_text("body")
            blocked = re.search(r"access denied|blocked|captcha|robot", page.title() + text[:2000], re.I)
            no_flights = re.search(r"no flights|not available|沒有航班", text, re.I)
            result.update(status="blocked" if blocked else "no_flights" if no_flights else "no_price",
                          title=page.title(), cells=len(cells))
            DEBUG.mkdir(exist_ok=True)
            page.screenshot(path=str(DEBUG / f"{tag}.png"), full_page=True)
            (DEBUG / f"{tag}.txt").write_text(text, encoding="utf-8")
            return result

        total = read_total(page)
        chosen = []
        for leg in (0, 1):
            cheapest = min(legs[leg], key=lambda c: c["price"])
            chosen.append(cheapest["price"])
            page.locator(f'[data-nz-idx="{cheapest["idx"]}"]').click()
            total = wait_total_change(page, total)
        if not total:
            raise RuntimeError("讀不到 Total cost")
        result.update(status="ok", min_price=total,
                      out_fare=chosen[0], ret_fare=chosen[1])
    except Exception as e:
        result.update(status="error", error=str(e)[:300])
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
    return (f"- 去 {r['depart']} / 回 {r['return']}（{days} 天）：全家含稅 NT${r['min_price']:,}"
            f"（成人單程票價 去 {r['out_fare']:,} / 回 {r['ret_fare']:,}）\n  {r['url']}")


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
                + f"\n\n{summary}\n價格為去程、回程各選最便宜經濟艙後，訂票頁顯示的全家含稅總價（Total cost），實際以訂票頁為準。"
                + f"\n<!-- best:{best} -->")
        notify(f"✈️ 紐航來回機票 {ADULTS + CHILDREN} 人 NT${best:,}（低於 NT${THRESHOLD_TWD:,}）", body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
