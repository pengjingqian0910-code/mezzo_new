# 拆模組驗證工具（refactor_check）

把 `main.py` 拆成模組時，用來確認「拆分前後行為完全一致」的工具與流程。
所有檢查都是**比對**：基準 commit（預設 `HEAD`）跟目前工作區各複製一份到暫存目錄，同一個測試兩邊各跑一次，結果必須相同。

## 一次跑完

在 repo 任何位置執行（建議兩種 Python 都給：venv 沒裝 aiortc → WebRTC 停用；系統 Python 有裝 → WebRTC 啟用）：

```bash
python mezzo_web_system/tools/refactor_check/run_checks.py \
    --python C:/Users/yunchen/work/mezzo_new/mezzo/Scripts/python.exe \
    --python C:/Users/yunchen/AppData/Local/Programs/Python/Python311/python.exe \
    --live http://localhost:8000
```

| 參數 | 說明 |
|---|---|
| `--base REF` | 比對基準，預設 `HEAD`（上一個 commit） |
| `--python PATH` | 每個 Python 各跑一輪，可重複 |
| `--live URL` | 對正在跑的伺服器發 GET（只讀） |
| `--db PATH` | 真實資料測試用的資料庫，預設 `mezzo_web_system/mezzo.db`（只讀，先複製一份） |
| `--keep` | 保留暫存目錄（除錯用） |

需要：`--python` 裡至少一個裝了 `pyflakes`（檢查 3）、一個裝了 `playwright` + Chromium（檢查 9）。
目前兩者都裝在 `mezzo/` venv。兩種 Python 都跑，整輪大約 7–8 分鐘。

結果代號：`PASS` 與基準相同、`CHANGED` 行為有變（只有預期中的修正可以接受，要看差異）、
`REVIEW` 需要人工確認、`SKIP` 沒跑到、`FAIL` 有問題。

## 拆模組流程

### 一、動手前：調查範圍，有疑問先問
1. 列出要從 main.py 搬走的範圍（行號、內容）。
2. 檢查陷阱：
   - 用 `global` 修改的變數：搬走後 main.py 會讀不到更新後的值（例如 STT 的 `STT_AVAILABLE`）。
   - 選裝套件的 `try/except`：沒裝時名稱不存在，`from xxx import` 會出錯（例如 WebRTC）。
   - 對共用物件做註冊／修改的程式：`python main.py`（reload 模式）會讓 main.py **執行兩次**，這類程式要放進被 import 的模組（例如 `init_models`）。
   - 其他檔案有沒有 `import main`；名稱在 main.py 其他地方的使用次數與位置。
3. 有任何要決定的地方，先問，等回覆。

### 二、拆分
4. 用腳本照行號搬移，先 assert 邊界，**逐字搬移，不手抄**。
5. **不刪除**：判斷用不到的程式碼改成註解並寫原因；被修改的原始行用註解保留。
6. 新模組開頭寫說明（內容、刻意留在 main.py 的東西與原因、不 import main）。

### 三、驗證：`run_checks.py`（基準 = 上一個 commit，兩種 Python 都跑）

| # | 檢查 | 腳本 |
|---|---|---|
| 0 | 函式／類別搬移與修改（AST 比對） | run_checks.py 內建 |
| 1 | 路由與資料表快照（路徑、方法、參數、依賴、欄位） | `snapshot.py` |
| 2 | TestClient 打 API | `smoke.py` |
| 3 | pyflakes：不能新增 undefined name | run_checks.py 內建 |
| 4 | `python main.py` 實際啟動：打 API、比對啟動日誌 | `launch_check.py` |
| 5 | 設定值（預設、自訂 `.env`＋環境變數） | `config_values.py` |
| 5 | MQTT 訊息處理（GPS／SOS／PTT、TAK 轉送、語音佇列） | `mqtt_flow.py` |
| 5 | WebSocket（map-data／ptt／v1 語音）＋ v1 API／JWT | `ws_v1.py` |
| 5 | 警戒區：完整流程、WhatsApp 通知、刪除隔離、id 重用回歸 | `geofence_*.py` |
| 5 | 真實資料庫複本（只印狀態碼／筆數／雜湊） | `realdb.py` |
| 6 | 前端呼叫的 API 路徑後端都有路由 | `frontend_routes.py` |
| 7 | `git diff --check` 與 diff 範圍 | run_checks.py 內建 |
| 8 | 正在跑的伺服器（`--live`，只 GET） | run_checks.py 內建 |
| 9 | 瀏覽器：首頁、登入、9 個分頁的 JS 錯誤／請求失敗 | `browser_check.py` |
| 10 | 同一個檔案沒有被載入成兩個模組（例如 `database` 與 `core.database`） | `module_identity.py` |

檢查 0、3 會掃 app 裡所有 `.py`（含 `core/`、`features/` 等子資料夾），不含 `tools/`、`static/`、`js/` 與「拷貝」備份檔。

另外每次拆分要人工確認：搬移的**模組層級**程式（import、變數、設定）用 `git diff` 逐字比對（檢查 0 只比函式／類別）。

### 四、回報與提交
7. 回報：改了什麼、驗證結果、可以檢查的地方；發現的問題**只回報，不擅自修改**。
8. 使用者在瀏覽器實際操作確認。
9. 推送前**完整重跑一次** `run_checks.py`。
10. 使用者說推，才 commit 並推到 `refactor/restructure-main`（**不碰 main**）；commit 訊息附驗證摘要。
11. 誠實說明沒驗證到的部分。

## 安全性

- **`_guard.py`**：測試腳本一開始就 import，擋下所有對外連線（socket、UDP、asyncio、aiohttp、urllib、DNS），只放行 127.0.0.1。
  觸發 TAK 推送、WhatsApp、NVR 等功能時不會真的送出封包，被擋下的目的地會印在輸出裡。
  （例：`mqtt_flow.py` 測 GPS 時會觸發 TAK 轉送，沒擋的話同一個區網裡的 ATAK 裝置會收到測試用的假座標）
  - **只影響有 `import _guard` 的測試腳本**。`main.py` 與其他模組沒有用到它；`python main.py`、Docker 部署、
    瀏覽器操作都不經過它；檢查 4（實際啟動）與檢查 9（瀏覽器）啟動的伺服器也沒有用它。
  - 被擋的連線表現得跟「連不上」一樣，拆分前後兩邊相同，不會造成比對誤判。
  - **新增測試時：如果那支測試需要真的連到外部（例如測真實 NVR），就不要 import `_guard`**，否則一定連不上。
- **檢查 4（實際啟動）** 照常連線 MQTT broker（跟平常啟動一樣），資料只寫進暫存複本的資料庫。
- **檢查 9（瀏覽器）** 啟動伺服器時把 NVR／MQTT 指到 127.0.0.1，不會碰到實際設備。外部 CDN（Vue、Cesium）照常從網路載入。
- **真實資料**：用 sqlite backup API 以唯讀方式複製，不改原檔；輸出只有雜湊，不印資料內容。

## 注意

- 測試透過 `main.xxx` 存取內部狀態（`fastapi_loop`、`devices_state`、`manager`…）。之後拆模組時，如果這些名稱搬走了，
  輸出會跟基準不同（標成 CHANGED／FAIL）。這時要判斷是行為改變，還是測試需要跟著更新；**測試更新要另外一個 commit**，不要跟拆分混在一起。
- 不涵蓋：瀏覽器裡的人工操作細節（畫面是否正確、地圖互動）、Docker 部署（`uvicorn main:app`，沒有 reload）、
  需要實體設備的功能（NVR 影像、真實 MQTT 裝置）。
