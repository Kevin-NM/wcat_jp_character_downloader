import json
import re
import argparse
from pathlib import Path

CONFIG_NAME = "config_lister.json"

DEFAULTS = {
    "work_dir": r".\! wcat\index_work",
    "cardtxt_dir": r".\! wcat\index_work\card_txt",

    "use_now_card_json": True,
    "force_4_cards": True,

    "include_voice": True,
    "voice_count": 55,

    "include_prefab": True,

    "include_icon": True,
    "include_bust": True,
    "include_full": True,
    "include_evol": True,
}

CARD_PAT = re.compile(
    r"^Card_([0-3])_(icon|bust|full|evol)_card_(\d{8})_([0-3])_png$",
    re.IGNORECASE
)

# -----------------------------
# Config
# -----------------------------
def load_config(cfg_path: Path) -> dict:
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    else:
        cfg = {}
    merged = dict(DEFAULTS)
    merged.update(cfg)
    return merged

# -----------------------------
# Load index
# -----------------------------
def read_now_card_json(work_dir: Path) -> dict:
    p = work_dir / "index_store" / "now_Card.json"
    if not p.exists():
        raise RuntimeError(f"找不到 now_Card.json：{p}")
    return json.loads(p.read_text(encoding="utf-8"))

# -----------------------------
# Collect Card keys
# -----------------------------
def collect_card_keys_for_id(now_index: dict, char_id: str, cfg: dict) -> list[str]:
    allow_slot = set()
    if cfg["include_icon"]: allow_slot.add("0")
    if cfg["include_bust"]: allow_slot.add("1")
    if cfg["include_full"]: allow_slot.add("2")
    if cfg["include_evol"]: allow_slot.add("3")

    wanted = []
    for k in now_index.keys():
        m = CARD_PAT.match(k)
        if not m:
            continue
        slot = m.group(1)
        cid = m.group(3)
        if cid != char_id:
            continue
        if slot not in allow_slot:
            continue
        wanted.append(k)

    wanted.sort()
    return wanted

# -----------------------------
# Force 4 cards
# -----------------------------
def force_cards(char_id: str, cfg: dict) -> list[str]:
    out = []
    if cfg["include_icon"]:
        out.append(f"Card_0_icon_card_{char_id}_0_png")
    if cfg["include_bust"]:
        out.append(f"Card_1_bust_card_{char_id}_1_png")
    if cfg["include_full"]:
        out.append(f"Card_2_full_card_{char_id}_2_png")
    if cfg["include_evol"]:
        out.append(f"Card_3_evol_card_{char_id}_3_png")
    return out

def gen_voice(char_id: str, count: int) -> list[str]:
    return [f"Sound_Voice_Player_{char_id}_{i:02d}_wav" for i in range(count)]

def gen_prefab(char_id: str) -> list[str]:
    return [f"Character_Prefabs_Player_ply_{char_id}_prefab"]

# -----------------------------
# Write single card.txt
# -----------------------------
def write_card_txt(out_dir: Path, lines: list[str]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "card.txt"

    # 去重 + 保持順序
    seen = set()
    final = []
    for x in lines:
        if x not in seen:
            seen.add(x)
            final.append(x)

    p.write_text("\n".join(final) + "\n", encoding="utf-8")
    return p

# -----------------------------
# Main
# -----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", nargs="*", help="8-digit IDs")
    ap.add_argument("--id_file", help="text file with IDs")
    args = ap.parse_args()

    script_dir = Path(__file__).resolve().parent
    cfg = load_config(script_dir / CONFIG_NAME)

    # 收集 IDs
    ids = []

    if args.id:
        for x in args.id:
            if re.fullmatch(r"\d{8}", x):
                ids.append(x)

    if not ids and args.id_file:
        p = Path(args.id_file)
        if not p.exists():
            raise RuntimeError(f"id_file 不存在：{p}")
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if re.fullmatch(r"\d{8}", s):
                ids.append(s)

    if not ids:
        raw = input("請輸入角色ID（可多個，用空白分隔）：").strip()
        for x in re.split(r"[,\s]+", raw):
            if re.fullmatch(r"\d{8}", x):
                ids.append(x)

    if not ids:
        raise RuntimeError("沒有有效ID")

    work_dir = Path(cfg["work_dir"])
    out_root = Path(cfg["cardtxt_dir"])

    now_index = None
    if cfg["use_now_card_json"]:
        now_index = read_now_card_json(work_dir)

    all_lines = []

    for char_id in ids:
        lines = []

        if now_index:
            lines.extend(collect_card_keys_for_id(now_index, char_id, cfg))

        if cfg["force_4_cards"]:
            have = set(lines)
            for x in force_cards(char_id, cfg):
                if x not in have:
                    lines.append(x)

        if cfg["include_voice"]:
            lines.extend(gen_voice(char_id, int(cfg["voice_count"])))

        if cfg["include_prefab"]:
            lines.extend(gen_prefab(char_id))

        all_lines.extend(lines)

    out_path = write_card_txt(out_root, all_lines)

    print("--------------------------------------------------")
    print(f"card.txt updated: {out_path}")
    print(f"total lines: {len(all_lines)}")

if __name__ == "__main__":
    main()
