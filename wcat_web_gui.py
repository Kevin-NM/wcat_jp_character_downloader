"""
白貓工具箱 Web GUI（只開在本機 127.0.0.1:9999）

  python wcat_web_gui.py            # 開瀏覽器 http://127.0.0.1:9999
  python wcat_web_gui.py --port 9999 --no-browser

把 ①～⑤ 的腳本包成按鈕，照順序排隊執行並即時顯示輸出；
另外有角色圖庫、角色資料夾瀏覽（圖片 / 語音）和 GLB 骨架動作預覽。
腳本本身不變，GUI 只是用 subprocess 幫你帶參數執行。
"""
import argparse
import importlib.util
import json
import mimetypes
import os
import queue
import re
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent
WCAT_DIR = BASE_DIR / "! wcat"
GUI_DIR = BASE_DIR / "gui"

SCRIPTS = {
    "index_diff": {"file": "wcat_0_角色資料創建.py", "title": "① 更新 Card 索引、比對新角色"},
    "bust_gallery": {"file": "wcat_0_創建資料轉圖片.py", "title": "② 下載 bust 圖庫"},
    "card_txt": {"file": "1_wcat_1_角色ID List創建.py", "title": "③ 產生 card.txt", "ids": True},
    "unpack": {"file": "2_wcat_2_角色圖片下載及解包.py", "title": "④ 下載並解包（圖片 / 語音 / OBJ）"},
    "rig": {"file": "3_wcat_3_角色骨架動作匯出.py", "title": "⑤ 骨架 + 動作 GLB", "ids": True},
}
ID_RE = re.compile(r"^\d{8}$")
mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("text/javascript", ".js")


def load_rig_module():
    spec = importlib.util.spec_from_file_location("wcat_rig", BASE_DIR / SCRIPTS["rig"]["file"])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rig = load_rig_module()


# ---------------- 工作佇列 ----------------

class Job:
    _next = 1

    def __init__(self, title, steps):
        self.id = Job._next
        Job._next += 1
        self.title = title
        self.steps = steps  # [(script_key, [args])]
        self.status = "queued"
        self.lines = []
        self.created = time.time()
        self.started = self.ended = None
        self.proc = None
        self.cancelled = False

    def log(self, text):
        self.lines.append(text)

    def summary(self):
        return {"id": self.id, "title": self.title, "status": self.status, "lines": len(self.lines),
                "created": self.created, "started": self.started, "ended": self.ended}


JOBS: dict[int, Job] = {}
JOB_QUEUE: "queue.Queue[Job]" = queue.Queue()


def run_job(job: Job):
    job.status, job.started = "running", time.time()
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    for key, args in job.steps:
        if job.cancelled:
            break
        script = SCRIPTS[key]["file"]
        job.log(f"▶ {SCRIPTS[key]['title']}  ({script} {' '.join(args)})")
        job.proc = subprocess.Popen(
            [sys.executable, "-u", script, *args], cwd=BASE_DIR, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for raw in job.proc.stdout:
            for part in raw.decode("utf-8", "replace").replace("\r", "\n").splitlines():
                if part.strip():
                    job.log(part.rstrip())
        rc = job.proc.wait()
        if job.cancelled:
            break
        if rc != 0:
            job.log(f"✖ 結束碼 {rc}，後面的步驟不執行")
            job.status = "failed"
            break
    job.proc = None
    if job.cancelled:
        job.status = "cancelled"
        job.log("■ 已取消")
    elif job.status == "running":
        job.status = "done"
        job.log("✔ 完成")
    job.ended = time.time()


def worker():
    while True:
        job = JOB_QUEUE.get()
        if job.cancelled:
            job.status = "cancelled"
            continue
        try:
            run_job(job)
        except Exception as e:  # 不讓一個工作掛掉整個佇列
            job.log(f"✖ GUI 執行錯誤：{e}")
            job.status, job.ended = "failed", time.time()


def cancel_job(job: Job):
    job.cancelled = True
    if job.proc and job.proc.poll() is None:
        # 連 AssetStudio 這種子行程一起關
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(job.proc.pid)], capture_output=True)
    if job.status == "queued":
        job.status = "cancelled"


def submit(title, steps) -> Job:
    job = Job(title, steps)
    JOBS[job.id] = job
    JOB_QUEUE.put(job)
    return job


# ---------------- 資料查詢 ----------------

_cache = {}


def cached(key, paths, fn):
    """依檔案修改時間快取（索引 bundle 很大，不要每次都解析）"""
    stamp = tuple(p.stat().st_mtime if p.exists() else 0 for p in paths)
    hit = _cache.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    val = fn()
    _cache[key] = (stamp, val)
    return val


def rig_cfg():
    return rig.load_config()


def index_paths():
    cfg = rig_cfg()
    return rig.resolve(cfg["character_index"]), rig.resolve(cfg["action_index"])


def prefab_ids():
    char_idx, _ = index_paths()
    return cached("prefab", [char_idx], lambda: set(rig.load_index_names(char_idx, rig.PREFAB_PAT)))


def anim_names():
    char_idx, _ = index_paths()
    return cached("anims", [char_idx], lambda: rig.load_index_names(char_idx, rig.ANIM_PAT))


def bust_dir():
    return WCAT_DIR / "index_work" / "bust_gallery"


def char_dirs() -> dict[str, list[Path]]:
    """! wcat 底下所有 8 位數資料夾（含 unity3d_exports\\活動名\\ID 這種分類）"""
    found = {}
    roots = [WCAT_DIR, rig.resolve(rig_cfg()["export_dir"])]
    for root in roots:
        if not root.is_dir():
            continue
        for d in root.iterdir():
            if not d.is_dir():
                continue
            if ID_RE.match(d.name):
                found.setdefault(d.name, []).append(d)
            elif root != WCAT_DIR:
                for sub in d.iterdir():
                    if sub.is_dir() and ID_RE.match(sub.name):
                        found.setdefault(sub.name, []).append(sub)
    return found


def rel(p: Path) -> str:
    return p.resolve().relative_to(WCAT_DIR.resolve()).as_posix()


def new_ids() -> list[str]:
    p = WCAT_DIR / "index_work" / "index_store" / "new_Card_character_ids.txt"
    if not p.exists():
        return []
    return [s.strip() for s in p.read_text(encoding="utf-8").splitlines() if ID_RE.match(s.strip())]


def characters():
    busts = {p.stem for p in bust_dir().glob("*.png")} if bust_dir().is_dir() else set()
    prefabs = prefab_ids()
    dirs = char_dirs()
    news = set(new_ids())
    out = []
    for cid in sorted(busts | prefabs | set(dirs) | news, reverse=True):
        ds = dirs.get(cid, [])
        out.append({
            "id": cid, "bust": cid in busts, "prefab": cid in prefabs, "new": cid in news,
            "dirs": [rel(d) for d in ds],
            "rig": any((d / f"ply_{cid}_rig.glb").exists() for d in ds),
        })
    return out


def char_detail(cid):
    detail = {"id": cid, "bust": f"index_work/bust_gallery/{cid}.png" if (bust_dir() / f"{cid}.png").exists() else None,
              "prefab": cid in prefab_ids(), "dirs": []}
    for d in char_dirs().get(cid, []):
        info = {"path": rel(d), "images": [], "voices": [], "glb": [], "other": []}
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            r, ext = rel(p), p.suffix.lower()
            if ext == ".glb":
                info["glb"].append(r)
            elif ext == ".wav":
                info["voices"].append(r)
            elif ext == ".png" and p.parent == d:
                info["images"].append(r)
            elif ext in (".obj", ".fbx"):
                info["other"].append(r)
        detail["dirs"].append(info)
    return detail


def status():
    char_idx, act_idx = index_paths()
    cli = BASE_DIR / "AssetStudio" / "AssetStudio.CLI.exe"
    now_card = WCAT_DIR / "index_work" / "index_store" / "now_Card.json"
    stamp = lambda p: time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime)) if p.exists() else None
    return {
        "python": sys.version.split()[0],
        "assetstudio": cli.exists(),
        "card_index": stamp(now_card),
        "character_index": stamp(char_idx),
        "action_index": stamp(act_idx),
        "new_ids": len(new_ids()),
        "busts": len(list(bust_dir().glob("*.png"))) if bust_dir().is_dir() else 0,
        "scripts": {k: {"title": v["title"], "exists": (BASE_DIR / v["file"]).exists(), "file": v["file"]}
                    for k, v in SCRIPTS.items()},
    }


def config_files():
    return sorted(p.name for p in BASE_DIR.glob("config_*.json"))


# ---------------- 依需求組工作 ----------------

def clean_ids(ids):
    out = [s for s in (str(x).strip() for x in ids or []) if ID_RE.match(s)]
    if not out:
        raise ValueError("沒有有效的 8 位數角色 ID")
    return list(dict.fromkeys(out))


def rig_args(ids, opts):
    args = list(ids)
    anims = [a for a in re.split(r"[,\s]+", opts.get("anims", "") or "") if a]
    if anims:
        args += ["--anims", *anims]
    if opts.get("no_skill"):
        args.append("--no-skill")
    if opts.get("include_m"):
        args.append("--include-m")
    if opts.get("include_hidden"):
        args.append("--include-hidden")
    if opts.get("update_index"):
        args.append("--update-index")
    return args


def build_job(body):
    task = body.get("task")
    opts = body.get("options", {}) or {}
    if task in ("index_diff", "bust_gallery", "unpack"):
        return SCRIPTS[task]["title"], [(task, [])]
    if task == "card_txt":
        ids = clean_ids(body.get("ids"))
        return f"{SCRIPTS[task]['title']}：{' '.join(ids)}", [(task, ["--id", *ids])]
    if task == "rig":
        ids = clean_ids(body.get("ids"))
        return f"⑤ GLB：{' '.join(ids)}", [("rig", rig_args(ids, opts))]
    if task == "rig_update_index":
        return "⑤ 更新 Character / Action 索引", [("rig", ["--update-index"])]
    if task == "char_all":
        # 單一角色一鍵：③ card.txt → ④ 下載解包 → ⑤ GLB
        ids = clean_ids(body.get("ids"))
        steps = [("card_txt", ["--id", *ids]), ("unpack", [])]
        if opts.get("with_rig", True):
            steps.append(("rig", rig_args(ids, opts)))
        return f"一鍵下載：{' '.join(ids)}", steps
    if task == "new_chars":
        ids = clean_ids(new_ids())
        return f"新角色 {len(ids)} 隻：③ → ④", [("card_txt", ["--id", *ids]), ("unpack", [])]
    raise ValueError(f"未知的工作：{task}")


# ---------------- HTTP ----------------

class Handler(BaseHTTPRequestHandler):
    server_version = "wcat-gui/1.0"

    def log_message(self, fmt, *a):
        pass  # 不洗版

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, cache=False):
        size = path.stat().st_size
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else end
            else:
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-cache")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 16, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def safe_path(self, root: Path, sub: str) -> Path | None:
        p = (root / unquote(sub)).resolve()
        try:
            p.relative_to(root.resolve())
        except ValueError:
            return None
        return p

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}

    def do_GET(self):
        url = urlparse(self.path)
        path, qs = url.path, parse_qs(url.query)
        try:
            if path == "/":
                return self.send_file(GUI_DIR / "index.html")
            if path.startswith("/gui/"):
                p = self.safe_path(GUI_DIR, path[5:])
                return self.send_file(p) if p and p.is_file() else self.send_error(404)
            if path.startswith("/files/"):
                p = self.safe_path(WCAT_DIR, path[7:])
                return self.send_file(p, cache=p.suffix.lower() == ".png") if p and p.is_file() else self.send_error(404)
            if path == "/api/status":
                return self.send_json(status())
            if path == "/api/characters":
                return self.send_json(characters())
            m = re.fullmatch(r"/api/char/(\d{8})", path)
            if m:
                return self.send_json(char_detail(m.group(1)))
            if path == "/api/anims":
                pre, suf = "Character_Animations_Player_anm_", "_anim"
                return self.send_json([n[len(pre):-len(suf)] for n in anim_names()])
            if path == "/api/jobs":
                return self.send_json([j.summary() for j in sorted(JOBS.values(), key=lambda j: -j.id)])
            m = re.fullmatch(r"/api/job/(\d+)", path)
            if m:
                job = JOBS.get(int(m.group(1)))
                if not job:
                    return self.send_json({"error": "沒有這個工作"}, 404)
                since = int(qs.get("since", ["0"])[0])
                return self.send_json({**job.summary(), "from": since, "log": job.lines[since:]})
            if path == "/api/id_labels":
                p = BASE_DIR / "config_id_labels.json"
                return self.send_json(json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {})
            if path == "/api/configs":
                return self.send_json({n: (BASE_DIR / n).read_text(encoding="utf-8") for n in config_files()})
            self.send_error(404)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self.body_json()
            if path == "/api/run":
                title, steps = build_job(body)
                return self.send_json(submit(title, steps).summary())
            m = re.fullmatch(r"/api/job/(\d+)/cancel", path)
            if m and int(m.group(1)) in JOBS:
                cancel_job(JOBS[int(m.group(1))])
                return self.send_json({"ok": True})
            if path == "/api/config":
                name, text = body.get("name"), body.get("text", "")
                if name not in config_files():
                    return self.send_json({"error": "不是可編輯的設定檔"}, 400)
                json.loads(text)  # 格式錯就不存
                (BASE_DIR / name).write_text(text, encoding="utf-8")
                return self.send_json({"ok": True})
            if path == "/api/open":
                p = self.safe_path(WCAT_DIR, body.get("path", ""))
                if not p or not p.exists():
                    return self.send_json({"error": "路徑不存在"}, 400)
                os.startfile(p if p.is_dir() else p.parent)
                return self.send_json({"ok": True})
            self.send_error(404)
        except (ValueError, json.JSONDecodeError) as e:
            self.send_json({"error": str(e)}, 400)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)


def main():
    ap = argparse.ArgumentParser(description="白貓工具箱 Web GUI")
    ap.add_argument("--port", type=int, default=9999)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    threading.Thread(target=worker, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"白貓工具箱 GUI：{url}  （Ctrl+C 結束）")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
