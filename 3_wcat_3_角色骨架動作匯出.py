"""
白貓角色 prefab -> 帶骨架 + 動作的 GLB

AssetStudio CLI 只會把 Mesh 轉成 OBJ（沒有骨架），所以這支直接用 UnityPy 讀 bundle：
  * Character_Prefabs_Player_ply_{ID}_prefab.unity3d  -> 網格、骨架(Transform)、權重、bindpose、材質貼圖
  * Character_Animations_Player_anm_{編號}_anim.unity3d -> legacy AnimationClip（多角色共用，骨架名稱一致）
  * Action_act_????{ID第4~7碼}_asset.unity3d -> 角色技能用到哪些 anm（自動加入）
然後自己寫出 glTF 2.0 Binary (.glb)，Blender / Unity / three.js 都能直接開。

用法：
  python "3_wcat_3_角色骨架動作匯出.py" 20413550
  python "3_wcat_3_角色骨架動作匯出.py" 20413550 --anims 00000000-00000010 00000014
  python "3_wcat_3_角色骨架動作匯出.py" 20413550 --out "D:\\somewhere"
  python "3_wcat_3_角色骨架動作匯出.py" --update-index 20413550   # 先更新 Character / Action 索引
  python "3_wcat_3_角色骨架動作匯出.py" --list-anims                # 列出所有共用動作

需要：pip install UnityPy requests
"""
import argparse
import json
import math
import re
import struct
import sys
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import requests
import UnityPy
from UnityPy.helpers.MeshHelper import MeshHandler

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = {
    "base_url": "https://img.wcat.colopl.jp/assets/2020/a/",
    # 不跟 2_wcat_2 共用 unity3d_downloads（那支每次執行都會清空）
    "download_dir": r".\! wcat\rig_cache",
    "export_dir": r".\! wcat\unity3d_exports",
    "character_index": r".\! wcat\index_work\_Version_a_Character_txt.unity3d",
    "action_index": r".\! wcat\index_work\_Version_a_Action_txt.unity3d",
    # 不指定 --anims 時用的動作（玩家共用的基本動作）
    "default_anims": "00000000-00000019",
    "sample_fps": 30,
    "timeout_sec": 30,
    "retries": 3,
}
CONFIG_PATH = BASE_DIR / "config_rig.json"


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    cfg.update(saved)
    if saved.keys() != cfg.keys():  # 補上新欄位
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (BASE_DIR / path).resolve()


# ---------------- 下載 ----------------

def download(session, base_url, name, download_dir: Path, timeout, retries) -> Path | None:
    out = download_dir / f"{name}.unity3d"
    if out.exists() and out.stat().st_size > 0:
        return out
    url = urljoin(base_url, f"{name}.unity3d")
    for _ in range(retries):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            out.write_bytes(r.content)
            return out
        except requests.RequestException as e:
            err = e
    print(f"  ⚠️ 下載失敗 {name}: {err}")
    return None


def update_index(session, base_url, index_bundle: Path, timeout):
    """重新下載 _Version_a_*_txt.unity3d（新角色要靠它才找得到動作）"""
    url = urljoin(base_url, index_bundle.name) + f"?t={int(time.time() * 1000)}"
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    index_bundle.parent.mkdir(parents=True, exist_ok=True)
    index_bundle.write_bytes(r.content)
    print(f"  索引已更新：{index_bundle.name}（{len(r.content) // 1024} KB）")


def load_index_names(index_bundle: Path, pattern: str) -> list[str]:
    if not index_bundle.exists():
        return []
    env = UnityPy.load(str(index_bundle))
    for obj in env.objects:
        if obj.type.name == "TextAsset":
            data = obj.read().m_Script
            text = data if isinstance(data, str) else bytes(data).decode("utf-8", "replace")
            return re.findall(pattern, text)
    return []


def find_skill_anims(cid: str, action_names: list[str], dl) -> list[str]:
    """
    角色專屬（技能）動作：Action_act_????{ID第4~7碼}_asset 裡的 animeName。
    這是從檔名規則推出來的（新角色適用，舊角色可能找不到），找不到就只用共用動作。
    """
    serial = cid[3:7]
    acts = [n for n in action_names if re.fullmatch(rf"Action_act_\d{{4}}{serial}(_[a-z0-9_]+)?_asset", n)]
    anims = []
    for act in acts:
        p = dl(act)
        if not p:
            continue
        env = UnityPy.load(str(p))
        for obj in env.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            try:
                text = json.dumps(obj.read_typetree(), ensure_ascii=False, default=str)
            except Exception:
                continue
            anims += re.findall(r'"animeName": "(anm_[0-9A-Za-z_]+)"', text)
        print(f"  {act}: {sorted(set(anims))}")
    return [f"Character_Animations_Player_{a}_anim" for a in dict.fromkeys(anims)]


ANIM_PAT = r"(Character_Animations_Player_anm_[0-9A-Za-z_]+?_anim)(?=,)"
ACTION_PAT = r"(Action_act_[0-9A-Za-z_]+?_asset)(?=,)"
PREFAB_PAT = r"Character_Prefabs_Player_ply_(\d{8})_prefab(?=,)"


def find_char_dir(export_dir: Path, cid: str) -> Path:
    """已經有這個角色的資料夾（例如 unity3d_exports\\RE0\\10208200）就輸出到那裡"""
    for d in [export_dir / cid, *export_dir.glob(f"*/{cid}")]:
        if d.is_dir():
            return d
    return export_dir / cid


def parse_anim_spec(specs: list[str], index_names: list[str]) -> list[str]:
    """'00000000-00000019' / '00000014' / '00000013_s' / 完整名稱 -> bundle 名稱清單"""
    result = []
    for spec in specs:
        m = re.fullmatch(r"(\d{8})-(\d{8})", spec)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            for n in index_names:
                mm = re.fullmatch(r"Character_Animations_Player_anm_(\d{8})(_[a-z0-9_]+)?_anim", n)
                # 範圍只收主要版本（排除 _rider 坐騎版）
                if mm and lo <= int(mm.group(1)) <= hi and "rider" not in (mm.group(2) or ""):
                    result.append(n)
            if not index_names:
                result += [f"Character_Animations_Player_anm_{i:08d}_anim" for i in range(lo, hi + 1)]
        elif spec.startswith("Character_"):
            result.append(spec)
        else:
            result.append(f"Character_Animations_Player_anm_{spec}_anim")
    return list(dict.fromkeys(result))


# ---------------- Unity -> glTF 座標 ----------------
# Unity 左手座標；glTF 右手。把 X 軸鏡像：pos(-x,y,z)、quat(x,-y,-z,w)、三角形反向

def cv_pos(v):
    return (-v[0], v[1], v[2])


def cv_quat(q):
    return (q[0], -q[1], -q[2], q[3])


def cv_bindpose(m):
    """Unity Matrix4x4f -> glTF column-major 16 floats（S*M*S, S=diag(-1,1,1,1)）"""
    e = [[getattr(m, f"e{r}{c}") for c in range(4)] for r in range(4)]
    s = [-1, 1, 1, 1]
    e = [[e[r][c] * s[r] * s[c] for c in range(4)] for r in range(4)]
    return [e[r][c] for c in range(4) for r in range(4)]


def euler_zxy_to_quat(x, y, z):
    """Unity euler(度, 套用順序 Z->X->Y) -> quaternion"""
    hx, hy, hz = (math.radians(a) * 0.5 for a in (x, y, z))
    cx, sx, cy, sy, cz, sz = math.cos(hx), math.sin(hx), math.cos(hy), math.sin(hy), math.cos(hz), math.sin(hz)
    # q = qy * qx * qz
    w = cy * cx * cz + sy * sx * sz
    qx = cy * sx * cz + sy * cx * sz
    qy = sy * cx * cz - cy * sx * sz
    qz = cy * cx * sz - sy * sx * cz
    return (qx, qy, qz, w)


# ---------------- 曲線取樣 ----------------

def sample_curve(keys, t, comps):
    """Unity AnimationCurve（Hermite）取樣，keys 為 typetree dict 列表"""
    if t <= keys[0]["time"]:
        k = keys[0]["value"]
        return [k[c] for c in comps]
    if t >= keys[-1]["time"]:
        k = keys[-1]["value"]
        return [k[c] for c in comps]
    lo, hi = 0, len(keys) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if keys[mid]["time"] <= t:
            lo = mid
        else:
            hi = mid
    k0, k1 = keys[lo], keys[hi]
    dt = k1["time"] - k0["time"]
    if dt <= 0:
        return [k1["value"][c] for c in comps]
    s = (t - k0["time"]) / dt
    s2, s3 = s * s, s * s * s
    h00, h10, h01, h11 = 2 * s3 - 3 * s2 + 1, s3 - 2 * s2 + s, -2 * s3 + 3 * s2, s3 - s2
    out = []
    for c in comps:
        p0, p1 = k0["value"][c], k1["value"][c]
        m0, m1 = k0["outSlope"][c], k1["inSlope"][c]
        if not (math.isfinite(m0) and math.isfinite(m1)):
            out.append(p0)  # 階梯（constant）切線
        else:
            out.append(h00 * p0 + h10 * m0 * dt + h01 * p1 + h11 * m1 * dt)
    return out


def bake_clip(clip_tree, fps):
    """回傳 (clip名稱, 長度秒, {path: {'rotation': [...], 'translation': [...], 'scale': [...]}}, times)"""
    end = 0.0
    groups = {"m_RotationCurves": "rotation", "m_PositionCurves": "translation",
              "m_ScaleCurves": "scale", "m_EulerCurves": "euler"}
    for key in groups:
        for c in clip_tree.get(key, []):
            ks = c["curve"]["m_Curve"]
            if ks:
                end = max(end, ks[-1]["time"])
    n = max(2, int(round(end * fps)) + 1)
    times = [min(end, i / fps) for i in range(n)]
    tracks = {}
    for key, kind in groups.items():
        for c in clip_tree.get(key, []):
            ks = c["curve"]["m_Curve"]
            if not ks:
                continue
            tr = tracks.setdefault(c["path"], {})
            if kind == "rotation":
                vals = []
                prev = None
                for t in times:
                    q = sample_curve(ks, t, "xyzw")
                    ln = math.sqrt(sum(v * v for v in q)) or 1.0
                    q = [v / ln for v in q]
                    q = list(cv_quat(q))
                    if prev and sum(a * b for a, b in zip(prev, q)) < 0:
                        q = [-v for v in q]  # 保持連續，避免插值繞遠路
                    vals.append(q)
                    prev = q
                tr["rotation"] = vals
            elif kind == "euler":
                vals = [list(cv_quat(euler_zxy_to_quat(*sample_curve(ks, t, "xyz")))) for t in times]
                tr["rotation"] = vals
            elif kind == "translation":
                tr["translation"] = [list(cv_pos(sample_curve(ks, t, "xyz"))) for t in times]
            else:
                tr["scale"] = [sample_curve(ks, t, "xyz") for t in times]
    return end, times, tracks


# ---------------- glTF 寫出 ----------------

class GltfBuilder:
    def __init__(self):
        self.bin = bytearray()
        self.g = {"asset": {"version": "2.0", "generator": "wcat rig exporter"},
                  "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [], "skins": [],
                  "accessors": [], "bufferViews": [], "buffers": [], "materials": [], "textures": [],
                  "images": [], "samplers": [], "animations": []}

    def view(self, data: bytes, target=None):
        while len(self.bin) % 4:
            self.bin.append(0)
        bv = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target:
            bv["target"] = target
        self.bin += data
        self.g["bufferViews"].append(bv)
        return len(self.g["bufferViews"]) - 1

    def accessor(self, values, ctype, typ, target=None, minmax=False, normalized=False):
        fmt = {5126: "f", 5121: "B", 5123: "H", 5125: "I"}[ctype]
        flat = [x for v in values for x in (v if isinstance(v, (list, tuple)) else (v,))]
        data = struct.pack(f"<{len(flat)}{fmt}", *flat)
        acc = {"bufferView": self.view(data, target), "componentType": ctype, "count": len(values), "type": typ}
        if normalized:
            acc["normalized"] = True
        if minmax:
            width = len(values[0]) if isinstance(values[0], (list, tuple)) else 1
            cols = [[v[i] if width > 1 else v for v in values] for i in range(width)]
            acc["min"] = [min(c) for c in cols]
            acc["max"] = [max(c) for c in cols]
        self.g["accessors"].append(acc)
        return len(self.g["accessors"]) - 1

    def write(self, path: Path):
        g = {k: v for k, v in self.g.items() if v != []}
        while len(self.bin) % 4:
            self.bin.append(0)
        g["buffers"] = [{"byteLength": len(self.bin)}]
        js = json.dumps(g, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        js += b" " * ((4 - len(js) % 4) % 4)
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        with open(path, "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, total))
            f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
            f.write(struct.pack("<II", len(self.bin), 0x004E4942) + self.bin)


def export_character(prefab_path: Path, anim_paths: list[Path], out_path: Path, fps: int, include_m: bool,
                     include_hidden: bool = False):
    env = UnityPy.load(str(prefab_path))
    objs = {o.path_id: o for o in env.objects}
    trees = {}

    def tree(pid):
        if pid not in trees:
            trees[pid] = objs[pid].read_typetree()
        return trees[pid]

    transforms = [pid for pid, o in objs.items() if o.type.name == "Transform"]
    root_tf = next(pid for pid in transforms if tree(pid)["m_Father"]["m_PathID"] == 0)
    go_name = lambda tf: tree(tree(tf)["m_GameObject"]["m_PathID"])["m_Name"]

    def active(tf):
        """GameObject 自己和所有上層都開著才算（關著的是技能 / 表情切換用的替換網格）"""
        while tf in objs:
            if not tree(tree(tf)["m_GameObject"]["m_PathID"]).get("m_IsActive", 1):
                return False
            tf = tree(tf)["m_Father"]["m_PathID"]
        return True

    b = GltfBuilder()
    g = b.g
    node_of = {}   # transform path_id -> node index
    path_of = {}   # 相對根節點的路徑（AnimationClip 用）

    def add_node(tf, rel):
        t = tree(tf)
        p, r, s = t["m_LocalPosition"], t["m_LocalRotation"], t["m_LocalScale"]
        node = {"name": go_name(tf)}
        tp = cv_pos((p["x"], p["y"], p["z"]))
        rq = cv_quat((r["x"], r["y"], r["z"], r["w"]))
        sc = (s["x"], s["y"], s["z"])
        if any(abs(v) > 1e-9 for v in tp):
            node["translation"] = list(tp)
        if any(abs(a - b_) > 1e-9 for a, b_ in zip(rq, (0, 0, 0, 1))):
            node["rotation"] = list(rq)
        if any(abs(v - 1) > 1e-9 for v in sc):
            node["scale"] = list(sc)
        idx = len(g["nodes"])
        g["nodes"].append(node)
        node_of[tf] = idx
        path_of[rel] = idx
        kids = []
        for c in t["m_Children"]:
            cpid = c["m_PathID"]
            if cpid not in objs:
                continue
            name = go_name(cpid)
            if not include_m and (name == "Root_m" or name.endswith("_m") and name.startswith("body")):
                continue
            kids.append(add_node(cpid, f"{rel}/{name}" if rel else name))
        if kids:
            node["children"] = kids
        return idx

    g["scenes"][0]["nodes"] = [add_node(root_tf, "")]

    # ---- 材質 / 貼圖 ----
    mat_cache = {}

    def material(mat_ptr):
        pid = mat_ptr["m_PathID"]
        if pid in mat_cache:
            return mat_cache[pid]
        m = objs[pid].read()
        pbr = {"metallicFactor": 0.0, "roughnessFactor": 1.0}
        for name, env_tex in m.m_SavedProperties.m_TexEnvs:
            if name == "_MainTex" and env_tex.m_Texture.path_id:
                img = env_tex.m_Texture.read().image
                buf = BytesIO()
                img.save(buf, "PNG")
                if not g["samplers"]:
                    g["samplers"].append({"magFilter": 9729, "minFilter": 9987})
                g["images"].append({"name": m.m_Name, "mimeType": "image/png", "bufferView": b.view(buf.getvalue())})
                g["textures"].append({"sampler": 0, "source": len(g["images"]) - 1})
                pbr["baseColorTexture"] = {"index": len(g["textures"]) - 1}
        g["materials"].append({"name": m.m_Name, "pbrMetallicRoughness": pbr,
                               "extensions": {"KHR_materials_unlit": {}}})
        g.setdefault("extensionsUsed", ["KHR_materials_unlit"])
        mat_cache[pid] = len(g["materials"]) - 1
        return mat_cache[pid]

    # ---- 蒙皮網格 ----
    for pid, o in objs.items():
        if o.type.name != "SkinnedMeshRenderer":
            continue
        smr = o.read_typetree()
        tf = next(c["component"]["m_PathID"] for c in tree(smr["m_GameObject"]["m_PathID"])["m_Component"]
                  if objs.get(c["component"]["m_PathID"]) and objs[c["component"]["m_PathID"]].type.name == "Transform")
        if tf not in node_of:
            continue
        # 武器平常也是關的（攻擊時才開），但預覽要看得到，所以保留
        if not include_hidden and not active(tf) and not go_name(tf).lower().startswith("weapon"):
            print(f"  略過預設隱藏的網格 {go_name(tf)}（要的話加 --include-hidden）")
            continue
        mesh = objs[smr["m_Mesh"]["m_PathID"]].read()
        h = MeshHandler(mesh)
        h.process()
        pos = [cv_pos(v) for v in h.m_Vertices]
        nrm = [cv_pos(v) for v in h.m_Normals] if h.m_Normals else None
        uv = [(u, 1.0 - v) for u, v in h.m_UV0] if h.m_UV0 else None
        weights, joints = [], []
        for bi, bw in zip(h.m_BoneIndices, h.m_BoneWeights):
            # 有的模型每頂點只存 2 骨頭權重，補滿到 glTF 要求的 4 個
            bi, bw = (list(bi) + [0] * 4)[:4], (list(bw) + [0.0] * 4)[:4]
            tot = sum(bw) or 1.0
            weights.append([w / tot for w in bw])
            joints.append([i if w > 0 else 0 for i, w in zip(bi, bw)])
        attrs = {"POSITION": b.accessor(pos, 5126, "VEC3", 34962, minmax=True)}
        if nrm:
            attrs["NORMAL"] = b.accessor(nrm, 5126, "VEC3", 34962)
        if uv:
            attrs["TEXCOORD_0"] = b.accessor(uv, 5126, "VEC2", 34962)
        attrs["JOINTS_0"] = b.accessor(joints, 5123, "VEC4", 34962)
        attrs["WEIGHTS_0"] = b.accessor(weights, 5126, "VEC4", 34962)
        prims = []
        mats = smr["m_Materials"]
        for si, tris in enumerate(h.get_triangles()):
            idx = [i for a, b_, c in tris for i in (a, c, b_)]  # 反轉繞序
            prim = {"attributes": attrs, "indices": b.accessor(idx, 5125, "SCALAR", 34963)}
            if si < len(mats) and mats[si]["m_PathID"]:
                prim["material"] = material(mats[si])
            prims.append(prim)
        g["meshes"].append({"name": mesh.m_Name, "primitives": prims})
        bones = [node_of[bp["m_PathID"]] for bp in smr["m_Bones"]]
        ibm = b.accessor([cv_bindpose(m) for m in mesh.m_BindPose], 5126, "MAT4")
        skin = {"name": mesh.m_Name, "joints": bones, "inverseBindMatrices": ibm}
        if smr["m_RootBone"]["m_PathID"] in node_of:
            skin["skeleton"] = node_of[smr["m_RootBone"]["m_PathID"]]
        g["skins"].append(skin)
        node = g["nodes"][node_of[tf]]
        node["mesh"] = len(g["meshes"]) - 1
        node["skin"] = len(g["skins"]) - 1
        print(f"  網格 {mesh.m_Name}: {len(pos)} 頂點, {len(bones)} 骨頭")

    # ---- 動作 ----
    for ap in anim_paths:
        aenv = UnityPy.load(str(ap))
        for ao in aenv.objects:
            if ao.type.name != "AnimationClip":
                continue
            clip = ao.read_typetree()
            if clip.get("m_Compressed"):
                print(f"  ⚠️ {clip['m_Name']} 是壓縮曲線，略過")
                continue
            end, times, tracks = bake_clip(clip, fps)
            channels, samplers = [], []
            t_acc = b.accessor(times, 5126, "SCALAR", minmax=True)
            for path, tr in tracks.items():
                if path not in path_of:
                    continue
                for prop, vals in tr.items():
                    typ = "VEC4" if prop == "rotation" else "VEC3"
                    samplers.append({"input": t_acc, "output": b.accessor(vals, 5126, typ), "interpolation": "LINEAR"})
                    channels.append({"sampler": len(samplers) - 1, "target": {"node": path_of[path], "path": prop}})
            if channels:
                g["animations"].append({"name": clip["m_Name"], "channels": channels, "samplers": samplers})
                print(f"  動作 {clip['m_Name']}: {end:.2f}s, {len(channels)} 軌")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    b.write(out_path)
    return len(g["animations"])


def main():
    ap = argparse.ArgumentParser(description="白貓角色 -> 帶骨架與動作的 GLB")
    ap.add_argument("ids", nargs="*", help="角色 ID（8 位數），可多個")
    ap.add_argument("--anims", nargs="*", help="動作編號：00000001、00000000-00000019、00000013_s，或完整 bundle 名稱")
    ap.add_argument("--out", help="輸出資料夾（預設 export_dir/<ID>/）")
    ap.add_argument("--no-skill", action="store_true", help="不要自動找角色專屬（技能）動作")
    ap.add_argument("--include-m", action="store_true", help="一併輸出 body_m（Root_m 骨架的小模型）")
    ap.add_argument("--include-hidden", action="store_true", help="一併輸出 prefab 裡預設關閉的網格（替換用手型、變身等）")
    ap.add_argument("--update-index", action="store_true", help="先重新下載 Character / Action 索引")
    ap.add_argument("--list-anims", action="store_true", help="列出索引裡所有共用動作後結束")
    args = ap.parse_args()
    if not args.ids and not (args.list_anims or args.update_index):
        ap.error("請給角色 ID")

    cfg = load_config()
    dl_dir = resolve(cfg["download_dir"])
    dl_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (unity3d-downloader/1.0)"})
    dl = lambda name: download(session, cfg["base_url"], name, dl_dir, cfg["timeout_sec"], cfg["retries"])

    if args.update_index:
        for key in ("character_index", "action_index"):
            update_index(session, cfg["base_url"], resolve(cfg[key]), cfg["timeout_sec"])

    index_names = load_index_names(resolve(cfg["character_index"]), ANIM_PAT)
    action_names = load_index_names(resolve(cfg["action_index"]), ACTION_PAT)
    if args.list_anims:
        for n in index_names:
            print(n)
        print(f"共 {len(index_names)} 個")
        return
    anim_names = parse_anim_spec(args.anims or [cfg["default_anims"]], index_names)
    print(f"共用動作 bundle：{len(anim_names)} 個")

    for cid in args.ids:
        print(f"=== {cid} ===")
        prefab = dl(f"Character_Prefabs_Player_ply_{cid}_prefab")
        if not prefab:
            print("  ❌ 找不到 prefab bundle")
            continue
        names = list(anim_names)
        if not args.no_skill:
            names += [n for n in find_skill_anims(cid, action_names, dl) if n not in names]
        anim_paths = [p for p in (dl(n) for n in names) if p]
        out_dir = Path(args.out) if args.out else find_char_dir(resolve(cfg["export_dir"]), cid)
        out = out_dir / f"ply_{cid}_rig.glb"
        n = export_character(prefab, anim_paths, out, cfg["sample_fps"], args.include_m, args.include_hidden)
        print(f"  ✅ {out}（{n} 段動作）")


if __name__ == "__main__":
    sys.exit(main())
