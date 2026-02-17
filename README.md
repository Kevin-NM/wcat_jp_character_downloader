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

因使用起來無法達到效果，看了程式碼後發現整體概念不難重現，因此使用ChatGPT 5.2轉成python進行改良

這個專案的目的只管能出圖，所以有些小細節沒有做出來

GUI也沒有做，因為我認為termnal夠我使用

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
config_diff.json             ← Index 比對設定
config_lister.json           ← card.txt 生成設定
config_unity3D.json          ← unity3d 解包設定
config_bust.json             ← bust gallery 設定

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

unity3d_downloads/
unity3d_exports/
```
---

# 📥 安裝方式

```bash
pip install -r requirements.txt

---

# ⚙ 系統需求

- Python 3.10+
- Windows (因為使用 AssetStudio CLI)

---

# 🧩 工具流程

整個流程分成四個階段：

---

# ① 角色 Index 比對

腳本：

```
wcat_1_角色ID List創建.py
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
wcat_0_角色資料創建.py
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
wcat_2_角色圖片下載及解包.py
```

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

* 第一位：性別
* 第二三位：職業
* 第四位：版本
* 最後一位：神解

---

⚠ 免責聲明

本工具僅供學術研究與資料分析用途，禁止任何商業使用。