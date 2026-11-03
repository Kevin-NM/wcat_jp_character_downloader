import re
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from PIL import Image

CONFIG_NAME = "config_unity3D.json"

DEFAULT_CONFIG = {
    "configured": False,
    "base_url": "https://img.wcat.colopl.jp/assets/2020/a/",
    "card_txt": r".\! wcat\index_work\card_txt\card.txt",
    "download_dir": r".\! wcat\unity3d_downloads",
    "export_dir": r".\! wcat\unity3d_exports",
    "assetstudio_cli": r".\AssetStudio\AssetStudio.CLI.exe",

    # ✅ 重點：加上 --group_assets BySource
    # 這樣才會輸出 *.unity3d_export 讓後處理整理能工作
    "assetstudio_args": "--game Normal --export_type Convert --group_assets BySource --silent",

    "timeout_sec": 30,
    "retries": 3,
    "skip_existing_download": True,

    "postprocess_images": True,
    "organize_outputs": True,
}

# -------------------------
# helpers
# -------------------------
def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)
    name = name.strip().strip(".")
    return name or "unnamed"

def normalize_base_url(u: str) -> str:
    u = (u or "").strip()
    if not u.endswith("/"):
        u += "/"
    return u

def load_config(path: Path) -> dict:
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            merged = dict(DEFAULT_CONFIG)
            merged.update(cfg)
            merged["base_url"] = normalize_base_url(merged.get("base_url", DEFAULT_CONFIG["base_url"]))
            return merged
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(path: Path, cfg: dict) -> None:
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

def prompt_edit(title: str, current: str) -> str:
    print(f"\n{title}\n  Current: {current}")
    new_val = input("  Enter new value (blank = keep): ").strip()
    return new_val if new_val else current

def read_cards(card_txt_path: Path) -> list[str]:
    if not card_txt_path.exists():
        raise FileNotFoundError(f"card.txt not found: {card_txt_path}")
    cards = []
    for line in card_txt_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith("//"):
            continue
        cards.append(s)
    return cards

# -------------------------
# download
# -------------------------
def head_len(session: requests.Session, url: str, timeout: int):
    try:
        r = session.head(url, allow_redirects=True, timeout=timeout)
        if r.status_code >= 400:
            return None
        cl = r.headers.get("Content-Length")
        return int(cl) if cl and cl.isdigit() else None
    except Exception:
        return None

def download_one(session: requests.Session, url: str, out_path: Path, timeout: int, retries: int, skip_existing: bool):
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if skip_existing and out_path.exists():
        remote = head_len(session, url, timeout)
        if remote is None or out_path.stat().st_size == remote:
            return True, f"SKIP -> {out_path.name}"

    last_err = ""
    for _ in range(retries):
        try:
            with session.get(url, stream=True, timeout=timeout, allow_redirects=True) as r:
                if r.status_code >= 400:
                    return False, f"HTTP {r.status_code}"

                tmp = out_path.with_suffix(out_path.suffix + ".part")
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
                tmp.replace(out_path)
                return True, f"OK -> {out_path.name}"
        except Exception as e:
            last_err = str(e)

    return False, f"ERROR: {last_err}"

# -------------------------
# AssetStudio CLI
# -------------------------
def find_cli_guess(base_dir: Path) -> str:
    candidates = ["AssetStudioCLI.exe", "AssetStudio.CLI.exe"]
    for base in [Path.cwd(), base_dir, base_dir.parent]:
        for c in candidates:
            p = base / c
            if p.exists():
                return str(p)
    for c in candidates:
        p = shutil.which(c)
        if p:
            return p
    return ""

def run_assetstudio_cli(cli: str, input_dir: Path, output_dir: Path, extra_args: str) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [cli, str(input_dir), str(output_dir)]
    if extra_args:
        cmd += extra_args.split()

    print("\n=== AssetStudio CLI ===")
    print("CMD:", " ".join([f"\"{x}\"" if " " in x else x for x in cmd]))

    p = subprocess.run(cmd)
    return int(p.returncode)

# -------------------------
# post-process images (修正尺寸)
# -------------------------
def apply_resize_logic(bundle_stem: str, img: Image.Image) -> Image.Image:
    w, h = img.size

    if bundle_stem.startswith("Card"):
        if ("std" not in bundle_stem) and (not bundle_stem.endswith("w_png")) and (w == 1024 and h == 1024):
            return img.resize((1024, 1331), Image.Resampling.LANCZOS)

    if bundle_stem.startswith("Location"):
        if (w == 512 and h == 512):
            return img.resize((768, 512), Image.Resampling.LANCZOS)
        if (w == 1024 and h == 1024):
            return img.resize((1536, 1024), Image.Resampling.LANCZOS)

    if ("loginBonus_bg" in bundle_stem) and (w == 1024 and h == 1024):
        return img.resize((1024, 1536), Image.Resampling.LANCZOS)

    return img

def postprocess_exported_images(export_root: Path) -> tuple[int, int]:
    changed = 0
    scanned = 0

    for bundle_dir in export_root.glob("*.unity3d_export"):
        if not bundle_dir.is_dir():
            continue
        bundle_stem = bundle_dir.name.replace(".unity3d_export", "")

        for p in bundle_dir.rglob("*.png"):
            scanned += 1
            try:
                with Image.open(p) as im:
                    im = im.convert("RGBA")
                    new_im = apply_resize_logic(bundle_stem, im)
                    if new_im.size != im.size:
                        new_im.save(p, format="PNG")
                        changed += 1
            except Exception:
                continue

    return changed, scanned

# -------------------------
# organize outputs (依 ID 整理)
# -------------------------
ID_RE = re.compile(r"_(\d{6,})_")

def extract_id(name: str) -> str | None:
    m = ID_RE.search(name)
    return m.group(1) if m else None

def move_all(src_dir: Path, dst_dir: Path):
    dst_dir.mkdir(parents=True, exist_ok=True)

    def unique_target(path: Path) -> Path:
        if not path.exists():
            return path
        stem, suf = path.stem, path.suffix
        for i in range(1, 9999):
            cand = path.with_name(f"{stem}__dup{i}{suf}")
            if not cand.exists():
                return cand
        return path.with_name(f"{stem}__dupX{suf}")

    for p in src_dir.rglob("*"):
        if p.is_dir():
            continue

        rel_parts = p.relative_to(src_dir).parts
        filtered = [x for x in rel_parts[:-1] if not x.startswith("CAB-")]

        target = dst_dir / p.name
        target = unique_target(target)

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(target))

    for d in sorted([x for x in src_dir.rglob("*") if x.is_dir()], key=lambda x: len(x.parts), reverse=True):
        try:
            d.rmdir()
        except Exception:
            pass

def organize_export_tree(export_root: Path) -> tuple[int, int]:
    moved_bundles = 0
    skipped = 0

    for bundle_dir in export_root.glob("*.unity3d_export"):
        if not bundle_dir.is_dir():
            continue

        bundle_stem = bundle_dir.name.replace(".unity3d_export", "")
        id_ = extract_id(bundle_stem)
        if not id_:
            skipped += 1
            continue

        id_root = export_root / id_

        if bundle_stem.startswith("Sound_Voice_Player_") and bundle_stem.endswith("_wav"):
            wav_root = id_root / f"Sound_Voice_Player_{id_}_wav"
            move_all(bundle_dir, wav_root)
            bundle_dir.rmdir()
            moved_bundles += 1
            continue

        if bundle_stem.startswith("Character_Prefabs_Player_ply_") and bundle_stem.endswith("_prefab"):
            prefab_root = id_root / f"Character_Prefabs_Player_ply_{id_}_prefab"
            move_all(bundle_dir, prefab_root)
            bundle_dir.rmdir()
            moved_bundles += 1
            continue

        if bundle_stem.startswith("Card_") and bundle_stem.endswith("_png"):
            move_all(bundle_dir, id_root)
            bundle_dir.rmdir()
            moved_bundles += 1
            continue

        misc = id_root / "_misc" / safe_filename(bundle_stem)
        move_all(bundle_dir, misc)
        bundle_dir.rmdir()
        moved_bundles += 1

    return moved_bundles, skipped

def diagnose_grouping(export_root: Path) -> None:
    """
    如果你看到 export_root 下面有 Texture2D/AudioClip/...，但沒有 *.unity3d_export，
    就表示 AssetStudio 仍然在 ByType 模式輸出，整理器會失效。
    """
    has_unity3d_export = any(p.is_dir() for p in export_root.glob("*.unity3d_export"))
    if has_unity3d_export:
        return

    type_dirs = ["Texture2D", "AudioClip", "Mesh", "Material", "Shader", "MonoBehaviour", "TextAsset", "Sprite"]
    if any((export_root / d).exists() for d in type_dirs):
        print("\n⚠️ 目前 AssetStudio 輸出是「按類型分資料夾」(ByType)，所以不會有 *.unity3d_export。")
        print("   你的整理規則依賴 *.unity3d_export，請確定 assetstudio_args 包含：")
        print("     --group_assets BySource\n")

# -------------------------
# main
# -------------------------
def main():
    script_dir = Path(__file__).resolve().parent
    cfg_path = script_dir / CONFIG_NAME
    cfg = load_config(cfg_path)

    force_setup = "--setup" in sys.argv

    if (not cfg.get("configured", False)) or force_setup:
        print("=== First-time setup (or --setup) ===")

        cfg["base_url"] = normalize_base_url(prompt_edit("1) Base URL", cfg["base_url"]))
        cfg["card_txt"] = prompt_edit("2) card.txt path", cfg["card_txt"])
        cfg["download_dir"] = prompt_edit("3) Download directory", cfg["download_dir"])
        cfg["export_dir"] = prompt_edit("4) Export directory", cfg["export_dir"])

        guess = cfg.get("assetstudio_cli") or find_cli_guess(Path(cfg["download_dir"]))
        cfg["assetstudio_cli"] = prompt_edit("5) AssetStudio CLI path (AssetStudio.CLI.exe)", guess)

        # ✅ 直接提示你要加 BySource
        default_args = cfg.get("assetstudio_args", DEFAULT_CONFIG["assetstudio_args"])
        cfg["assetstudio_args"] = prompt_edit(
            "6) AssetStudio args (建議包含 --group_assets BySource)",
            default_args
        )

        pp = prompt_edit("7) Postprocess images? (true/false)", str(cfg.get("postprocess_images", True)).lower())
        cfg["postprocess_images"] = (pp.lower() in ("1", "true", "yes", "y", "on"))

        org = prompt_edit("8) Organize outputs? (true/false)", str(cfg.get("organize_outputs", True)).lower())
        cfg["organize_outputs"] = (org.lower() in ("1", "true", "yes", "y", "on"))

        cfg["configured"] = True
        save_config(cfg_path, cfg)
        print(f"\nConfig saved: {cfg_path}\n")
    else:
        cfg["base_url"] = normalize_base_url(cfg["base_url"])

    base_url = cfg["base_url"]
    card_txt = Path(cfg["card_txt"])
    download_dir = Path(cfg["download_dir"])
    export_dir = Path(cfg["export_dir"])

    # ✅ 每次執行前清空下載資料夾（避免殘留/重複建立）
    if download_dir.exists():
        print(f"Clearing download_dir: {download_dir}")
        shutil.rmtree(download_dir, ignore_errors=True)
    download_dir.mkdir(parents=True, exist_ok=True)

    timeout = int(cfg.get("timeout_sec", 30))
    retries = int(cfg.get("retries", 3))
    skip_existing = bool(cfg.get("skip_existing_download", True))

    cli = (cfg.get("assetstudio_cli") or "").strip().strip('"')
    if not cli:
        print("⚠️ assetstudio_cli is empty. Run with --setup to configure.")
        return
    cli_path = Path(cli)
    if not cli_path.exists():
        print(f"⚠️ CLI not found: {cli}")
        print("   Run with --setup and set correct path.")
        return

    cards = read_cards(card_txt)
    if not cards:
        print("card.txt is empty.")
        return

    # 下載
    print("=== Download unity3d ===")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (unity3d-downloader/1.0)"})

    ok, fail = 0, 0
    for i, card in enumerate(cards, 1):
        rel = f"{card}.unity3d"
        url = urljoin(base_url, rel)
        unity3d_path = download_dir / safe_filename(rel)

        success, msg = download_one(session, url, unity3d_path, timeout, retries, skip_existing)
        print(f"[{i}/{len(cards)}] {'✅' if success else '❌'} {card} | {msg}")
        if success:
            ok += 1
        else:
            fail += 1

    print("\n--------------------------------------------------")
    print(f"Download done. OK={ok}, FAIL={fail}")
    print(f"Downloads: {download_dir}")

    # 解包
    rc = run_assetstudio_cli(str(cli_path), download_dir, export_dir, cfg.get("assetstudio_args", ""))
    print("\n--------------------------------------------------")
    print(f"Unpack done. rc={rc}")
    print(f"Exports: {export_dir}")

    # ✅ 提醒 grouping 模式
    diagnose_grouping(export_dir)

    # 修正尺寸（只會處理 *.unity3d_export 內的 png）
    if cfg.get("postprocess_images", True):
        print("\n=== Postprocess images (resize rules) ===")
        changed, scanned = postprocess_exported_images(export_dir)
        print(f"Images scanned={scanned}, resized={changed}")

    # 整理輸出（依賴 *.unity3d_export）
    if cfg.get("organize_outputs", True):
        print("\n=== Organize outputs by ID ===")
        moved, skipped = organize_export_tree(export_dir)
        print(f"Bundles organized={moved}, skipped(no ID matched)={skipped}")

    print("\nDone.")

if __name__ == "__main__":
    main()
