import json
import re
import time
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urljoin

import requests

CONFIG_NAME = "config_lister.json"

DEFAULT_CONFIG = {
    # JP only
    "base_url": "https://img.wcat.colopl.jp/assets/2020/a/",
    "timeout_sec": 30,
    "retries": 3,
    "skip_existing_download": True,

    # where now_Card.json is
    "now_card_json": r".\! wcat\index_work\index_store\now_Card.json",

    # work/output
    "work_dir": r".\! wcat\index_work\bust_work",
    "output_dir": r".\! wcat\index_work\bust_gallery",  # 最終圖庫（不建資料夾）

    # AssetStudio CLI
    "assetstudio_cli": r".\AssetStudio\AssetStudio.CLI.exe",
    "assetstudio_game": "Normal",
    "assetstudio_extra_args": "--silent",

    # bust export settings
    # 這邊用 Convert 才會輸出 png
    "assetstudio_export_type": "Convert",
    # 注意：AssetStudio CLI types 參數通常要用逗號或空白分隔（看版本）
    # 你那版顯示是 --types <Texture2D|Shader:Parse|Sprite:Both|...>
    # 所以我們給：Texture2D Sprite:Both
    "assetstudio_types": "Texture2D Sprite:Both",

    # bust key pattern
    "bust_key_regex": r"^Card_1_bust_card_(\d+)_1_png$",
}

UNITY_MAGIC = (b"UnityFS", b"UnityWeb", b"UnityRaw")


def load_config(path: Path) -> dict:
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            merged = dict(DEFAULT_CONFIG)
            merged.update(cfg)
            return merged
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(path: Path, cfg: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def is_unity_bundle(b: bytes) -> bool:
    return any(b.startswith(m) for m in UNITY_MAGIC)


def download_one(session: requests.Session, url: str, out_path: Path, timeout: int, retries: int, skip_existing: bool):
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if skip_existing and out_path.exists() and out_path.stat().st_size > 0:
        return True, f"SKIP -> {out_path.name}"

    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=timeout, allow_redirects=True)
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}")

            head = r.content[:16]
            if not is_unity_bundle(head):
                # 仍然寫出來，避免你覺得卡住沒產出
                out_path.write_bytes(r.content)
                raise RuntimeError(f"Not Unity bundle. head={r.content[:64]!r}")

            out_path.write_bytes(r.content)
            return True, f"OK -> {out_path.name}"
        except Exception as e:
            last_err = str(e)
            if attempt < retries:
                time.sleep(1.0)

    return False, f"ERROR: {last_err}"


def run_assetstudio_cli(cli: Path, input_path: Path, export_dir: Path,
                        game: str, export_type: str,
                        types_list: list[str] | None,
                        containers_regex: str | None,
                        extra_args: str) -> int:
    export_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(cli),
        str(input_path),
        str(export_dir),
        "--game", game,
        "--export_type", export_type,
    ]

    # 用 containers 精準命中（你要的 key）
    if containers_regex:
        cmd += ["--containers", containers_regex]

    # ✅ 重複 --types，最相容
    if types_list:
        for t in types_list:
            cmd += ["--types", t]

    if extra_args:
        cmd += extra_args.split()

    print("=== AssetStudio CLI ===")
    print("CMD:", " ".join([f"\"{c}\"" if " " in c else c for c in cmd]))
    p = subprocess.run(cmd)
    return int(p.returncode)



def find_any_png(export_dir: Path) -> Path | None:
    pngs = list(export_dir.rglob("*.png"))
    if not pngs:
        return None
    # 取最短路徑那個，通常就是主輸出
    pngs.sort(key=lambda p: len(str(p)))
    return pngs[0]


def main():
    script_dir = Path(__file__).resolve().parent
    cfg_path = script_dir / CONFIG_NAME
    cfg = load_config(cfg_path)
    if not cfg_path.exists():
        save_config(cfg_path, cfg)
        print(f"[ok] Config created: {cfg_path}  (第一次可直接改這個檔)")

    base_url = cfg["base_url"].rstrip("/") + "/"
    now_json = Path(cfg["now_card_json"])
    work_dir = Path(cfg["work_dir"])
    out_dir = Path(cfg["output_dir"])
    dl_dir = work_dir / "downloads"
    tmp_export = work_dir / "assetstudio_export_tmp"

    work_dir.mkdir(parents=True, exist_ok=True)
    dl_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    cli = Path(cfg["assetstudio_cli"].strip().strip('"'))
    if not cli.exists():
        raise RuntimeError(f"AssetStudio CLI not found: {cli}")

    if not now_json.exists():
        raise RuntimeError(f"now_Card.json not found: {now_json}")

    data = json.loads(now_json.read_text(encoding="utf-8"))
    # keys: asset_name, value: hash (我們不需要 hash)
    keys = list(data.keys())

    pat = re.compile(cfg["bust_key_regex"], re.IGNORECASE)
    bust_items: list[tuple[str, str]] = []  # (id, key)
    for k in keys:
        m = pat.match(k)
        if m:
            bust_items.append((m.group(1), k))

    bust_items.sort(key=lambda x: x[0])

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (wcat-bust-gallery/1.0)"})

    total = len(bust_items)
    ok = skip = fail = 0

    for i, (cid, key) in enumerate(bust_items, 1):
        out_png = out_dir / f"{cid}.png"
        if out_png.exists() and out_png.stat().st_size > 0:
            skip += 1
            continue

        unity_name = f"{key}.unity3d"
        unity_path = dl_dir / unity_name
        url = urljoin(base_url, unity_name) + f"?t={int(time.time()*1000)}"

        success, msg = download_one(
            session=session,
            url=url,
            out_path=unity_path,
            timeout=int(cfg["timeout_sec"]),
            retries=int(cfg["retries"]),
            skip_existing=bool(cfg["skip_existing_download"]),
        )

        print(f"[{i}/{total}] {cid} | {msg}")
        if not success:
            fail += 1
            continue

        # 清 tmp export，避免撈到上一張 png
        if tmp_export.exists():
            shutil.rmtree(tmp_export, ignore_errors=True)
        tmp_export.mkdir(parents=True, exist_ok=True)

        # 針對這個 unity3d 的 key，精準容器命中
        container_regex = f"^{re.escape(key)}$"

        # 1) 先試：Texture2D + Sprite
        rc = run_assetstudio_cli(
            cli=cli,
            input_path=unity_path,
            export_dir=tmp_export,
            game=cfg["assetstudio_game"],
            export_type=cfg["assetstudio_export_type"],
            types_list=["Texture2D", "Sprite:Both"],
            containers_regex=container_regex,
            extra_args=cfg.get("assetstudio_extra_args", ""),
        )
        png = find_any_png(tmp_export)

        # 2) 還沒有 → 再加 SpriteAtlas
        if not png:
            shutil.rmtree(tmp_export, ignore_errors=True)
            tmp_export.mkdir(parents=True, exist_ok=True)

            rc = run_assetstudio_cli(
                cli=cli,
                input_path=unity_path,
                export_dir=tmp_export,
                game=cfg["assetstudio_game"],
                export_type=cfg["assetstudio_export_type"],
                types_list=["Texture2D", "Sprite:Both", "SpriteAtlas"],
                containers_regex=container_regex,
                extra_args=cfg.get("assetstudio_extra_args", ""),
            )
            png = find_any_png(tmp_export)

        # 3) 還沒有 → 最後不帶 types（全匯出），再撈 png
        if not png:
            shutil.rmtree(tmp_export, ignore_errors=True)
            tmp_export.mkdir(parents=True, exist_ok=True)

            rc = run_assetstudio_cli(
                cli=cli,
                input_path=unity_path,
                export_dir=tmp_export,
                game=cfg["assetstudio_game"],
                export_type=cfg["assetstudio_export_type"],
                types_list=None,  # ✅ 不給 types
                containers_regex=container_regex,
                extra_args=cfg.get("assetstudio_extra_args", ""),
            )
            png = find_any_png(tmp_export)

        if not png:
            print("  ❌ 找不到輸出的 bust png（export 內無 png）")
            fail += 1
            continue


        out_png.write_bytes(png.read_bytes())
        ok += 1

    print("--------------------------------------------------")
    print(f"Done. OK={ok}, SKIP={skip}, FAIL={fail}")
    print(f"Gallery: {out_dir}")
    print(f"Config:  {cfg_path}")


if __name__ == "__main__":
    main()
