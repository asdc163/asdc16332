# 幣安廣場內容生產線

一個排程跑的內容工廠：每天自動抓幣安公開行情、產出繁體中文貼文草稿與配圖，
你審過之後**手動**發布到幣安廣場。附一張成長追蹤表，用來看「每週 200U + 破萬粉」卡在漏斗哪一層。

---

## 先讀這段：這個專案不做什麼

**不自動發文。** 幣安沒有公開的廣場發文 API（官方 API 只涵蓋交易與行情）。
要自動發文只剩兩條路：逆向 App 的內部端點，或用瀏覽器自動化登入你的帳號代發。
兩者都違反幣安使用條款，被判定為自動化操作的後果是連交易帳戶一起被限制。
為了省下每天 10 分鐘的貼文動作，賠上整個帳號不划算，所以這條線停在「產好草稿」。

**不碰你的 API 金鑰。** 這個專案用到的全部是免金鑰的公開行情端點。
倉庫裡沒有、也不需要任何密鑰。如果你曾經在任何地方貼出過金鑰，
請到幣安 API Management 立刻刪除並重建，並確認舊金鑰沒有開啟提幣權限。

**不保證收益。** 200U/週取決於推薦人的實際交易量，不取決於發文腳本。
這個工具能保證的只有一件事：內容的產出頻率與品質不再依賴你的心情。

---

## 快速開始

```bash
pip install -r requirements.txt

python -m square generate --offline   # 用示意資料測版面，不連網
python -m square generate             # 抓即時行情，產出今天該發的貼文
python -m square preview --kind education   # 只印文案不存檔
python -m square topics               # 看教育課綱與今天輪到第幾篇
python -m square status               # 看目標進度與漏斗診斷
```

產出會落在 `out/YYYY-MM-DD/`，每篇一個 `.md`（含 YAML front matter）加一張 `.png`。

## 每天的實際流程

1. 排程跑完後，到 Actions 的執行摘要頁直接讀文案，或在倉庫的 `out/` 看當天資料夾。
2. 掃一眼數字對不對、語氣要不要調。**這一步不要跳過**——你的帳號，你負責。
3. 複製文案、下載配圖，發到幣安廣場。
4. 每天（或每週）把後台數字記一筆：

```bash
python -m square track --followers 1250 --posts 3 --impressions 8400 \
       --clicks 96 --signups 4 --commission 23.5
```

## 排程

`.github/workflows/square-content.yml`，時間為台北時間：

| 時間 | 頻率 | 型別 | 內容 |
|---|---|---|---|
| 08:00 | 每天 | `morning_brief` | 觀察名單行情、24h 高低、情緒指數，含 48 小時走勢圖卡 |
| 12:30 | 一 / 三 / 五 | `education` | 教育系列，依 `square/topics.py` 的課綱輪替 |
| 21:00 | 二 / 四 / 六 | `data_watch` | 漲跌幅榜（已濾低流動性）、資金費率 |
| 20:00 | 週日 | `weekly` | 一週回顧、本週講過的主題 |

一週 11 篇。要調整就改 workflow 裡的 cron 與 `square/compose.py` 的 `kinds_for()`。

> **兩個 GitHub 的坑**
> 1. 排程只在**預設分支**上觸發。這個 workflow 合併進 `main` 之前不會自己跑。
> 2. 倉庫連續 60 天沒有活動，GitHub 會自動停用排程。生產線每天都會 commit 產出，正常情況下不會踩到。

手動觸發：Actions → 幣安廣場內容生產線 → Run workflow，可指定型別或勾選離線模式。

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
  imagegen.py   PIL 配圖，四種版型，不需要任何外部 API
  tracker.py    成長追蹤與漏斗診斷
  cli.py        指令列進入點
tests/          煙霧測試 + 內容合規檢查
config.yaml     品牌、觀察名單、排程、目標
data/           追蹤表
out/            產出（由排程 commit）
```

## 要改內容？

- **換觀察標的**：`config.yaml` 的 `market.watchlist`。
- **加教育主題**：在 `square/topics.py` 的 `TOPICS` 追加一個 `Topic`。
  照著現有格式寫 3–5 個要點，`test_every_topic_renders_without_error` 會確認版面不會爆。
- **改圖卡配色 / 版型**：`square/imagegen.py` 最上面的常數與四個版型函式。
- **改發文頻率**：workflow 的 cron 加上 `compose.kinds_for()`，兩邊要一起改。
