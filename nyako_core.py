"""
拾掇猫
放在 Z:\aimanga 下双击运行，命令行菜单选择功能。
"""
import hashlib
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# ═══════════════════════════════════════════════════════════
# 共享工具
# ═══════════════════════════════════════════════════════════

C_RESET   = "\033[0m"
C_BOLD    = "\033[1m"
C_DIM     = "\033[2m"
C_GREEN   = "\033[32m"
C_YELLOW  = "\033[33m"
C_RED     = "\033[31m"
C_CYAN    = "\033[36m"
C_MAGENTA = "\033[35m"

TERM_WIDTH = shutil.get_terminal_size().columns
MAP_FILENAME = "dedup-map.json"
EXTRACT_MAP  = ".nyako-extract-revert.json"
GIF_MAP      = ".nyako-gif-revert.json"
SPLIT_MAP    = ".nyako-split-revert.json"
CBZ_MAP      = ".nyako-cbz-revert.json"
CLASSIFY_MAP = ".nyako-classify-revert.json"

DEDUP_MAP    = MAP_FILENAME


def bar(percent: float, width: int = 30) -> str:
    filled = int(width * percent)
    return f"{C_CYAN}{'█' * filled}{'░' * (width - filled)}{C_RESET} {percent * 100:5.1f}%"


def header(text: str):
    line = f" {text} "
    pad = max(0, (TERM_WIDTH - len(line)) // 2)
    print(f"\n{C_BOLD}{'─' * pad}{line}{'─' * (TERM_WIDTH - pad - len(line))}{C_RESET}\n")


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def wait_enter():
    input(f"\n{C_DIM}按 Enter 返回菜单...{C_RESET}")


def pick_targets(work_dir: Path, label: str = "") -> list[Path]:
    """
    选择目标文件夹。
    Enter     → 返回 work_dir 的所有直接子文件夹（批量模式）
    输入路径  → 返回 [Path]（单文件夹模式）
    输入 s    → 列出子文件夹，选号多选
    """
    subdirs = sorted([d for d in work_dir.iterdir() if d.is_dir()], key=lambda d: d.name)
    print(f"  {C_DIM}子文件夹:{C_RESET} {len(subdirs)} 个")
    print(f"  {C_CYAN}Enter{C_RESET} = 批量全部")
    print(f"  {C_CYAN}路径{C_RESET} = 指定单个文件夹")
    print(f"  {C_CYAN}s{C_RESET}    = 从列表勾选")
    choice = input(f"  {C_CYAN}> {C_RESET}").strip()

    if not choice:
        return subdirs

    if choice.lower() == "s":
        # 列表勾选模式
        for i, d in enumerate(subdirs, 1):
            print(f"  {C_BOLD}{i:>4}.{C_RESET} {d.name}")
        print(f"\n  {C_DIM}输入编号，空格分隔（如 1 3 5-8），Enter = 全选{C_RESET}")
        sel = input(f"  {C_CYAN}> {C_RESET}").strip()
        if not sel:
            return subdirs
        picked = []
        for part in sel.split():
            if "-" in part:
                try:
                    a, b = part.split("-", 1)
                    picked.extend(range(int(a), int(b) + 1))
                except ValueError:
                    pass
            else:
                try:
                    picked.append(int(part))
                except ValueError:
                    pass
        return [subdirs[i - 1] for i in picked if 1 <= i <= len(subdirs)]

    # 单文件夹模式
    p = Path(choice)
    if p.is_dir():
        return [p.resolve()]
    joined = work_dir / choice
    if joined.is_dir():
        return [joined.resolve()]
    print(f"  {C_RED}路径无效，使用批量模式{C_RESET}")
    return subdirs


def move_files_batch(plan: list, label: str = "") -> tuple[int, int, int, list]:
    """执行移动计划。返回 (移动数, 碰撞数, 失败数, [(src_str, dst_str)])"""
    moved = collisions = fails = 0
    records = []
    total = len(plan)
    for i, (src, dest, tag) in enumerate(plan):
        try:
            src.rename(dest)
            moved += 1
            records.append([str(src), str(dest)])
            if tag == "collision":
                collisions += 1
        except OSError:
            fails += 1
        percent = (i + 1) / total
        if percent >= 0.05 or i == total - 1 or i % max(1, total // 20) == 0 or fails > 0:
            status = (
                f"{C_GREEN}✓{C_RESET}" if tag == "ok"
                else f"{C_YELLOW}↻{C_RESET}" if tag == "collision"
                else f"{C_RED}✗{C_RESET}"
            )
            prefix = f"{label} " if label else ""
            sys.stdout.write(f"\r  {bar(percent)}  {prefix}{i + 1}/{total}  {status} {dest.name}")
            if fails > 0:
                sys.stdout.write(f"\n  {C_RED}FAIL: {src.name}{C_RESET}")
            sys.stdout.flush()
    if total > 0:
        print()
    return moved, collisions, fails, records


# ═══════════════════════════════════════════════════════════
# 1. 子文件夹提取
# ═══════════════════════════════════════════════════════════

def extract_scan_folder(parent: Path) -> tuple[list[Path], list[Path], set[str]]:
    files_to_move = []
    subdirs_by_depth: dict[int, list[Path]] = {}
    root_names: set[str] = set()

    for entry in os.scandir(parent):
        if entry.is_dir():
            extract_walk_sub(entry, parent, files_to_move, subdirs_by_depth, depth=1)
        elif entry.is_file():
            root_names.add(entry.name)

    all_subdirs = []
    for depth in sorted(subdirs_by_depth, reverse=True):
        all_subdirs.extend(subdirs_by_depth[depth])
    return files_to_move, all_subdirs, root_names


def extract_walk_sub(dir_entry, parent, files_out, dirs_out, depth):
    dir_path = Path(dir_entry.path)
    dirs_out.setdefault(depth, []).append(dir_path)
    try:
        for entry in os.scandir(dir_path):
            if entry.is_dir():
                extract_walk_sub(entry, parent, files_out, dirs_out, depth + 1)
            elif entry.is_file():
                files_out.append(Path(entry.path))
    except PermissionError:
        pass


def extract_resolve_destinations(files, parent, reserved, source_root=None):
    """
    批量计算目标路径。
    parent: 目标根目录（dest = parent / target_name）
    source_root: 前缀计算用的源根目录，默认等于 parent
    """
    if source_root is None:
        source_root = parent
    plan = []
    for src in files:
        rel = src.relative_to(source_root)
        dirs = rel.parts[:-1]
        prefix = "_".join(dirs)
        stem = rel.stem
        suffix = rel.suffix
        target_name = f"{prefix}_{stem}{suffix}"
        if target_name in reserved:
            counter = 1
            while True:
                target_name = f"{prefix}_{stem}_{counter}{suffix}"
                if target_name not in reserved:
                    break
                counter += 1
            reserved.add(target_name)
            plan.append((src, parent / target_name, "collision"))
        else:
            reserved.add(target_name)
            plan.append((src, parent / target_name, "ok"))
    return plan


def extract_in_folder(parent: Path) -> tuple[int, int, int, dict | None]:
    if not parent.is_dir():
        return 0, 0, 0, None
    files_to_move, all_subdirs, root_names = extract_scan_folder(parent)
    if not files_to_move:
        return 0, 0, 0, None

    plan = extract_resolve_destinations(files_to_move, parent, root_names)

    moved, collisions, fails, move_records = move_files_batch(plan)

    removed = 0
    deleted_dirs = []
    total_dirs = len(all_subdirs)
    for i, d in enumerate(all_subdirs):
        percent = (i + 1) / total_dirs if total_dirs else 0
        try:
            d.rmdir()
            removed += 1
            deleted_dirs.append(str(d))
            sys.stdout.write(f"\r  {bar(percent)}  清理 {i + 1}/{total_dirs}  (已删 {removed})")
            sys.stdout.flush()
        except OSError:
            pass
    if total_dirs > 0:
        print()

    # 保存回溯文件
    mapping = {
        "tool": "extract-to-parent",
        "timestamp": datetime.now().isoformat(),
        "folder": str(parent),
        "moves": move_records,
        "deleted_dirs": deleted_dirs,
    }
    map_path = parent / EXTRACT_MAP
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

    return moved, collisions, removed, mapping


# ═══════════════════════════════════════════════════════════
# 2. GIF 统一重命名
# ═══════════════════════════════════════════════════════════

RE_GIF_DUP       = re.compile(r"^(.+?)(\d+)\s*\((\d+)\)$")
RE_GIF_ALL       = re.compile(r"^GIF\(ALL\)_(.+)$")
RE_GIF_EXTRA     = re.compile(r"^GIF\(Extra\)_(.+)$")
RE_GIF_PLAIN     = re.compile(r"^(.+?)(\d+)$")
RE_FOLDER_NAME   = re.compile(r"^(?:\[[^\]]*?\])?\s*([^_]+)")
_INVALID_CHARS   = re.compile(r'[<>:"/\\|?*]')

GIF_GROUP_ORDER  = {"dup": 0, "plain": 1, "gif_all": 2, "gif_extra": 3}
GIF_GROUP_LABEL  = {"dup": "独有副本", "plain": "无前缀", "gif_all": "GIF(ALL)", "gif_extra": "GIF(Extra)"}


@dataclass
class GifEntry:
    path: Path
    group: str
    base_name: str
    num: int
    dup_marker: int | None = None
    keep: bool = True


def gif_extract_char_name(folder: Path) -> str:
    raw = folder.name
    m = RE_FOLDER_NAME.match(raw)
    if m:
        name = m.group(1).strip()
        if name:
            return _INVALID_CHARS.sub("", name)
    return _INVALID_CHARS.sub("", raw.strip())


def gif_classify(filepath: Path) -> GifEntry | None:
    stem = filepath.stem
    if m := RE_GIF_DUP.match(stem):
        return GifEntry(filepath, "dup", m[1], int(m[2]), int(m[3]))
    if m := RE_GIF_ALL.match(stem):
        if pm := RE_GIF_PLAIN.match(m[1]):
            return GifEntry(filepath, "gif_all", pm[1], int(pm[2]))
    if m := RE_GIF_EXTRA.match(stem):
        if pm := RE_GIF_PLAIN.match(m[1]):
            return GifEntry(filepath, "gif_extra", pm[1], int(pm[2]))
    if m := RE_GIF_PLAIN.match(stem):
        return GifEntry(filepath, "plain", m[1], int(m[2]))
    return None


def gif_process_folder(folder: Path, char_name: str) -> tuple[int, int, int, int]:
    if not folder.is_dir():
        return 0, 0, 0, 0

    entries: list[GifEntry] = []
    skipped = 0
    for e in os.scandir(folder):
        if not e.is_file():
            continue
        if r := gif_classify(Path(e.path)):
            entries.append(r)
        else:
            skipped += 1
    if not entries:
        return 0, 0, 0, skipped

    plain_index: dict[tuple[str, int], GifEntry] = {}
    for e in entries:
        if e.group == "plain":
            plain_index[(e.base_name, e.num)] = e

    group_counts = defaultdict(int)
    for e in entries:
        group_counts[e.group] += 1
    print(f"  {C_DIM}分类:{C_RESET}  ", end="")
    parts = [f"{GIF_GROUP_LABEL[g]}×{group_counts[g]}" for g in ("dup", "plain", "gif_all", "gif_extra") if group_counts[g]]
    print(", ".join(parts))
    if skipped:
        print(f"  {C_DIM}未识别:{C_RESET} {skipped}")
    print(f"  {C_DIM}角色名:{C_RESET} {C_BOLD}{char_name}{C_RESET}")

    deleted = 0
    deleted_names = []
    dup_files = [e for e in entries if e.group == "dup"]
    total_dup = len(dup_files)
    if total_dup > 0:
        print(f"  {C_DIM}去重比对{C_RESET} ", end="")
    for i, e in enumerate(dup_files):
        key = (e.base_name, e.num)
        percent = (i + 1) / total_dup
        sys.stdout.write(f"\r  {bar(percent)}  {i + 1}/{total_dup}")
        sys.stdout.flush()
        if key in plain_index:
            try:
                if file_hash(e.path) == file_hash(plain_index[key].path):
                    e.keep = False
                    deleted += 1
                    deleted_names.append(e.path.name)
                    e.path.unlink()
                    continue
            except OSError:
                pass
    if total_dup > 0:
        print()

    kept = [e for e in entries if e.keep]
    kept.sort(key=lambda e: (GIF_GROUP_ORDER.get(e.group, 99), e.num))
    total = len(kept)
    if total == 0:
        return 0, deleted, 0, skipped

    # 清理残留临时文件
    for stale in folder.glob("__rename_*"):
        try:
            stale.unlink()
        except OSError:
            pass

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
    renamed_total = len(temp_map)
    for i, (tmp, orig_path) in enumerate(temp_map):
        if not tmp.exists():
            continue
        new_name = f"{char_name}{i + 1}{tmp.suffix}"
        dest = folder / new_name
        percent = (i + 1) / renamed_total * 0.8 if renamed_total else 0
        sys.stdout.write(f"\r  {bar(percent)}  重命名 {i + 1}/{renamed_total}")
        sys.stdout.flush()
        try:
            tmp.rename(dest)
            rename_records[orig_path.name] = new_name
            renamed += 1
        except OSError:
            pass
    if total > 0:
        print()

    # 保存回溯文件
    if rename_records or deleted_names:
        mapping = {
            "tool": "gif-rename",
            "timestamp": datetime.now().isoformat(),
            "folder": str(folder),
            "renames": rename_records,
            "deleted": deleted_names,
        }
        map_path = folder / GIF_MAP
        with open(map_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)

    return total, deleted, renamed, skipped


# ═══════════════════════════════════════════════════════════
# 3. (n) 标记去重
# ═══════════════════════════════════════════════════════════

RE_EXTRACT_DUP = re.compile(r"^(.+?)\s*\((\d+)\)$")


def dedup_next_pixiv(folder: Path) -> int:
    max_n = 0
    for f in folder.iterdir():
        if not f.is_file():
            continue
        m = re.match(r"^Pixiv_(\d+)$", f.stem)
        if m:
            max_n = max(max_n, int(m[1]))
    return max_n + 1


def dedup_process_folder(folder: Path) -> tuple[int, int, int]:
    if not folder.is_dir():
        return 0, 0, 0

    stem_index: dict[str, Path] = {}
    dup_candidates: list[tuple[Path, str, str, int]] = []

    for f in folder.iterdir():
        if not f.is_file():
            continue
        stem_index[f.stem] = f
        m = RE_EXTRACT_DUP.match(f.stem)
        if m:
            dup_candidates.append((f, m.group(1), f.name, int(m.group(2))))

    if not dup_candidates:
        return 0, 0, 0

    deleted = 0
    renamed = 0
    skipped = 0
    mapping: dict = {"renamed": {}, "deleted": [], "timestamp": datetime.now().isoformat()}
    total = len(dup_candidates)
    next_n = dedup_next_pixiv(folder)

    for i, (fp, base_stem, orig_name, marker) in enumerate(dup_candidates):
        percent = (i + 1) / total
        sys.stdout.write(f"\r  {bar(percent)}  {i + 1}/{total}")
        sys.stdout.flush()

        base_file = stem_index.get(base_stem)
        if base_file is None:
            new_name = f"Pixiv_{next_n:03d}{fp.suffix}"
            dest = folder / new_name
            try:
                fp.rename(dest)
                mapping["renamed"][orig_name] = new_name
                renamed += 1
                next_n += 1
            except OSError:
                skipped += 1
            continue

        try:
            h1 = file_hash(fp)
            h2 = file_hash(base_file)
        except OSError:
            skipped += 1
            continue

        if h1 == h2:
            try:
                fp.unlink()
                mapping["deleted"].append(orig_name)
                deleted += 1
            except OSError:
                skipped += 1
        else:
            new_name = f"Pixiv_{next_n:03d}{fp.suffix}"
            dest = folder / new_name
            try:
                fp.rename(dest)
                mapping["renamed"][orig_name] = new_name
                renamed += 1
                next_n += 1
            except OSError:
                skipped += 1

    if total > 0:
        print()

    if mapping["renamed"] or mapping["deleted"]:
        map_path = folder / MAP_FILENAME
        with open(map_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        print(f"  {C_DIM}映射已保存:{C_RESET} {map_path.name}")

    return deleted, renamed, skipped


# ═══════════════════════════════════════════════════════════
# 4. 去重还原
# ═══════════════════════════════════════════════════════════

def restore_folder(folder: Path) -> tuple[int, int, int]:
    map_path = folder / MAP_FILENAME
    if not map_path.exists():
        return 0, 0, 0

    with open(map_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    renamed = mapping.get("renamed", {})
    deleted_list = mapping.get("deleted", [])
    timestamp = mapping.get("timestamp", "未知")

    print(f"  {C_DIM}操作时间:{C_RESET} {timestamp}")
    print(f"  {C_DIM}改名记录:{C_RESET} {len(renamed)} 条")
    print(f"  {C_DIM}删除记录:{C_RESET} {len(deleted_list)} 条")

    if deleted_list:
        print(f"\n  {C_YELLOW}以下文件已永久删除，无法恢复：{C_RESET}")
        for name in deleted_list:
            print(f"    {C_DIM}{name}{C_RESET}")

    if not renamed:
        return 0, len(deleted_list), 0

    restored = 0
    failed = 0
    total = len(renamed)

    for i, (orig_name, new_name) in enumerate(renamed.items()):
        percent = (i + 1) / total
        sys.stdout.write(f"\r  {bar(percent)}  {i + 1}/{total}")
        sys.stdout.flush()

        new_path = folder / new_name
        orig_path = folder / orig_name
        if not new_path.exists():
            print(f"\n  {C_YELLOW}文件不存在，跳过:{C_RESET} {new_name}")
            failed += 1
            continue
        if orig_path.exists():
            print(f"\n  {C_YELLOW}目标已存在，跳过:{C_RESET} {orig_name}")
            failed += 1
            continue
        try:
            new_path.rename(orig_path)
            restored += 1
        except OSError:
            print(f"\n  {C_RED}重命名失败:{C_RESET} {new_name} → {orig_name}")
            failed += 1
    if total > 0:
        print()

    if restored + failed == total:
        try:
            map_path.unlink()
            print(f"  {C_DIM}映射文件已删除{C_RESET}")
        except OSError:
            pass

    return restored, len(deleted_list), failed


# ═══════════════════════════════════════════════════════════
# 5. 图片视频分离
# ═══════════════════════════════════════════════════════════

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".svg", ".ico"}
VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".m4v", ".3gp", ".ts"}


def split_classify(filepath: Path) -> str | None:
    ext = filepath.suffix.lower()
    if ext in IMAGE_EXT: return "image"
    if ext in VIDEO_EXT: return "video"
    return None


def split_scan_folder(parent: Path):
    images, videos = [], []
    subdirs_by_depth: dict[int, list[Path]] = {}
    root_names = set()
    for entry in os.scandir(parent):
        if entry.is_dir():
            split_walk(entry, parent, images, videos, subdirs_by_depth, depth=1)
        elif entry.is_file():
            kind = split_classify(Path(entry.path))
            if kind == "image":
                root_names.add(entry.name)
            elif kind == "video":
                videos.append(Path(entry.path))
                root_names.add(entry.name)
    return images, videos, subdirs_by_depth, root_names


def split_walk(dir_entry, parent, images_out, videos_out, dirs_out, depth):
    dir_path = Path(dir_entry.path)
    dirs_out.setdefault(depth, []).append(dir_path)
    try:
        for entry in os.scandir(dir_path):
            if entry.is_dir():
                split_walk(entry, parent, images_out, videos_out, dirs_out, depth + 1)
            elif entry.is_file():
                kind = split_classify(Path(entry.path))
                if kind == "image": images_out.append(Path(entry.path))
                elif kind == "video": videos_out.append(Path(entry.path))
    except PermissionError:
        pass


def split_process_folder(folder: Path) -> tuple[int, int, bool]:
    """提取视频。返回 (视频移动数, 0=提取到自身, 1=提取到_视频, 是否有操作)"""
    if not folder.is_dir():
        return 0, 0, False
    images, videos, _subdirs, root_names = split_scan_folder(folder)
    if not videos:
        return 0, 0, False

    mapping = {
        "tool": "split-media",
        "timestamp": datetime.now().isoformat(),
        "folder": str(folder),
        "vid_moves": [],
    }

    if not images:
        mode = 0
        # 纯视频：只提取子文件夹中的视频，根目录不动
        nested = [v for v in videos if v.parent != folder]
        if not nested:
            return 0, 0, False
        print(f"  {C_YELLOW}纯视频{C_RESET}")
        plan = extract_resolve_destinations(nested, folder, root_names, source_root=folder)
        print(f"  {C_CYAN}视频{C_RESET} {len(plan)} 个 → {folder.name}")
        vid_moved, _, _, records = move_files_batch(plan, "视频")
        mapping["vid_moves"] = records
    else:
        mode = 1
        video_folder = folder.parent / f"{folder.name}_视频"
        video_folder.mkdir(exist_ok=True)
        existing = set()
        for entry in os.scandir(video_folder):
            if entry.is_file():
                existing.add(entry.name)
        plan = extract_resolve_destinations(videos, video_folder, existing, source_root=folder)
        print(f"  {C_CYAN}视频{C_RESET} {len(plan)} 个 → {video_folder.name}")
        vid_moved, _, _, records = move_files_batch(plan, "视频")
        mapping["vid_moves"] = records

    map_path = folder / SPLIT_MAP
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    print(f"  {C_DIM}回溯文件已保存{C_RESET}")

    return vid_moved, mode, True


# ═══════════════════════════════════════════════════════════
# 6. 统一操作回溯
# ═══════════════════════════════════════════════════════════

REVERT_REGISTRY = [
    (EXTRACT_MAP, "子文件夹提取", "extract-to-parent"),
    (GIF_MAP,     "GIF 重命名",    "gif-rename"),
    (DEDUP_MAP,   "(n) 去重",      "dedup-duplicates"),
    (SPLIT_MAP,   "图片视频分离",  "split-media"),
]


def revert_extract(mapping: dict, _folder: Path) -> tuple[int, int]:
    """还原 extract-to-parent：move 文件回去 + 重建目录"""
    files = 0
    for src_str, dst_str in mapping.get("moves", []):
        dst = Path(dst_str)
        src = Path(src_str)
        if dst.exists():
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                dst.rename(src)
                files += 1
            except OSError:
                pass
    dirs = 0
    for d_str in mapping.get("deleted_dirs", []):
        Path(d_str).mkdir(parents=True, exist_ok=True)
        dirs += 1
    return files, dirs


def revert_gif(mapping: dict, _folder: Path) -> tuple[int, int]:
    """还原 gif-rename：重命名回去"""
    folder = Path(mapping["folder"])
    restored = 0
    for orig_name, new_name in mapping.get("renames", {}).items():
        new_path = folder / new_name
        orig_path = folder / orig_name
        if new_path.exists() and not orig_path.exists():
            try:
                new_path.rename(orig_path)
                restored += 1
            except OSError:
                pass
    deleted = len(mapping.get("deleted", []))
    return restored, deleted


def revert_dedup(mapping: dict, folder: Path) -> tuple[int, int]:
    """还原 dedup-duplicates：Pixiv_NNN → 原名"""
    restored = 0
    for orig_name, new_name in mapping.get("renamed", {}).items():
        new_path = folder / new_name
        orig_path = folder / orig_name
        if new_path.exists() and not orig_path.exists():
            try:
                new_path.rename(orig_path)
                restored += 1
            except OSError:
                pass
    deleted = len(mapping.get("deleted", []))
    return restored, deleted


def revert_split(mapping: dict, _folder: Path) -> tuple[int, int]:
    """还原 split-media：move 视频回去"""
    all_moves = mapping.get("img_moves", []) + mapping.get("vid_moves", [])
    files = 0
    for src_str, dst_str in all_moves:
        dst = Path(dst_str)
        src = Path(src_str)
        if dst.exists():
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                dst.rename(src)
                files += 1
            except OSError:
                pass
    return files, 0

# ============================================================
# CBZ  & 
# ============================================================

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}

CBZ_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

def parse_metadata(name: str) -> str | None:
    """从方括号提取作者：优先圆括号内，否则第一个方括号"""
    brackets = re.findall(r'\\[([^\\]]+)\\]', name)
    if not brackets:
        return None
    for part in brackets:
        parens = re.findall(r'\\(([^)]+)\\)', part)
        if parens:
            return parens[0].strip()
    return brackets[0].strip()

def extract_title(name: str) -> str:
    """移除第一个方括号组及紧随空格"""
    return re.sub(r'^\\[[^\\]]+\\]\\s*', '', name).strip()

def is_manga_folder(path: Path) -> bool:
    try:
        return any(
            f.suffix.lower() in CBZ_IMAGE_EXT
            for f in path.iterdir() if f.is_file()
        )
    except Exception:
        return False

def create_comicinfo_xml(title: str, artist: str) -> bytes:
    import xml.etree.ElementTree as ET
    from xml.dom import minidom
    root = ET.Element('ComicInfo')
    ET.SubElement(root, 'Title').text = title
    ET.SubElement(root, 'Writer').text = artist
    ET.SubElement(root, 'Series').text = title
    ET.SubElement(root, 'Manga').text = 'Yes'
    rough = ET.tostring(root, 'utf-8')
    return minidom.parseString(rough).toprettyxml(indent="  ", encoding='utf-8')

def cbz_process_folder(folder: Path) -> tuple[bool, str | None, dict | None]:
    """打包文件夹为 CBZ。返回 (成功, cbz路径, 回溯映射)"""
    import zipfile, tempfile
    folder_name = folder.name
    parent_name = folder.parent.name

    artist = parse_metadata(folder_name) or parse_metadata(parent_name)
    if not artist:
        return False, None, None

    title = extract_title(folder_name) or folder_name

    cbz_name = f"[{artist}] {folder_name}.cbz" if artist not in folder_name else f"{folder_name}.cbz"
    cbz_name = re.sub(r'[\\\\/:*?"<>|]', '_', cbz_name)
    cbz_path = folder.parent / cbz_name

    if cbz_path.exists():
        return False, str(cbz_path), None

    print(f"  打包: {cbz_name}  (作者: {artist})")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for f in folder.rglob('*'):
            if f.is_file() and f.suffix.lower() in CBZ_IMAGE_EXT:
                rel = f.relative_to(folder)
                dst = tmp / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy2(f, dst)

        xml_content = create_comicinfo_xml(title, artist)
        (tmp / 'ComicInfo.xml').write_bytes(xml_content)

        with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_STORED) as zf:
            for f in tmp.rglob('*'):
                if f.is_file():
                    zf.write(f, f.relative_to(tmp))

    mapping = {
        "tool": "cbz-pack",
        "timestamp": datetime.now().isoformat(),
        "folder": str(folder),
        "cbz": str(cbz_path),
        "artist": artist,
        "title": title,
    }
    map_path = folder.parent / CBZ_MAP
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

    # 删除原文件夹
    import shutil
    shutil.rmtree(folder)
    print(f"  完成: {cbz_name}")

    return True, str(cbz_path), mapping

def classify_build_author_map(root_dir: Path) -> dict[str, Path]:
    """扫描现有文件夹，建立作者→路径映射"""
    author_map = {}
    for d in root_dir.iterdir():
        if not d.is_dir():
            continue
        author = parse_metadata(d.name)
        if author:
            if author in author_map:
                print(f"  警告: 作者 [{author}] 已有文件夹 {author_map[author].name}")
            else:
                author_map[author] = d
    return author_map

def classify_move_file(src: Path, target_dir: Path) -> Path | None:
    """移动文件，碰撞加后缀。返回目标路径"""
    dest = target_dir / src.name
    if dest.exists():
        stem, suffix = src.stem, src.suffix
        counter = 1
        while True:
            dest = target_dir / f"{stem}_{counter}{suffix}"
            if not dest.exists():
                break
            counter += 1
    import shutil
    shutil.move(str(src), str(dest))
    return dest

def classify_process_folder(root_dir: Path) -> tuple[int, int, list]:
    """按作者分类根目录下所有文件。返回 (移动数, 跳过数, [(src, dst)])"""
    author_map = classify_build_author_map(root_dir)
    records = []
    moved = skipped = 0

    files = [f for f in root_dir.iterdir() if f.is_file()]
    for src in files:
        author = parse_metadata(src.stem)
        if not author:
            skipped += 1
            continue

        target_dir = author_map.get(author)
        if not target_dir:
            target_dir = root_dir / f"[{author}]\u5408\u96c6"
            target_dir.mkdir(exist_ok=True)
            author_map[author] = target_dir
            print(f"  \u521b\u5efa: {target_dir.name}")

        try:
            dest = classify_move_file(src, target_dir)
            records.append([str(src), str(dest)])
            moved += 1
            print(f"  \u79fb\u52a8: {src.name} \u2192 {target_dir.name}/" )
        except Exception as e:
            print(f"  \u5931\u8d25: {src.name} - {e}")
            skipped += 1

    if records:
        mapping = {
            "tool": "classify",
            "timestamp": datetime.now().isoformat(),
            "folder": str(root_dir),
            "moves": records,
        }
        map_path = root_dir / CLASSIFY_MAP
        with open(map_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        print(f"  \u56de\u6eaf\u6587\u4ef6\u5df2\u4fdd\u5b58")

    return moved, skipped, records

def revert_cbz(mapping: dict, _folder: Path) -> tuple[int, int]:
    """\u8fd8\u539f CBZ\u6253\u5305\uff1a\u4ece .cbz \u89e3\u538b\u56de\u539f\u6587\u4ef6\u5939"""
    import zipfile
    cbz_path = Path(mapping.get("cbz", ""))
    orig_folder = Path(mapping.get("folder", ""))
    if not cbz_path.exists():
        return 0, 0
    try:
        orig_folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(cbz_path, 'r') as zf:
            for name in zf.namelist():
                if name != "ComicInfo.xml":
                    zf.extract(name, orig_folder)
        cbz_path.unlink()
        return 1, 1
    except Exception:
        return 0, 0

def revert_classify(mapping: dict, _folder: Path) -> tuple[int, int]:
    """\u8fd8\u539f\u5206\u7c7b\uff1a\u628a\u6587\u4ef6\u79fb\u56de\u539f\u4f4d"""
    files = 0
    for src_str, dst_str in mapping.get("moves", []):
        dst = Path(dst_str)
        src = Path(src_str)
        if dst.exists():
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                dst.rename(src)
                files += 1
            except OSError:
                pass
    return files, 0


REVERT_HANDLERS = {
    "extract-to-parent": revert_extract,
    "gif-rename":        revert_gif,
    "dedup-duplicates":  revert_dedup,
    "split-media":       revert_split,
    "cbz-pack":          revert_cbz,
    "classify":          revert_classify,
}


