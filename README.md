# 紐航機票每日監控

每天台灣時間 08:00 由 GitHub Actions 到紐西蘭航空台灣訂票網站（flightbookings.airnewzealand.com.tw）查詢：

- 航線：台北 TPE ⇄ 奧克蘭 AKL
- 出發日：2027-02-20 ～ 2027-03-31（每天一組），回程 = 出發 + 14 天
- 若最低票價 < NT$100,000 → 通知

## 通知方式

1. **GitHub Issue（預設，免設定）**：開一個 `cheap-fare` issue／留言，GitHub 會寄信給你（請確認有 Watch 此 repo）。
   只有在出現「比之前通知過更低」的價格時才會再通知，不會每天重複。
2. **Email（選用）**：在 repo Settings → Secrets and variables → Actions 新增
   `SMTP_USER`（Gmail 帳號）、`SMTP_PASSWORD`（Gmail 應用程式密碼）、`NOTIFY_EMAIL`（收件信箱）。
3. **Telegram（選用）**：新增 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`。

如果整批查詢都抓不到價格（被網站擋或版面改了），workflow 會失敗，GitHub 會寄失敗通知；
截圖與頁面文字放在該次執行的 artifact `fare-results/debug/` 裡。

## 調整條件

修改 `.github/workflows/daily.yml` 中 `Check fares` 步驟的 `env`：

| 變數 | 預設 | 說明 |
|---|---|---|
| `ORIGIN` / `DEST` | TPE / AKL | 機場代碼 |
| `DEPART_START` / `DEPART_END` | 2027-02-20 / 2027-03-31 | 出發日範圍 |
| `TRIP_DAYS` | 14 | 來回天數 |
| `THRESHOLD_TWD` | 100000 | 通知門檻 |
| `ADULTS` | 1 | 成人數 |
| `CABIN` | economy | economy / premiumeconomy / business |
| `DATE_STEP` | 1 | 每隔幾天查一個出發日 |

手動執行：Actions → Daily Air NZ fare check → Run workflow。
