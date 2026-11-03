# White Cat Project JP - Character-Downloader

> White Cat Project (白貓 Project) JP 版 角色圖片及模型下載器

前言：

本專案由孤之界大佬的專案所改良
參考了以下資料

https://forum.gamer.com.tw/Co.php?bsn=26686&sn=759182

https://github.com/konnokai/WcatIndexDownload

https://github.com/konnokai/WcatCharacterDataDownload

https://github.com/konnokai/WcatIndexDownloadAndComparisonTool


AssetStudio使用的是這個的8.0版本

https://github.com/Razviar/assetstudio/releases/tag/v2.4.1

因使用起來無法達到效果，看了程式碼後發現整體概念不難重現，使用ChatGPT 5.2完成這項專案，所以code內的註解是爛的 看看就好

這個專案的目的只管能出圖，所以有些小細節沒有做出來

GUI也沒有做，因為我認為termnal夠我使用（後來還是補了一個 Web GUI，見 ⑥）

然後README.md也是GPT寫的，改了一下而已(X


本專案用於：

* 解析官方 AssetBundle
* 自動比對新舊角色 Index
* 產生角色 ID 清單
* 下載並解包角色圖片 / 語音 / Prefab(角色模型檔案)
* 自動整理輸出資料夾結構
* 產生 bust 圖片預覽列表

---

# 📁 專案結構

```
AssetStudio/                 ← 只需要 CLI 版本
gui/                         ← Web GUI 前端（⑥）
wcat_web_gui.py              ← Web GUI 伺服器（⑥）
啟動 Web GUI.bat              ← 雙擊開 GUI
config_diff.json             ← Index 比對設定
config_lister.json           ← card.txt 生成設定
config_unity3D.json          ← unity3d 解包設定
config_bust.json             ← bust gallery 設定
config_rig.json              ← 骨架動作匯出設定（⑤）
config_id_labels.json        ← 角色 ID 各位數名稱（GUI 篩選用）

! wcat/
index_work/
  ├── index_store/
  │    ├── now_Card.json
  │    ├── last_Card.json
  │    ├── new_Card.txt
  │    └── new_Card_character_ids.txt
  │
  ├── card_txt/
  │    └── card.txt
  │
  ├── bust_gallery/
  └── bust_work/

unity3d_downloads/            ← ④ 用，每次執行會清空
unity3d_exports/
rig_cache/                    ← ⑤ 用的 prefab / 動作快取（不會被 ④ 清掉）
```
---

# 📥 安裝方式

```bash
pip install -r requirements.txt
```

（requests、Pillow、UnityPy）
---

# ⚙ 系統需求

- Python 3.10+
- Windows (因為使用 AssetStudio CLI)

---

# 🧩 工具流程

整個流程分成四個階段（之後加了 ⑤ 骨架動作、⑥ Web GUI）：

---

# ① 角色 Index 比對

腳本：

```
wcat_0_角色資料創建.py      （設定：config_diff.json）
```

功能：

* 下載 `_Version_a_Card_txt.unity3d`
* 使用 AssetStudio CLI 抽出 TextAsset -> 獲得 Card.data
* 解析為 now_Card.json (這次獲得的)
* 與 last_Card.json 比對 (上次獲得的)
* 產生：

```
new_Card.txt (上次以及這次比對後的新Card)
new_Card_character_ids.txt (上面Card的ID檔案)
```

用途：

✔ 取得新角色 ID
✔ 知道哪些角色更新

---

# ② 產生 bust 圖片預覽清單

腳本：

```
wcat_0_創建資料轉圖片.py
```

設定檔：

```
config_lister.json
```

用途：

* 從 now_Card.json 抓出

  ```
  Card_1_bust_card_{ID}_1_png
  ```
* 下載 bust 圖 (半身圖，因為從AssetStudio轉出來的圖片大小會有問題，還得寫轉換，那不如用不用轉的)
* 解包
* 生成 bust_gallery
* 可選擇產生 HTML 圖庫

用途：

✔ 快速辨識角色
✔ 不用盲猜 ID
✔ 生成可視化 index


或是說 誰知道裡面有什麼 搞個圖片預覽解決問題不就好了 (在參考資料內的巴哈文章看到的想法)

---

# ③ 產生 card.txt

腳本：

```
1_wcat_1_角色ID List創建.py --id 20413550 10101930
```

功能：

從：

```
index_store/now_Card.json
```

獲取資料

產生：

```
card_txt/card.txt
```

用途：

生成需要抓取的資料名稱
供 unity3d 下載器使用

---

# ④ 下載並解包角色素材

腳本：

```
2_wcat_2_角色圖片下載及解包.py
```

注意：每次執行會先清空 `unity3d_downloads`。語音固定猜 55 個（config_lister.json 的 `voice_count`），角色實際沒那麼多時多出來的會顯示 HTTP 403，可以忽略。

功能：

* 讀取 `card.txt`
* 下載對應 unity3d
* 使用 AssetStudio CLI 解包
* 自動：

  * 修正圖片尺寸
  * 依角色 ID 整理資料夾
  * 整理語音 / Prefab

整理後結構：

```
unity3d_exports/
   ├── 10101930/
   │     ├── Card_2_full...
   │     ├── Sound_Voice_Player...
   │     └── Character_Prefabs...
```

---

# 🔧 AssetStudio 需求

只需要：

```
AssetStudio.CLI.exe
AssetStudio.CLI.dll
AssetStudio.dll
AssetStudio.FBXWrapper.dll
AssetStudio.CLI.runtimeconfig.json
AssetStudio.CLI.deps.json
runtimes/
```

不需要 GUI。(或是你別亂刪了)

---

# ⚙ 設定檔說明

### config_unity3D.json

重點：

```
"group_assets": BySource
```

必須包含：

```
--group_assets BySource
```

否則整理器會失效。

---

### config_lister.json

關鍵設定：

```
"bust_key_regex": "^Card_1_bust_card_(\\d{8})_1_png$"
```

用途：

抓 bust 圖用，因此你可以更換要顯示的圖片

---

# 🧠 ID 結構說明

角色 ID 為 8 位數：

```
[性別][職業][版本][xxxx][神解]
```

例：

```
10101930
```

* 第一位：性別（1 = 男、2 = 女）
* 第二三位：職業：01 劍、02 拳、03 斧、04 槍、05 弓、06 法、07 雙刀、08 龍騎士、09 變身士、10 大劍、11 輝劍、12 鎖劍
* 第四位：版本（目前有 0、1）
* 最後一位：神解（0 = 一般、1 = 神解，另有 13 隻是 2）

各位數的名稱寫在 `config_id_labels.json`，Web GUI 的篩選按鈕會照這裡顯示；職業圖示放在 `gui/icons/job_XX.png`（repo 不附圖示，沒有圖示就只顯示文字）。

---

# ⚠ 免責聲明

**本工具僅供學術研究與資料分析用途，禁止任何商業使用。**



---

# ⑤ 角色骨架 + 動作匯出（GLB）

腳本：

```
3_wcat_3_角色骨架動作匯出.py
```

AssetStudio CLI 只會把 Mesh 轉成 OBJ（沒有骨架），這支改用 UnityPy 直接讀 bundle，輸出帶骨架、權重、貼圖、動作的 `.glb`（Blender / Unity / three.js 可直接開）。

```bash
python "3_wcat_3_角色骨架動作匯出.py" 20413550
python "3_wcat_3_角色骨架動作匯出.py" 20413550 --anims 00000000-00000019 00021355
python "3_wcat_3_角色骨架動作匯出.py" --update-index 20514030
python "3_wcat_3_角色骨架動作匯出.py" --list-anims
```

* 骨架：在角色自己的 `Character_Prefabs_Player_ply_{ID}_prefab` 裡（Root/Spine/...，27 根左右）
* 共用動作：`Character_Animations_Player_anm_{編號}_anim`（legacy AnimationClip，所有玩家角色同一套骨架名稱），預設抓 `00000000-00000019`（config_rig.json 的 `default_anims`）
* 角色專屬（技能）動作：自動找 `Action_act_????{ID第4~7碼}_asset`，讀裡面的 `animeName`（新角色適用；舊角色可能找不到，用 `--anims` 手動指定）
* 新角色找不到模型或動作時，先加 `--update-index` 更新 Character / Action 索引（index_work 裡的索引不會自己更新）
* prefab 裡預設關閉的網格（替換手型、變身用的 body_t1 這類）預設不輸出；`weapon*` 例外，一律保留
* 輸出：角色已經有資料夾（例如 `unity3d_exports\RE0\10208200`）就放那裡，否則 `unity3d_exports\{ID}\`，檔名 `ply_{ID}_rig.glb`
* 下載的 bundle 放 `! wcat\rig_cache`
* 參數：
  * `--no-skill`：不找技能動作
  * `--include-m`：一併輸出 body_m 小模型
  * `--include-hidden`：一併輸出預設關閉的網格
  * `--out`：指定輸出資料夾

---

# ⑥ Web GUI（port 9999）

雙擊 `啟動 Web GUI.bat`，或：

```bash
python wcat_web_gui.py
```

會自動開 http://127.0.0.1:9999/ （只開在本機，區網連不到）。

* **角色**：bust 圖庫，可以搜尋 ID，也能篩選新角色、有模型、已下載、有 GLB，以及依 ID 篩選性別、職業、版本、神解（名稱在 `config_id_labels.json`，可在「設定」頁改）
  * 點角色會顯示：一鍵下載（③ → ④ → ⑤）、只匯出 GLB、卡圖、語音試聽、開啟資料夾
  * 3D 預覽可以選動作、暫停、調速度、拖時間軸、顯示骨頭、鏡頭跟隨
  * 網址加 `#角色ID` 可以直接打開該角色
* **流程**：①～⑤ 每一步各有按鈕，還有「對新角色跑 ③ → ④」
* **工作**：工作會排隊依序執行，可以即時看輸出，也能取消
* **設定**：直接編輯 config_*.json，存檔前會檢查格式

GUI 只是幫你帶參數執行上面的腳本，腳本本身照樣可以在終端機單獨使用。3D 預覽用的 three.js 從 jsDelivr 載入，第一次開需要網路。

---

# 📝 更新紀錄

## 2.0.0

* 新增 ⑤ `3_wcat_3_角色骨架動作匯出.py`：用 UnityPy 輸出帶骨架、權重、貼圖、動作的 GLB
* 新增 ⑥ Web GUI（port 9999）：角色圖庫、3D 預覽、語音試聽、流程按鈕、工作排隊、設定編輯
* 角色可依 ID 篩選性別、職業、版本、神解（`config_id_labels.json`）
* 腳本改名為 `1_wcat_1_…`、`2_wcat_2_…`、`3_wcat_3_…`，方便照順序排
* requirements 加上 UnityPy

## 260217

* 第一版
