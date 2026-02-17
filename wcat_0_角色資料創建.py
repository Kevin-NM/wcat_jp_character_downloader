import json
import re
import time
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urljoin

import requests

CONFIG_NAME = "config_diff.json"

DEFAULT_CONFIG = {
    # JP only
    "base_url": "https://img.wcat.colopl.jp/assets/2020/a/",
    "index_type": "Card",  # Card / Area / Item / Event
    "work_dir": r".\! wcat\index_work",

    "timeout_sec": 30,
    "retries": 3,
    "skip_existing_download": True,

    # AssetStudio CLI
    "assetstudio_cli": r".\AssetStudio\AssetStudio.CLI.exe",
    "assetstudio_game": "Normal",
    "assetstudio_export_type": "Raw",
    "assetstudio_types": "TextAsset",
    "assetstudio_extra_args": "--silent",

    # 額外：需要時才開
    "verbose": False,
}

UNITY_MAGIC = (b"UnityFS", b"UnityWeb", b"UnityRaw")


# -------------------------
# config
# -------------------------
def load_config(path: Path) -> dict:
    if path.exists():
        cfg = json.loads(path.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_CONFIG)
        merged.update(cfg)
        return merged
    return dict(DEFAULT_CONFIG)


def save_config(path: Path, cfg: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# -------------------------
# utilities
# -------------------------
def is_unity_bundle(head16: bytes) -> bool:
    return any(head16.startswith(m) for m in UNITY_MAGIC)


def print_tree(root: Path, max_items: int = 80) -> None:
    if not root.exists():
        print(f"[dbg] (no dir) {root}")
        return

    items = []
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root)
            items.append((len(str(rel)), str(rel)))

    items.sort()
    print(f"[dbg] tree of {root} (files={len(items)})")
    for i, (_, rel) in enumerate(items[:max_items], 1):
        print(f"  - {rel}")
    if len(items) > max_items:
        print(f"  ... ({len(items) - max_items} more)")


def safe_write_text(p: Path, lines: list[str]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8", errors="ignore")


# -------------------------
# download
# -------------------------
def download_file(session: requests.Session, url: str, out_path: Path, timeout: int, retries: int, verbose: bool) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=timeout, allow_redirects=True)
            content = r.content or b""
            head = content[:16]
            ct = r.headers.get("Content-Type", "")
            ce = r.headers.get("Content-Encoding", "")

            if verbose:
                print(f"  [dbg] HTTP {r.status_code} | Content-Type={ct} | Content-Encoding={ce} | len={len(content)}")
                print(f"  [dbg] head64={content[:64]!r}")

            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}")

            # 一律寫檔（避免你遇到「卡頓但沒產出」）
            out_path.write_bytes(content)

            # 檢查 UnityFS header（只針對 index bundle）
            if not is_unity_bundle(head):
                raise RuntimeError(
                    "❌ 下載到的檔案不像 Unity bundle（不是 UnityFS/UnityWeb/UnityRaw）。\n"
                    f"   URL={url}\n"
                    f"   HTTP={r.status_code} Content-Type={ct} Encoding={ce}\n"
                    f"   head16={head!r}\n"
                    "   這通常是拿到錯誤回應/被擋內容/端點回傳不是 unity3d。"
                )

            return

        except Exception as e:
            last_err = str(e)
            if attempt < retries:
                print(f"  [warn] attempt {attempt}/{retries} failed: {last_err}")
                time.sleep(1.0)
            else:
                break

    raise RuntimeError(f"❌ 下載失敗：{last_err}")


# -------------------------
# AssetStudio CLI
# -------------------------
def run_assetstudio_cli(cli: Path, input_path: Path, output_dir: Path, game: str, export_type: str, types: str, extra_args: str) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(cli),
        str(input_path),
        str(output_dir),
        "--game", game,
        "--export_type", export_type,
        "--types", types,
    ]
    if extra_args:
        cmd += extra_args.split()

    print("\n=== AssetStudio CLI ===")
    print("CMD:", " ".join([f"\"{c}\"" if " " in c else c for c in cmd]))
    p = subprocess.run(cmd)
    return int(p.returncode)


def find_textasset_dat(export_dir: Path, index_type: str) -> Path:
    """
    只找指定檔：Card.dat / Area.dat / Item.dat / Event.dat
    （不再亂抓其他 .dat，避免誤判）
    """
    want = f"{index_type}.dat".lower()
    hits = [p for p in export_dir.rglob("*") if p.is_file() and p.name.lower() == want]

    if hits:
        hits.sort(key=lambda x: len(str(x)))
        return hits[0]

    # 找不到就列出資料夾結構，讓你立刻看 AssetStudio 實際吐了啥
    print(f"\n❌ 找不到匯出的 TextAsset：{index_type}.dat")
    print_tree(export_dir)
    raise RuntimeError(f"❌ 找不到匯出的 TextAsset 檔（{index_type}.dat）。請確認 CLI 參數與輸出結果。")


# -------------------------
# parse + diff
# -------------------------
def parse_index_text(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "," not in line:
            continue
        k, v = line.split(",", 1)
        k, v = k.strip(), v.strip()
        if k:
            out[k] = v
    return out


def extract_character_ids(keys: list[str]) -> list[str]:
    """
    依你現在需求：從 Card 的 key 抽角色ID
      card_20413550_2_png -> 20413550
    """
    ids = set()
    pat = re.compile(r"card_(\d+)_\d+_png$", re.IGNORECASE)
    for k in keys:
        m = pat.search(k)
        if m:
            ids.add(m.group(1))
    return sorted(ids)


# -------------------------
# main
# -------------------------
def main():
    script_dir = Path(__file__).resolve().parent
    cfg_path = script_dir / CONFIG_NAME

    # ✅ 只在第一次建立 config，不互動、不每次跳出
    if not cfg_path.exists():
        cfg = dict(DEFAULT_CONFIG)
        save_config(cfg_path, cfg)
        raise SystemExit(
            f"[ok] 已建立預設設定檔：{cfg_path}\n"
            f"請先確認/修改 assetstudio_cli 路徑與 work_dir 後再跑一次。"
        )

    cfg = load_config(cfg_path)
    verbose = bool(cfg.get("verbose", False))

    base_url = (cfg["base_url"].rstrip("/") + "/")
    index_type = cfg["index_type"].strip()
    work_dir = Path(cfg["work_dir"])

    dl_dir = work_dir / "downloads"
    export_dir = work_dir / "assetstudio_export"
    store_dir = work_dir / "index_store"

    dl_dir.mkdir(parents=True, exist_ok=True)
    store_dir.mkdir(parents=True, exist_ok=True)

    cli = Path(str(cfg["assetstudio_cli"]).strip().strip('"'))
    if not cli.exists():
        raise RuntimeError(f"❌ AssetStudio CLI 不存在：{cli}\n   請修正 {cfg_path} 的 assetstudio_cli")

    # 清掉舊 export，避免讀到上一次殘留的 Card.dat
    if export_dir.exists():
        shutil.rmtree(export_dir, ignore_errors=True)
    export_dir.mkdir(parents=True, exist_ok=True)

    # 下載 index bundle（一定要從 assets base_url，不要用 ajax/version 那個）
    index_bundle_name = f"_Version_a_{index_type}_txt.unity3d"
    url = urljoin(base_url, index_bundle_name) + f"?t={int(time.time() * 1000)}"
    out_bundle = dl_dir / index_bundle_name

    print(f"Download: {index_bundle_name}\n  -> {out_bundle}")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (wcat-index-diff/2.1)"})
    download_file(session, url, out_bundle, int(cfg["timeout_sec"]), int(cfg["retries"]), verbose)

    # AssetStudio 抽 TextAsset Raw
    rc = run_assetstudio_cli(
        cli=cli,
        input_path=out_bundle,
        output_dir=export_dir,
        game=cfg["assetstudio_game"],
        export_type=cfg["assetstudio_export_type"],
        types=cfg["assetstudio_types"],
        extra_args=cfg.get("assetstudio_extra_args", ""),
    )
    if rc != 0:
        print_tree(export_dir)
        raise RuntimeError(f"❌ AssetStudio CLI 失敗 rc={rc}")

    dumped = find_textasset_dat(export_dir, index_type)
    print(f"[ok] TextAsset dump: {dumped}")

    raw = dumped.read_bytes()
    text = raw.decode("utf-8", errors="ignore")
    now_index = parse_index_text(text)

    now_path = store_dir / f"now_{index_type}.json"
    last_path = store_dir / f"last_{index_type}.json"
    new_list_path = store_dir / f"new_{index_type}.txt"
    new_ids_path = store_dir / f"new_{index_type}_character_ids.txt"

    now_path.write_text(json.dumps(now_index, ensure_ascii=False, indent=2), encoding="utf-8")

    if last_path.exists():
        last_index = json.loads(last_path.read_text(encoding="utf-8"))
    else:
        last_index = {}

    # diff：新增 or hash 改變
    changed = []
    for k, v in now_index.items():
        if k not in last_index or str(last_index.get(k)) != str(v):
            changed.append(k)

    changed.sort()
    safe_write_text(new_list_path, changed)

    # 解析角色 ID
    new_ids = extract_character_ids(changed)
    safe_write_text(new_ids_path, new_ids)

    # 更新 last_index（你原本的流程）
    last_path.write_text(json.dumps(now_index, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n--------------------------------------------------")
    print(f"Index type: {index_type}")
    print(f"now_index:  {now_path}")
    print(f"last_index: {last_path}")
    print(f"new_index:  {new_list_path}  (count={len(changed)})")
    print(f"new_ids:    {new_ids_path}   (count={len(new_ids)})")
    print("Done.")


if __name__ == "__main__":
    main()
