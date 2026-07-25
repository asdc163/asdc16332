# 幣安廣場內容生產線

一條全自動的內容管線：每天依排程抓幣安公開行情、產出繁體中文貼文與配圖，
再透過**幣安廣場官方 Creator OpenAPI** 直接發布。
附一張成長追蹤表，用來看「每週 200U + 破萬粉」卡在漏斗哪一層。

## 設定（三步）

1. 到 [廣場創作者中心](https://www.binance.com/square/creator-center/home) 建立 OpenAPI 金鑰。
2. 在這個倉庫 Settings → Secrets and variables → Actions 新增 secret：
   名稱 `BINANCE_SQUARE_OPENAPI_KEY`，值就是那把金鑰。
3. 把這條分支合併進 `main`。**GitHub 的排程只在預設分支觸發**，沒合併不會跑。

沒設定 secret 時管線仍會正常產內容，只是不發布——金鑰就位前不會壞掉。

> 金鑰只能發文，碰不到資產與交易。萬一外洩，最壞情況是有人冒名發文，
> 到創作者中心重新產生一把就會讓舊的失效。金鑰只透過環境變數傳遞，
> 不進版控、不進指令參數（指令參數會出現在 process list 和 shell history）。

## 快速開始

```bash
pip install -r requirements.txt

python -m square generate --offline   # 用示意資料測版面，不連網
python -m square generate             # 抓即時行情，產出今天該發的貼文
python -m square publish --dry-run    # 印出將送出的內容，不真的發
python -m square publish              # 實際發布（需要金鑰）
python -m square generate --publish   # 產生 + 發布，一步到位
python -m square topics               # 看教育課綱與今天輪到第幾篇
python -m square status               # 看目標進度與漏斗診斷
python -m square review               # 產生每週檢視報告
```

## 排程總覽

| workflow | 何時 | 做什麼 |
|---|---|---|
| `square-content.yml` | 每天四個時段 | 產內容 → 發布 → 提交帳本 |
| `weekly-review.yml` | 週日 21:30 | 開檢視 issue，附報告與數據回報樣板 |
| `metrics-intake.yml` | 你回覆 issue 時 | 解析數字 → 寫進追蹤表 → 回覆確認 |
| `ci.yml` | 每次推送 | 跑測試，確認管線沒被推壞 |

產出會落在 `out/YYYY-MM-DD/`，每篇一個 `.md`（含 YAML front matter）加一張 `.png`。

## 發布是冪等的

排程會重跑——手動觸發、失敗重試、GitHub 偶發的重複派送。
`data/published.json` 是發布帳本，以「日期/slug」為鍵，發過的一律跳過。
幾個刻意的設計：

- 帳本會跟著產出一起 commit 回倉庫，**否則下次排程會重發同一篇**。
- 提交步驟是 `if: always()`，就算發布中途失敗，已發出去的部分也會記帳。
- `/content/add` 回 504 代表**已送達但沒回 id**，視為成功並記帳。
  當成失敗重送會發出兩篇——這是官方 skill 明確標注的行為。
- 業務錯誤（金鑰失效、超過每日上限）不重試，只有網路層失敗才重試。
- 帳本檔案損毀時直接中止，不會當成空帳本重發一輪。

## 每天你要做的事

沒有。管線自己產、自己發、自己記帳。

**每週要做的事只有一件：回一則留言。**
每週日 21:30 系統會自動開一則「每週檢視」issue，裡面有發布健康度、漏斗轉換率、
以及依數據算出來的下一步。唯一需要你的地方是五個數字——
廣場沒有開放統計 API，粉絲數與曝光只能從後台抄。

直接在那則 issue 底下回覆就好，寫法很寬鬆：

```
followers: 1250
impressions: 8400
clicks: 96
signups: 4
commission: 23.5
```

或者中文自由書寫也行：`這週粉絲數 1250，曝光 8,400，進個人頁 96 次，註冊 4 個，返佣 23.5 USDT`。
系統會解析、寫進 `data/tracking.csv`、回覆確認。
順序不拘、少填幾項也可以，沒填的欄位不會被當成 0 猜進去。

（`posts_published` 由發布流程自動記入，不用手填。）

## 每週檢視在看什麼

`python -m square review` 也可以隨時手動跑。報告分兩塊，性質不同所以分開講：

**發布健康度**（全自動，來自 `data/published.json`）
對帳「這週應該發 14 篇、實際發了幾篇」，列出漏發的日期與型別。
內容再好沒發出去都是零，所以這一項排在最前面——管線壞掉時，
報告的第一條建議一定是先修管線，不會跳過去談優化。

**成長漏斗**（需要你回報）
曝光 → 進個人頁 → 推薦註冊 → 返佣，每層算轉換率，
然後指出**最弱的那一環**並給出具體動作。判斷邏輯大致是：

| 症狀 | 診斷 | 動作 |
|---|---|---|
| 每篇曝光 < 300 | 觸及不足 | 熱門標籤、留言互動、固定發文時間 |
| 曝光→點擊 < 1% | 鉤子不夠 | 貼文結尾放續集預告、改寫個人簡介 |
| 有點擊、0 註冊 | 動線斷了 | 連結要放個人簡介與置頂，不能只埋在貼文結尾 |
| 點擊→註冊 < 2% | CTA 太模糊 | 給具體理由、減少帶連結的貼文比例 |
| 粉絲零成長 | 題材不對 | 拉高教育系列比重、壓低行情快報 |

沒有數據時報告會直說「無法診斷」並要求補數字，**不會拿沒有的數字硬湊結論**。

## 用到的幣安 API

發布走官方 Creator OpenAPI，契約來自幣安開源的
[square-post skill](https://github.com/binance/binance-skills-hub/tree/main/skills/binance/square-post)：

| 用途 | 端點 |
|---|---|
| 取得圖片預簽名網址 | `POST {v2}/image/presignedUrl` → `{presignedUrl, fileTicket}` |
| 上傳圖片 | `PUT` 該預簽名網址 |
| 輪詢圖片處理狀態 | `POST {v2}/image/imageStatus` → `status` 1=完成 2=失敗 |
| 發布內容 | `POST {v1}/content/add` |

標頭 `X-Square-OpenAPI-Key` / `clienttype: binanceSkill`，成功碼 `000000`。
`contentType` 1＝短貼文（正文＋最多 4 張圖），2＝長文（標題＋單張封面）。
每日上限 100 篇貼文、400 次上傳；我們一週 14 篇，用不到 2%。

行情資料另外走**免金鑰**的公開端點（`api.binance.com/api/v3/*`、
`fapi.binance.com/fapi/v1/premiumIndex`），與廣場金鑰無關。

## 排程

`.github/workflows/square-content.yml`，時間為台北時間：

| 時間 | 頻率 | 型別 | 內容 |
|---|---|---|---|
| 08:00 | 每天 | `morning_brief` | 觀察名單行情、24h 高低、情緒指數，含 48 小時走勢圖卡 |
| 12:30 | 一 / 三 / 五 | `education` | 教育系列，依 `square/topics.py` 的課綱輪替 |
| 21:00 | 二 / 四 / 六 | `data_watch` | 漲跌幅榜（已濾低流動性）、資金費率 |
| 20:00 | 週日 | `weekly` | 一週回顧、本週講過的主題 |

一週 14 篇（早報 7 + 教育 3 + 數據 3 + 週報 1）。要調整就改 workflow 裡的 cron 與 `square/compose.py` 的 `kinds_for()`。

> **兩個 GitHub 的坑**
> 1. 排程只在**預設分支**上觸發。這個 workflow 合併進 `main` 之前不會自己跑。
> 2. 倉庫連續 60 天沒有活動，GitHub 會自動停用排程。管線每天都會 commit，正常情況下不會踩到。

手動觸發：Actions → 幣安廣場內容生產線 → Run workflow，
可指定型別、勾選離線模式（測版面）或乾跑（產內容但不發布）。
**第一次啟用建議先跑一次乾跑**，確認文案與圖卡沒問題再讓它自動發。

## 內容規則

寫在模板裡的硬性限制，`tests/test_pipeline.py` 會擋：

- 只描述已發生的數據與機制知識，**不預測價格、不給進出場建議**。
- 每篇強制附免責聲明。
- 推薦連結只出現在教育與週報貼文（`config.yaml` 的 `brand.referral_on`）。
  每篇都塞連結會被讀者和演算法一起判定為推廣帳號。
- 承諾報酬、喊單類措辭一律禁止，測試會失敗。

## 追蹤表怎麼用

`data/tracking.csv`。粉絲數只是結果，要知道該改什麼得看整條漏斗：

```
曝光 → 進個人頁 → 點推薦連結 → 註冊 → 入金交易 → 返佣
```

`python -m square status` 會算出每一層的轉換率，並指出最弱的一環——
是曝光不夠（該加強觸及）、還是有曝光沒人追蹤（內容鉤子不夠）、
還是有人追蹤但不點連結（CTA 動線有問題）。三種情況的解法完全不同。

數字得你自己從廣場後台與推薦儀表板抄過來，沒有 API 可以自動抓。

## 專案結構

```
square/
  config.py     設定載入、時區
  market.py     幣安公開行情（含離線示意資料）
  topics.py     教育課綱，32 篇，一週三篇約 11 週不重複
  compose.py    四種貼文的文案生成與排程規則
  imagegen.py   PIL 配圖，四種版型，不需要任何外部繪圖 API
  publisher.py  廣場 Creator OpenAPI 客戶端（圖片上傳 + 發文）
  ledger.py     發布帳本，防止重複發文
  review.py     每週檢視：發布對帳、漏斗分析、策略建議
  intake.py     從 issue 留言解析成長數據
  tracker.py    成長追蹤與漏斗診斷
  cli.py        指令列進入點
tests/          煙霧測試、內容合規檢查、發布路徑測試、檢視邏輯測試
config.yaml     品牌、觀察名單、排程、目標
data/           追蹤表 + 發布帳本
out/            產出（由排程 commit）
```

`data/published.json` 是狀態，不是產物——**不要手動刪**。
刪掉會讓管線把當天的貼文再發一次。

## 要改內容？

- **換觀察標的**：`config.yaml` 的 `market.watchlist`。
- **加教育主題**：在 `square/topics.py` 的 `TOPICS` 追加一個 `Topic`。
  照著現有格式寫 3–5 個要點，`test_every_topic_renders_without_error` 會確認版面不會爆。
- **改圖卡配色 / 版型**：`square/imagegen.py` 最上面的常數與四個版型函式。
- **改發文頻率**：workflow 的 cron 加上 `compose.kinds_for()`，兩邊要一起改。
