# 紐航機票每日監控

每天台灣時間 08:00 由 GitHub Actions 到紐西蘭航空台灣訂票網站（flightbookings.airnewzealand.com.tw）查詢：

- 航線：台北 TPE ⇄ 奧克蘭 AKL，經濟艙
- 乘客：2 位成人 + 1 位兒童（2～11 歲）
- 出發日：2027-02-20 ～ 2027-03-31；停留 14～20 天
- 若 **三人總價** < NT$100,000 → 寄 Gmail 通知

出發日 × 停留天數共約 280 組。每天查其中 1/3（約 95 組、約 45 分鐘），
3 天內全部查過一輪，才不會超過 private repo 每月 2,000 分鐘的免費 Actions 額度。
（若把 repo 改成 public，Actions 不限分鐘，可把 `ROTATE` 改成 `1` 每天全查。）

## 設定 Gmail 通知

### 1. 開啟 Google 帳號兩步驟驗證
應用程式密碼需要先開兩步驟驗證。
到 <https://myaccount.google.com/security> →「兩步驟驗證」→ 依指示開啟。

### 2. 建立「應用程式密碼」
1. 開啟 <https://myaccount.google.com/apppasswords>（需重新登入）。
2. 應用程式名稱填 `nz-tickets`，按「建立」。
3. 畫面會顯示 16 個字母的密碼（例如 `abcd efgh ijkl mnop`），**複製起來**，關掉後就看不到了。
   貼上時空格可留可不留。

> 這不是你的 Gmail 登入密碼，只能拿來寄信，可隨時在同一頁刪除。

### 3. 把密碼存到 GitHub Secrets
1. 打開 repo 頁面 → **Settings** → 左側 **Secrets and variables** → **Actions**。
2. 按 **New repository secret**，新增以下兩個（Name 要一字不差）：

   | Name | Secret |
   |---|---|
   | `SMTP_USER` | 你的 Gmail 地址，例如 `xxx@gmail.com` |
   | `SMTP_PASSWORD` | 第 2 步的 16 碼應用程式密碼 |

3. （選用）想寄到別的信箱，再加 `NOTIFY_EMAIL`；沒設定就寄給 `SMTP_USER` 自己。

### 4. 手動跑一次確認
repo 頁面 → **Actions** → 左側 **Daily Air NZ fare check** → 右側 **Run workflow** → **Run workflow**。
跑完（約 45 分鐘）若有低於門檻的票，就會收到主旨為「✈️ 紐航來回機票 3 人 NT$…」的信。
若信件跑到垃圾郵件，請標記「不是垃圾郵件」。

## 其他說明

- 同一個價格只通知一次；之後要出現更低的價格才會再寄信。
  （已通知過的最低價記錄在 repo 的 `cheap-fare` issue 中，GitHub 也可能另外寄 issue 通知信。
  關閉該 issue 即可重置，下次符合條件就會重新通知。）
- 頁面上有「總計」金額時直接用總計；沒有的話以「頁面最低價 × 3 人」保守估算，信中會註明。
- 如果整批查詢都抓不到價格（被網站擋或版面改了），workflow 會失敗，GitHub 會寄失敗通知；
  截圖與頁面文字放在該次執行的 artifact `fare-results/debug/` 裡。

## 調整條件

修改 `.github/workflows/daily.yml` 中 `Check fares` 步驟的 `env`：

| 變數 | 預設 | 說明 |
|---|---|---|
| `ORIGIN` / `DEST` | TPE / AKL | 機場代碼 |
| `DEPART_START` / `DEPART_END` | 2027-02-20 / 2027-03-31 | 出發日範圍 |
| `TRIP_DAYS_MIN` / `TRIP_DAYS_MAX` | 14 / 20 | 停留天數範圍 |
| `THRESHOLD_TWD` | 100000 | 全部乘客總價門檻 |
| `ADULTS` / `CHILDREN` | 2 / 1 | 成人、兒童人數 |
| `CABIN` | economy | economy / premiumeconomy / business |
| `ROTATE` | 3 | 幾天查完一輪 |
