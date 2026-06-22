"""
拾掇猫 · 核心逻辑模块
纯逻辑，无 I/O。GUI 和 CLI 共用。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".svg", ".ico"}
VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".m4v", ".3gp", ".ts"}
CBZ_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

RE_GIF_DUP   = re.compile(r"^(.+?)(\d+)\s*\((\d+)\)$")
RE_GIF_ALL   = re.compile(r"^GIF\(ALL\)_(.+)$")
RE_GIF_EXTRA = re.compile(r"^GIF\(Extra\)_(.+)$")
RE_GIF_PLAIN = re.compile(r"^(.+?)(\d+)$")
RE_FOLDER    = re.compile(r"^(?:\[[^\]]*?\])?\s*([^_]+)")
RE_DUP       = re.compile(r"^(.+?)\s*\((\d+)\)$")
RE_PIXIV     = re.compile(r"^Pixiv_(\d+)$")
RE_INVALID   = re.compile(r'[<>:"/\\|?*]')
RE_BRACKET   = re.compile(r'\[([^\]]+)\]')
RE_PAREN     = re.compile(r'\(([^)]+)\)')
RE_TITLE     = re.compile(r'^\[[^\]]+\]\s*')

# 回溯文件名
MAP_EXTRACT  = ".nyako-extract-revert.json"
MAP_GIF      = ".nyako-gif-revert.json"
MAP_DEDUP    = "dedup-map.json"
MAP_SPLIT    = ".nyako-split-revert.json"
MAP_CBZ      = ".nyako-cbz-revert.json"
MAP_CLASSIFY = ".nyako-classify-revert.json"

GIF_GROUP_ORDER = {"dup": 0, "plain": 1, "gif_all": 2, "gif_extra": 3}


# ═══════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════

@dataclass
class Result:
    """统一返回结构"""
    success: int = 0
    skipped: int = 0
    deleted: int = 0
    renamed: int = 0
    mapping: dict | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class GifEntry:
    path: Path
    group: str
    base_name: str
    num: int
    dup_marker: int | None = None
    keep: bool = True


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def parse_metadata(name: str) -> str | None:
    brackets = RE_BRACKET.findall(name)
    if not brackets:
        return None
    for part in brackets:
        parens = RE_PAREN.findall(part)
        if parens:
            return parens[0].strip()
    return brackets[0].strip()


def extract_title(name: str) -> str:
    return RE_TITLE.sub("", name).strip()


def extract_char_name(folder: Path) -> str:
    raw = folder.name
    m = RE_FOLDER.match(raw)
    if m and m.group(1).strip():
        return RE_INVALID.sub("", m.group(1).strip())
    return RE_INVALID.sub("", raw.strip())


def classify_ext(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in IMAGE_EXT: return "image"
    if ext in VIDEO_EXT: return "video"
    return None


def is_manga_folder(path: Path) -> bool:
    try:
        return any(f.suffix.lower() in CBZ_IMAGE_EXT for f in path.iterdir() if f.is_file())
    except Exception:
        return False


def _save_mapping(folder: Path, map_file: str, mapping: dict):
    mapping.setdefault("timestamp", datetime.now().isoformat())
    with open(folder / map_file, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)


def _walk_dirs(parent: Path) -> dict[int, list[Path]]:
    """递归收集子目录，按深度分组"""
    by_depth: dict[int, list[Path]] = {}
    def _walk(entry, depth):
        p = Path(entry.path)
        by_depth.setdefault(depth, []).append(p)
        try:
            for e in os.scandir(p):
                if e.is_dir():
                    _walk(e, depth + 1)
        except PermissionError:
            pass
    for e in os.scandir(parent):
        if e.is_dir():
            _walk(e, 1)
    return by_depth


def _cleanup_empty_dirs(by_depth: dict[int, list[Path]]) -> list[str]:
    """从深到浅删除空目录，返回已删路径列表"""
    removed = []
    for depth in sorted(by_depth, reverse=True):
        for d in by_depth[depth]:
            try:
                d.rmdir()
                removed.append(str(d))
            except OSError:
                pass
    return removed


def _resolve_destinations(files: list[Path], dest_root: Path, reserved: set[str], source_root: Path | None = None) -> list[tuple[Path, Path, str]]:
    """批量计算目标路径，碰撞加序号"""
    src_root = source_root or dest_root
    plan = []
    for src in files:
        rel = src.relative_to(src_root)
        prefix = "_".join(rel.parts[:-1])
        stem, suffix = rel.stem, rel.suffix
        name = f"{prefix}_{stem}{suffix}"
        if name in reserved:
            c = 1
            while f"{prefix}_{stem}_{c}{suffix}" in reserved:
                c += 1
            name = f"{prefix}_{stem}_{c}{suffix}"
            plan.append((src, dest_root / name, "collision"))
        else:
            plan.append((src, dest_root / name, "ok"))
        reserved.add(name)
    return plan


def _execute_moves(plan: list[tuple[Path, Path, str]], on_progress: Callable | None = None) -> tuple[int, int, int, list]:
    """执行移动计划。返回 (成功, 碰撞, 失败, [(src,dst)])"""
    moved = collisions = fails = 0
    records = []
    total = len(plan)
    for i, (src, dest, tag) in enumerate(plan):
        try:
            src.rename(dest)
            moved += 1
            records.append([str(src), str(dest)])
            if tag == "collision": collisions += 1
        except OSError:
            fails += 1
        if on_progress:
            on_progress(i + 1, total, dest.name, tag)
    return moved, collisions, fails, records


# ═══════════════════════════════════════════════════════════
# 1. 子文件夹提取
# ═══════════════════════════════════════════════════════════

def extract_process(folder: Path, on_progress: Callable | None = None) -> Result:
    if not folder.is_dir():
        return Result()
    # 扫描
    files_to_move = []
    root_names: set[str] = set()
    for entry in os.scandir(folder):
        if entry.is_dir():
            for f in Path(entry.path).rglob("*"):
                if f.is_file():
                    files_to_move.append(f)
        elif entry.is_file():
            root_names.add(entry.name)
    if not files_to_move:
        return Result()
    subdirs = _walk_dirs(folder)
    plan = _resolve_destinations(files_to_move, folder, root_names, source_root=folder)
    moved, collisions, fails, records = _execute_moves(plan, on_progress)
    deleted_dirs = _cleanup_empty_dirs(subdirs)
    mapping = {"tool": "extract", "folder": str(folder), "moves": records, "deleted_dirs": deleted_dirs}
    _save_mapping(folder, MAP_EXTRACT, mapping)
    return Result(success=moved, renamed=collisions, extra={"dirs_cleaned": len(deleted_dirs)}, mapping=mapping)


# ═══════════════════════════════════════════════════════════
# 2. GIF 统一重命名
# ═══════════════════════════════════════════════════════════

def _gif_classify(path: Path) -> GifEntry | None:
    stem = path.stem
    if m := RE_GIF_DUP.match(stem):
        return GifEntry(path, "dup", m[1], int(m[2]), int(m[3]))
    if m := RE_GIF_ALL.match(stem):
        if pm := RE_GIF_PLAIN.match(m[1]):
            return GifEntry(path, "gif_all", pm[1], int(pm[2]))
    if m := RE_GIF_EXTRA.match(stem):
        if pm := RE_GIF_PLAIN.match(m[1]):
            return GifEntry(path, "gif_extra", pm[1], int(pm[2]))
    if m := RE_GIF_PLAIN.match(stem):
        return GifEntry(path, "plain", m[1], int(m[2]))
    return None


def gif_process(folder: Path, char_name: str, on_progress: Callable | None = None) -> Result:
    if not folder.is_dir():
        return Result()
    entries: list[GifEntry] = []
    skipped = 0
    for e in os.scandir(folder):
        if not e.is_file(): continue
        if r := _gif_classify(Path(e.path)): entries.append(r)
        else: skipped += 1
    if not entries:
        return Result(skipped=skipped)

    plain_index: dict[tuple[str, int], GifEntry] = {}
    for e in entries:
        if e.group == "plain": plain_index[(e.base_name, e.num)] = e

    # 去重
    deleted = 0
    deleted_names = []
    for e in entries:
        if e.group != "dup": continue
        key = (e.base_name, e.num)
        if key in plain_index:
            try:
                if file_hash(e.path) == file_hash(plain_index[key].path):
                    e.keep = False
                    deleted += 1
                    deleted_names.append(e.path.name)
                    e.path.unlink()
            except OSError:
                pass

    kept = sorted([e for e in entries if e.keep], key=lambda e: (GIF_GROUP_ORDER.get(e.group, 99), e.num))
    if not kept:
        return Result(deleted=deleted, skipped=skipped)

    # 清理残留
    for stale in folder.glob("__rename_*"):
        try: stale.unlink()
        except OSError: pass

    # 两阶段重命名
    temp_map: list[tuple[Path, Path]] = []
    for i, e in enumerate(kept):
        tmp = folder / f"__rename_{i:04d}{e.path.suffix}"
        try:
            e.path.rename(tmp)
            temp_map.append((tmp, e.path))
        except OSError:
            pass

    renamed = 0
    rename_records = {}
    for i, (tmp, orig) in enumerate(temp_map):
        if not tmp.exists(): continue
        new_name = f"{char_name}{i + 1}{tmp.suffix}"
        try:
            tmp.rename(folder / new_name)
            rename_records[orig.name] = new_name
            renamed += 1
            if on_progress: on_progress(i + 1, len(temp_map), new_name, "ok")
        except OSError:
            pass

    if rename_records or deleted_names:
        mapping = {"tool": "gif-rename", "folder": str(folder), "renames": rename_records, "deleted": deleted_names}
        _save_mapping(folder, MAP_GIF, mapping)
    return Result(success=len(kept), deleted=deleted, renamed=renamed, skipped=skipped, mapping=mapping if (rename_records or deleted_names) else None)


# ═══════════════════════════════════════════════════════════
# 3. (n) 标记去重
# ═══════════════════════════════════════════════════════════

def dedup_process(folder: Path, on_progress: Callable | None = None) -> Result:
    if not folder.is_dir():
        return Result()
    stem_index: dict[str, Path] = {}
    candidates: list[tuple[Path, str, int]] = []
    for f in folder.iterdir():
        if not f.is_file(): continue
        stem_index[f.stem] = f
        if m := RE_DUP.match(f.stem):
            candidates.append((f, m[1], int(m[2])))
    if not candidates:
        return Result()

    deleted = renamed = skipped = 0
    rename_records = {}
    deleted_names = []
    next_n = 1
    for f in folder.iterdir():
        if not f.is_file(): continue
        if m := RE_PIXIV.match(f.stem):
            next_n = max(next_n, int(m[1]) + 1)

    for i, (fp, base_stem, marker) in enumerate(candidates):
        if on_progress: on_progress(i + 1, len(candidates), fp.name, "ok")
        base = stem_index.get(base_stem)
        if base is None:
            name = f"Pixiv_{next_n:03d}{fp.suffix}"
            try:
                fp.rename(folder / name)
                rename_records[fp.name] = name
                renamed += 1
                next_n += 1
            except OSError:
                skipped += 1
            continue
        try:
            if file_hash(fp) == file_hash(base):
                fp.unlink()
                deleted += 1
                deleted_names.append(fp.name)
            else:
                name = f"Pixiv_{next_n:03d}{fp.suffix}"
                fp.rename(folder / name)
                rename_records[fp.name] = name
                renamed += 1
                next_n += 1
        except OSError:
            skipped += 1

    if rename_records or deleted_names:
        mapping = {"tool": "dedup", "folder": str(folder), "renamed": rename_records, "deleted": deleted_names}
        _save_mapping(folder, MAP_DEDUP, mapping)
    return Result(deleted=deleted, renamed=renamed, skipped=skipped, mapping=mapping if (rename_records or deleted_names) else None)


# ═══════════════════════════════════════════════════════════
# 4. 去重还原
# ═══════════════════════════════════════════════════════════

def restore_process(folder: Path) -> Result:
    map_path = folder / MAP_DEDUP
    if not map_path.exists():
        return Result()
    with open(map_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    renamed = mapping.get("renamed", {})
    deleted_list = mapping.get("deleted", [])
    restored = 0
    failed = 0
    for orig, new in renamed.items():
        new_path, orig_path = folder / new, folder / orig
        if new_path.exists() and not orig_path.exists():
            try:
                new_path.rename(orig_path)
                restored += 1
            except OSError:
                failed += 1
    try:
        map_path.unlink()
    except OSError:
        pass
    return Result(success=restored, deleted=len(deleted_list), skipped=failed)


# ═══════════════════════════════════════════════════════════
# 5. 图片视频分离
# ═══════════════════════════════════════════════════════════

def split_process(folder: Path, on_progress: Callable | None = None) -> Result:
    if not folder.is_dir():
        return Result()
    images, videos = [], []
    root_names: set[str] = set()
    for entry in os.scandir(folder):
        if entry.is_dir():
            for f in Path(entry.path).rglob("*"):
                if f.is_file():
                    kind = classify_ext(f)
                    if kind == "image": images.append(f)
                    elif kind == "video": videos.append(f)
        elif entry.is_file():
            kind = classify_ext(Path(entry.path))
            if kind == "image": root_names.add(entry.name)
            elif kind == "video":
                videos.append(Path(entry.path))
                root_names.add(entry.name)
    if not videos:
        return Result()

    if not images:
        # 纯视频：只提取嵌套的
        nested = [v for v in videos if v.parent != folder]
        if not nested:
            return Result()
        plan = _resolve_destinations(nested, folder, root_names, source_root=folder)
        moved, _, _, records = _execute_moves(plan, on_progress)
        mapping = {"tool": "split", "folder": str(folder), "vid_moves": records}
        _save_mapping(folder, MAP_SPLIT, mapping)
        return Result(success=moved, mapping=mapping, extra={"mode": "self"})
    else:
        # 混合：视频提取到 _视频
        vid_folder = folder.parent / f"{folder.name}_视频"
        vid_folder.mkdir(exist_ok=True)
        existing = {e.name for e in os.scandir(vid_folder) if e.is_file()}
        plan = _resolve_destinations(videos, vid_folder, existing, source_root=folder)
        moved, _, _, records = _execute_moves(plan, on_progress)
        mapping = {"tool": "split", "folder": str(folder), "vid_moves": records}
        _save_mapping(folder, MAP_SPLIT, mapping)
        return Result(success=moved, mapping=mapping, extra={"mode": "sibling", "vid_folder": str(vid_folder)})


# ═══════════════════════════════════════════════════════════
# 6. CBZ 打包
# ═══════════════════════════════════════════════════════════

def _comicinfo_xml(title: str, artist: str) -> bytes:
    from xml.dom import minidom
    root = ET.Element("ComicInfo")
    ET.SubElement(root, "Title").text = title
    ET.SubElement(root, "Writer").text = artist
    ET.SubElement(root, "Series").text = title
    ET.SubElement(root, "Manga").text = "Yes"
    return minidom.parseString(ET.tostring(root, "utf-8")).toprettyxml(indent="  ", encoding="utf-8")


def cbz_process(folder: Path, on_progress: Callable | None = None) -> Result:
    import tempfile
    name = folder.name
    artist = parse_metadata(name) or parse_metadata(folder.parent.name)
    if not artist:
        return Result(skipped=1)
    title = extract_title(name) or name
    cbz_name = f"[{artist}] {name}.cbz" if artist not in name else f"{name}.cbz"
    cbz_name = RE_INVALID.sub("_", cbz_name)
    cbz_path = folder.parent / cbz_name
    if cbz_path.exists():
        return Result(skipped=1)
    if on_progress: on_progress(1, 1, cbz_name, "ok")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_p = Path(tmp)
        for f in folder.rglob("*"):
            if f.is_file() and f.suffix.lower() in CBZ_IMAGE_EXT:
                dst = tmp_p / f.relative_to(folder)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
        (tmp_p / "ComicInfo.xml").write_bytes(_comicinfo_xml(title, artist))
        with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_STORED) as zf:
            for f in tmp_p.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(tmp_p))
    mapping = {"tool": "cbz", "folder": str(folder), "cbz": str(cbz_path), "artist": artist, "title": title}
    _save_mapping(folder.parent, MAP_CBZ, mapping)
    shutil.rmtree(folder)
    return Result(success=1, mapping=mapping)


# ═══════════════════════════════════════════════════════════
# 7. 按作者分类
# ═══════════════════════════════════════════════════════════

def classify_process(folder: Path, on_progress: Callable | None = None) -> Result:
    author_map: dict[str, Path] = {}
    for d in folder.iterdir():
        if d.is_dir():
            author = parse_metadata(d.name)
            if author and author not in author_map:
                author_map[author] = d
    moved = skipped = 0
    records = []
    for src in [f for f in folder.iterdir() if f.is_file()]:
        if on_progress: on_progress(moved + skipped + 1, 0, src.name, "ok")
        author = parse_metadata(src.stem)
        if not author:
            skipped += 1
            continue
        target = author_map.get(author)
        if not target:
            target = folder / f"[{author}]合集"
            target.mkdir(exist_ok=True)
            author_map[author] = target
        dest = target / src.name
        if dest.exists():
            c = 1
            while True:
                dest = target / f"{src.stem}_{c}{src.suffix}"
                if not dest.exists(): break
                c += 1
        try:
            shutil.move(str(src), str(dest))
            records.append([str(src), str(dest)])
            moved += 1
        except OSError:
            skipped += 1
    if records:
        mapping = {"tool": "classify", "folder": str(folder), "moves": records}
        _save_mapping(folder, MAP_CLASSIFY, mapping)
    return Result(success=moved, skipped=skipped, mapping=mapping if records else None)


# ═══════════════════════════════════════════════════════════
# 8. 操作回溯
# ═══════════════════════════════════════════════════════════

REVERT_REGISTRY = [
    (MAP_EXTRACT,  "子文件夹提取", "extract"),
    (MAP_GIF,      "GIF 重命名",   "gif-rename"),
    (MAP_DEDUP,    "(n) 去重",     "dedup"),
    (MAP_SPLIT,    "视频分离",     "split"),
    (MAP_CBZ,      "CBZ 打包",     "cbz"),
    (MAP_CLASSIFY, "按作者分类",   "classify"),
]


def revert_scan(work_dir: Path) -> list[tuple[Path, str, str, str, str, dict]]:
    """扫描工作目录下所有回溯文件。返回 [(map_path, label, tool_id, folder_name, ts, mapping)]"""
    items = []
    for map_file, label, tool_id in REVERT_REGISTRY:
        for d in work_dir.iterdir():
            if not d.is_dir(): continue
            mp = d / map_file
            if mp.exists():
                try:
                    with open(mp, "r", encoding="utf-8") as f: m = json.load(f)
                    items.append((mp, label, tool_id, d.name, m.get("timestamp", "?")[:16], m))
                except Exception: pass
        mp = work_dir / map_file
        if mp.exists():
            try:
                with open(mp, "r", encoding="utf-8") as f: m = json.load(f)
                items.append((mp, label, tool_id, work_dir.name, m.get("timestamp", "?")[:16], m))
            except Exception: pass
    return items


def revert_execute(items: list, on_progress: Callable | None = None) -> Result:
    total_files = total_dirs = 0
    for mp, label, tool_id, folder_name, ts, mapping in items:
        handler = REVERT_HANDLERS.get(tool_id)
        if not handler: continue
        files, dirs = handler(mapping, mp.parent)
        total_files += files
        total_dirs += dirs
        try: mp.unlink()
        except OSError: pass
        if on_progress: on_progress(0, 0, f"{label} — {folder_name}", "ok")
    return Result(success=total_files, extra={"dirs": total_dirs})


def _revert_moves(mapping: dict, keys: list[str]) -> int:
    files = 0
    for key in keys:
        for src_str, dst_str in mapping.get(key, []):
            dst, src = Path(dst_str), Path(src_str)
            if dst.exists():
                try:
                    src.parent.mkdir(parents=True, exist_ok=True)
                    dst.rename(src)
                    files += 1
                except OSError: pass
    return files


def _revert_renames(mapping: dict, folder: Path, key: str = "renames") -> int:
    restored = 0
    for orig, new in mapping.get(key, {}).items():
        new_path, orig_path = folder / new, folder / orig
        if new_path.exists() and not orig_path.exists():
            try:
                new_path.rename(orig_path)
                restored += 1
            except OSError: pass
    return restored


def revert_extract(m: dict, folder: Path) -> tuple[int, int]:
    return _revert_moves(m, ["moves"]), 0


def revert_gif_rename(m: dict, folder: Path) -> tuple[int, int]:
    return _revert_renames(m, Path(m.get("folder", folder))), 0


def revert_dedup(m: dict, folder: Path) -> tuple[int, int]:
    return _revert_renames(m, folder, "renamed"), 0


def revert_split(m: dict, folder: Path) -> tuple[int, int]:
    return _revert_moves(m, ["vid_moves", "img_moves"]), 0


def revert_cbz(m: dict, folder: Path) -> tuple[int, int]:
    cbz_path = Path(m.get("cbz", ""))
    orig = Path(m.get("folder", ""))
    if not cbz_path.exists(): return 0, 0
    try:
        orig.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(cbz_path, "r") as zf:
            for name in zf.namelist():
                if name != "ComicInfo.xml":
                    zf.extract(name, orig)
        cbz_path.unlink()
        return 1, 1
    except Exception:
        return 0, 0


def revert_classify(m: dict, folder: Path) -> tuple[int, int]:
    return _revert_moves(m, ["moves"]), 0


REVERT_HANDLERS = {
    "extract":     revert_extract,
    "gif-rename":  revert_gif_rename,
    "dedup":       revert_dedup,
    "split":       revert_split,
    "cbz":         revert_cbz,
    "classify":    revert_classify,
}
