# 紐航機票每日監控

每天台灣時間 06:00、18:00 左右由 GitHub Actions 到紐西蘭航空台灣訂票網站（flightbookings.airnewzealand.com.tw）查詢：

- 航線：台北 TPE ⇄ 皇后鎮 ZQN，經濟艙，每段最多轉機一次（例：TPE→AKL→ZQN）
- 乘客：2 位成人 + 1 位兒童（2～11 歲）
- 出發日：2027-01-01 ～ 2027-03-31；停留 14～20 天
- 每天早晚各寄一封 Gmail **報告**：今日最便宜 10 組、每個出發日的最低價
- 若 **三人含稅總價** < NT$100,000，日報主旨會加上「🔔 低於門檻！」

每組日期會在訂票頁把去程、回程各點選最便宜的經濟艙，再讀取頁首的「Total cost」
（全家含稅總價）。出發日 × 停留天數共約 630 組，同時開 6 個分頁查，每次約 20 分鐘；
一天兩次、每月約 1,300 分鐘，在 private repo 每月 2,000 分鐘的免費 Actions 額度內。

排程在 05:15、17:15 開始（GitHub 排程常會晚 10～20 分鐘），信件約在 06:00、18:00 寄達，
偶爾可能早幾分鐘或晚一點。
GitHub 忙碌時偶爾會整個略過排程，所以 05:45、17:45 另有備援排程：主排程有跑就自動跳過，
沒跑才補查，這時信件會晚約 30 分鐘。

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

### 4. 寄測試信確認
Actions → **Daily Air NZ fare check** → **Run workflow** → 勾選 **只寄一封測試信** → **Run workflow**，約 1 分鐘後應收到「測試信」。

### 5. 手動跑一次確認
repo 頁面 → **Actions** → 左側 **Daily Air NZ fare check** → 右側 **Run workflow** → **Run workflow**。
跑完（約 15 分鐘）會收到主旨為「✈️ 紐航日報 MM/DD：全家最低 NT$…」的信。
若信件跑到垃圾郵件，請標記「不是垃圾郵件」。

## 其他說明

- 報告每次都寄；查詢全部失敗時會寄「⚠️ 今天查詢失敗」。
- 低於門檻時另外在 repo 開 `cheap-fare` issue（同一價格只開一次，之後出現更低價才會再留言）。
- 想先快速測試，Run workflow 時在 `limit` 填 `3`，只查前 3 組（約 2 分鐘）。
- 如果整批查詢都抓不到價格（被網站擋或版面改了），workflow 會失敗，GitHub 會寄失敗通知；
  截圖與頁面文字放在該次執行的 artifact `fare-results/debug/` 裡。

## 調整條件

修改 `.github/workflows/daily.yml` 中 `Check fares` 步驟的 `env`：

| 變數 | 預設 | 說明 |
|---|---|---|
| `ORIGIN` / `DEST` | TPE / ZQN | 機場代碼（手動執行時可用 `dest` 輸入暫時改） |
| `MAX_FLIGHTS` | 2 | 每段最多搭幾班（2 = 最多轉機一次） |
| `DEPART_START` / `DEPART_END` | 2027-01-01 / 2027-03-31 | 出發日範圍 |
| `TRIP_DAYS_MIN` / `TRIP_DAYS_MAX` | 14 / 20 | 停留天數範圍 |
| `THRESHOLD_TWD` | 100000 | 全部乘客總價門檻 |
| `ADULTS` / `CHILDREN` | 2 / 1 | 成人、兒童人數 |
| `CABIN` | economy | economy / premiumeconomy / business |
| `ROTATE` | 1 | 幾次查完一輪（1 = 每次全查） |
| `WORKERS` | 6 | 同時查幾組 |

---

# 芬蘭／挪威機票每日監控

每天台灣時間 **中午 12:00 左右** 由 GitHub Actions（`.github/workflows/nordic.yml`）到 Google Flights 查詢，寄一封 Gmail 報告：

- 行程：一進一出（多個城市），兩種走法都查
  - A：台北 TPE → 赫爾辛基 HEL ……（自行陸路／渡輪）…… 奧斯陸 OSL → 台北
  - B：台北 TPE → 奧斯陸 OSL …… 赫爾辛基 HEL → 台北
- 出發日：2027-07-18 ～ 2027-08-10；整趟 16～21 天（最晚 8/31 回到台灣）
- 乘客：2 位成人 + 1 位兒童（2～11 歲），經濟艙，每段最多轉機 1 次
- **含託運行李**：Google Flights 這類行程只能篩手提行李，所以改用航空公司規定判斷——排除最便宜票種常不含託運行李的航空（芬航、KLM、法航、漢莎集團、SAS、英航等），只留長程經濟艙基本票就含託運行李的航空（土耳其、阿聯酋、卡達、長榮、華航、國泰等）。訂票時仍請確認票種的行李額度
- **只看傳統航空**：去程、回程都排除廉價航空（Norwegian、Scoot、AirAsia、Jetstar、VietJet 等）
- 每組日期先選去程最便宜的傳統航空班次，再選回程最便宜的，讀取全家含稅總價
- 共 288 組（24 個出發日 × 6 種天數 × 2 種走法），每次約 25 分鐘；排程 11:15 開始，11:45 有備援

信件內容：今日最便宜 10 組、兩種走法各自最低、每個出發日的最低價、與昨天／歷史最低比較。
出現以下情況時，主旨會加上「🔥特別推薦！」，信件開頭列出那一組：

- 全家總價低於 NT$85,000（`THRESHOLD_TWD`），或
- 比之前查到的歷史最低價還便宜

每天的最低價記錄在 repo 中標籤為 `nordic-history` 的 issue（自動更新，請勿關閉）。

Gmail 設定與紐航共用（`SMTP_USER`、`SMTP_PASSWORD`、`NOTIFY_EMAIL`），不用另外設定。
手動測試：Actions → **Daily Finland/Norway fare check** → **Run workflow**（`limit` 填 `6` 可快速試跑；勾選「只寄一封測試信」可測 Gmail）。

> Google Flights 約只開放 11 個月內的航班；8 月底回程的日期若還沒開放，會先算在「沒有符合條件的班次」，開放後自動納入。

修改 `check_nordic.py` 開頭或在 workflow 加 `env` 調整：

| 變數 | 預設 | 說明 |
|---|---|---|
| `FINLAND_AIRPORT` / `NORWAY_AIRPORT` | HEL / OSL | 例如改成羅瓦涅米 RVN、特羅姆瑟 TOS |
| `DEPART_START` / `DEPART_END` | 2027-07-18 / 2027-08-10 | 出發日範圍 |
| `TRIP_DAYS_MIN` / `TRIP_DAYS_MAX` | 16 / 21 | 整趟天數 |
| `MAX_STOPS` | 1 | 每段最多轉機次數 |
| `REQUIRE_BAGS` | 1 | 0 = 不排除可能不含託運行李的航空 |
| `THRESHOLD_TWD` | 85000 | 全家總價低於此就特別推薦 |
| `WORKERS` | 6 | 同時查幾組 |
