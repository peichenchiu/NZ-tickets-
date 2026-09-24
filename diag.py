"""臨時診斷：觀察點選票價後頁面的變化（確認後會刪除）。"""
import datetime as dt
import re

from playwright.sync_api import sync_playwright

import check_fares as c

PRICE = re.compile(r"^\s*\$[\d,]+\s*$")


def dump(page, label):
    text = page.inner_text("body")
    i = text.find("Total cost")
    print(f"==== {label}: total area ====\n{text[max(0, i - 50):i + 120]}")
    dialogs = page.locator("[role=dialog], .modal, [aria-modal=true]")
    for k in range(min(dialogs.count(), 3)):
        if dialogs.nth(k).is_visible():
            print(f"==== {label}: dialog {k} ====\n{dialogs.nth(k).inner_text()[:2500]}")


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_context(locale="zh-TW", viewport={"width": 1366, "height": 900}).new_page()
    page.goto(c.search_url(dt.date(2027, 2, 21), dt.date(2027, 3, 8)), timeout=90_000)
    page.wait_for_load_state("networkidle", timeout=60_000)
    prices = page.get_by_text(PRICE)
    print("price elements:", prices.count())
    first = prices.first
    print("==== outerHTML chain ====")
    print(first.evaluate("""e => { let out = []; let n = e;
        for (let i = 0; i < 5 && n; i++, n = n.parentElement) out.push(n.outerHTML.slice(0, 700));
        return out.join('\\n---\\n'); }"""))
    first.click()
    page.wait_for_timeout(4000)
    dump(page, "after outbound click")
    body = page.inner_text("body")
    j = body.find("Select your flight to Auckland")
    print("==== body after click (outbound area) ====\n" + body[j:j + 2500])
    buttons = page.locator("button:visible")
    print("==== visible buttons ====")
    print([t.strip()[:40] for t in buttons.all_inner_texts()][:80])
    b.close()
