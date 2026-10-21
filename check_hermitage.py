"""隱士飯店（Hermitage Aoraki/Mt Cook）每日空房監控。

第一階段：診斷模式（MODE=diag）——只開官網、嘗試操作日期欄位，
把畫面、HTML、網路請求存到 debug/，用來確認 GitHub 機器沒被 Cloudflare 擋、
並找出訂房系統的實際流程。確認後再補上正式查房（MODE=check）。
"""
import asyncio
import json
import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

from playwright.async_api import async_playwright

ARRIVE = "2027-02-17"
DEPART = "2027-02-20"
ADULTS, CHILDREN, CHILD_AGE = 2, 1, 6
START_URL = "https://www.hermitage.co.nz/stay/hermitage-hotel"
DEBUG = Path("debug")
DEBUG.mkdir(exist_ok=True)
MODE = os.getenv("MODE") or "diag"


def notify_email(subject: str, body: str) -> None:
    user, pw = os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD")
    to = os.getenv("HERMITAGE_NOTIFY_EMAIL") or "forclaude.peichen@gmail.com"
    if not (user and pw and to):
        print("沒有設定 SMTP，略過寄信", file=sys.stderr)
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.send_message(msg)


async def snap(page, name: str) -> None:
    try:
        await page.screenshot(path=str(DEBUG / f"{name}.png"), full_page=False, timeout=15000)
    except Exception as e:  # noqa: BLE001
        print(f"screenshot {name} failed: {e}")


async def diag() -> int:
    net: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            locale="en-NZ",
            timezone_id="Pacific/Auckland",
            viewport={"width": 1366, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"),
        )
        page = await ctx.new_page()
        page.on("request", lambda r: net.append(f"REQ {r.method} {r.url}"))
        page.on("response", lambda r: net.append(f"RES {r.status} {r.url}"))
        page.on("framenavigated", lambda f: net.append(f"NAV {f.url}"))
        resp = await page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
        print("status:", resp.status if resp else None, "title:", await page.title())
        await page.wait_for_timeout(6000)
        await snap(page, "01_loaded")
        (DEBUG / "01_title.txt").write_text(await page.title(), encoding="utf-8")

        # cookie 視窗：選最保守（拒絕非必要）
        for label in ("Reject", "Decline", "Necessary", "Only necessary"):
            btn = page.get_by_role("button", name=label)
            if await btn.count():
                await btn.first.click()
                break

        # 試著點開入住日期欄位
        field = page.get_by_text("Arrival Date").first
        try:
            await field.scroll_into_view_if_needed(timeout=10000)
            await field.click(timeout=10000)
            await page.wait_for_timeout(1500)
            await snap(page, "02_after_arrival_click")
        except Exception as e:  # noqa: BLE001
            print("arrival click failed:", e)

        html = await page.content()
        (DEBUG / "page.html").write_text(html, encoding="utf-8")
        # 找出日曆相關元素與表單輸入
        info = await page.evaluate(
            """() => ({
              inputs: [...document.querySelectorAll('input,select,button')].slice(0,80).map(e => ({
                tag: e.tagName, type: e.type, name: e.name, id: e.id, cls: e.className,
                ph: e.placeholder, text: (e.innerText||'').slice(0,40), ro: e.readOnly})),
              calendars: [...document.querySelectorAll('[class*=calendar],[class*=datepicker],[class*=picker],[id*=calendar]')]
                .slice(0,10).map(e => ({tag: e.tagName, cls: e.className, id: e.id,
                   vis: !!(e.offsetWidth||e.offsetHeight), html: e.outerHTML.slice(0,600)})),
              iframes: [...document.querySelectorAll('iframe')].map(f => f.src),
              forms: [...document.forms].map(f => ({action: f.action, method: f.method, id: f.id}))
            })"""
        )
        (DEBUG / "dom_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")

        # 用 JS 直接讀頁面內嵌的 Vue 應用狀態（若有）
        try:
            snippet = await page.evaluate(
                "() => { const s=[...document.scripts].map(x=>x.src||x.textContent.slice(0,300)); return s; }"
            )
            (DEBUG / "scripts.json").write_text(json.dumps(snippet, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            print("scripts dump failed:", e)

        (DEBUG / "network.txt").write_text("\n".join(net), encoding="utf-8")
        await browser.close()
    print("診斷完成，結果在 debug/")
    return 0


def main() -> int:
    if os.getenv("TEST_EMAIL") == "true":
        if not (os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD")):
            print("沒有設定 SMTP_USER / SMTP_PASSWORD", file=sys.stderr)
            return 1
        notify_email("🏔️ 隱士飯店空房監控：測試信",
                     f"這是測試信。收到代表通知設定成功。\n監控：{ARRIVE} ～ {DEPART}，"
                     f"{ADULTS} 大人 {CHILDREN} 小孩（{CHILD_AGE} 歲）。")
        print("測試信已寄出")
        return 0
    if MODE == "diag":
        return asyncio.run(diag())
    print(f"尚未實作 MODE={MODE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
