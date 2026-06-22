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


def extract_main(script_dir: Path):
    header(f"1. 子文件夹提取")
    print(f"  {C_DIM}工作目录:{C_RESET} {script_dir}")

    targets = pick_targets(script_dir)
    if not targets:
        print(f"\n  {C_YELLOW}没有找到子文件夹。{C_RESET}")
        wait_enter()
        return

    print(f"  {C_DIM}处理:{C_RESET} {len(targets)} 个\n")

    t_moved = t_col = t_rem = 0
    for i, sub in enumerate(targets, 1):
        tag = f"{C_MAGENTA}[{i}/{len(targets)}]{C_RESET} " if len(targets) > 1 else ""
        print(f"  {C_BOLD}{tag}{sub.name}{C_RESET}")
        m, c, r, _ = extract_in_folder(sub)
        if m == 0:
            print(f"  {C_DIM}无需处理{C_RESET}")
        t_moved += m; t_col += c; t_rem += r
        print()

    header("汇总")
    print(f"  {C_GREEN}移动文件:{C_RESET} {t_moved}")
    print(f"  {C_YELLOW}碰撞重命名:{C_RESET} {t_col}")
    print(f"  {C_DIM}清理空目录:{C_RESET} {t_rem}")
    wait_enter()


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


def gif_main(script_dir: Path):
    header(f"2. GIF 统一重命名")

    # 自动定位 GIF 合集目录
    gif_dir = script_dir
    candidates = sorted(
        [d for d in script_dir.iterdir() if d.is_dir() and "GIF" in d.name],
        key=lambda d: d.name,
    )
    if candidates:
        gif_dir = candidates[0]
        print(f"  {C_DIM}自动定位:{C_RESET} {gif_dir.name}")
        print(f"  {C_DIM}Enter 确认，输入其他路径切换{C_RESET}")
        alt = input("  > ").strip()
        if alt:
            alt_path = Path(alt)
            if alt_path.is_dir():
                gif_dir = alt_path
            else:
                print(f"  {C_YELLOW}路径无效，使用默认{C_RESET}")
    else:
        print(f"  {C_DIM}未检测到 GIF 合集目录，请手动输入路径:{C_RESET}")
        alt = input("  > ").strip()
        if alt:
            alt_path = Path(alt)
            if alt_path.is_dir():
                gif_dir = alt_path
            else:
                print(f"  {C_RED}路径无效，已取消{C_RESET}")
                wait_enter()
                return
        else:
            print(f"  {C_RED}已取消{C_RESET}")
            wait_enter()
            return

    print(f"  {C_DIM}工作目录:{C_RESET} {gif_dir}")

    subdirs = sorted([d for d in gif_dir.iterdir() if d.is_dir()], key=lambda d: d.name)

    if subdirs:
        targets = subdirs
        print(f"  {C_DIM}角色文件夹:{C_RESET} {len(subdirs)} 个\n")
    else:
        char_name = gif_extract_char_name(gif_dir)
        print(f"  {C_DIM}模式:{C_RESET} 平铺")
        print(f"  {C_DIM}角色名:{C_RESET} {C_BOLD}{char_name}{C_RESET}")
        print(f"\n  {C_YELLOW}确认？按 Enter 继续，Ctrl+C 取消{C_RESET}")
        input("  > ")
        print()
        targets = [gif_dir]

    t_kept = t_del = t_ren = t_skip = 0
    for i, target in enumerate(targets, 1):
        tag = f"{C_MAGENTA}[{i}/{len(targets)}]{C_RESET} " if len(targets) > 1 else ""
        print(f"  {C_BOLD}{tag}{target.name}{C_RESET}")
        char_name = gif_extract_char_name(target)
        kept, deleted, renamed, skipped = gif_process_folder(target, char_name)
        t_kept += kept; t_del += deleted; t_ren += renamed; t_skip += skipped
        if kept:
            parts = [f"保留 {kept}"]
            if deleted:
                parts.append(f"删重 {deleted}")
            parts.append(f"→ {renamed}")
            print(f"  {C_GREEN}✓{C_RESET} {', '.join(parts)}")
        elif deleted:
            print(f"  {C_RED}全删{C_RESET} (全部为重复)")
        else:
            print(f"  {C_DIM}无需处理{C_RESET}")
        print()

    header("汇总")
    print(f"  {C_GREEN}保留:{C_RESET} {t_kept} 文件")
    if t_del:
        print(f"  {C_RED}删除重复:{C_RESET} {t_del}")
    print(f"  {C_CYAN}重命名:{C_RESET} {t_ren}")
    if t_skip:
        print(f"  {C_DIM}跳过未识别:{C_RESET} {t_skip}")
    wait_enter()


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


def dedup_main(script_dir: Path):
    header(f"3. (n) 标记去重")
    print(f"  {C_DIM}工作目录:{C_RESET} {script_dir}")

    targets = pick_targets(script_dir)
    if not targets:
        print(f"\n  {C_YELLOW}没有找到子文件夹。{C_RESET}")
        wait_enter()
        return

    print(f"  {C_DIM}处理:{C_RESET} {len(targets)} 个\n")

    t_del = t_ren = t_skip = 0
    for i, target in enumerate(targets, 1):
        tag = f"{C_MAGENTA}[{i}/{len(targets)}]{C_RESET} " if len(targets) > 1 else ""
        print(f"  {C_BOLD}{tag}{target.name}{C_RESET}")
        deleted, renamed, skipped = dedup_process_folder(target)
        t_del += deleted; t_ren += renamed; t_skip += skipped
        if deleted or renamed:
            parts = []
            if deleted:
                parts.append(f"{C_RED}删除重复{C_RESET} {deleted}")
            if renamed:
                parts.append(f"{C_GREEN}改名独有{C_RESET} {renamed}")
            if skipped:
                parts.append(f"{C_YELLOW}跳过{C_RESET} {skipped}")
            print(f"  {'  '.join(parts)}")
        else:
            print(f"  {C_DIM}无 (n) 标记文件{C_RESET}")
        print()

    header("汇总")
    if t_del:
        print(f"  {C_RED}删除重复:{C_RESET} {t_del}")
    if t_ren:
        print(f"  {C_GREEN}改名独有:{C_RESET} {t_ren}")
    if t_skip:
        print(f"  {C_YELLOW}跳过:{C_RESET} {t_skip}")
    if not t_del and not t_ren:
        print(f"  {C_DIM}没有需要处理的文件{C_RESET}")
    wait_enter()


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


def restore_main(script_dir: Path):
    header(f"4. 去重还原")
    print(f"  {C_DIM}工作目录:{C_RESET} {script_dir}")

    # restore 直接扫描工作目录及其子文件夹中的映射文件
    targets = []
    for d in sorted(script_dir.iterdir(), key=lambda d: d.name):
        if d.is_dir() and (d / MAP_FILENAME).exists():
            targets.append(d)
    if not targets and (script_dir / MAP_FILENAME).exists():
        targets = [script_dir]

    if not targets:
        print(f"\n  {C_YELLOW}未找到 {MAP_FILENAME}，无需还原。{C_RESET}")
        wait_enter()
        return

    print(f"  {C_DIM}待还原文件夹:{C_RESET} {len(targets)} 个\n")

    t_restored = t_deleted = t_failed = 0
    for i, target in enumerate(targets, 1):
        tag = f"{C_MAGENTA}[{i}/{len(targets)}]{C_RESET} " if len(targets) > 1 else ""
        print(f"  {C_BOLD}{tag}{target.name}{C_RESET}")
        restored, deleted, failed = restore_folder(target)
        t_restored += restored; t_deleted += deleted; t_failed += failed
        if restored:
            print(f"  {C_GREEN}✓ 还原 {restored} 个文件{C_RESET}")
        if failed:
            print(f"  {C_YELLOW}跳过 {failed} 个{C_RESET}")
        print()

    header("汇总")
    print(f"  {C_GREEN}已还原:{C_RESET} {t_restored}")
    if t_deleted:
        print(f"  {C_RED}永久删除(无法恢复):{C_RESET} {t_deleted}")
    if t_failed:
        print(f"  {C_YELLOW}跳过:{C_RESET} {t_failed}")
    wait_enter()


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


def split_main(script_dir: Path):
    header(f"5. 图片视频分离")
    print(f"  {C_DIM}工作目录:{C_RESET} {script_dir}")

    targets = pick_targets(script_dir)
    if not targets:
        print(f"\n  {C_YELLOW}没有找到子文件夹。{C_RESET}")
        wait_enter()
        return

    print(f"  {C_DIM}处理:{C_RESET} {len(targets)} 个\n")

    t_vid = 0
    for i, sub in enumerate(targets, 1):
        tag = f"{C_MAGENTA}[{i}/{len(targets)}]{C_RESET} " if len(targets) > 1 else ""
        print(f"  {C_BOLD}{tag}{sub.name}{C_RESET}")
        vid_m, mode, acted = split_process_folder(sub)
        t_vid += vid_m
        if acted:
            dest = sub.name if mode == 0 else f"{sub.name}_视频"
            print(f"  {C_CYAN}→ {vid_m} 个视频 →{C_RESET} {dest}")
        else:
            print(f"  {C_DIM}无视频{C_RESET}")
        print()

    header("汇总")
    print(f"  {C_CYAN}视频移动:{C_RESET} {t_vid}")
    wait_enter()


# ═══════════════════════════════════════════════════════════

# ============================================================
# 6. CBZ 打包
# ============================================================

def cbz_main(script_dir):
    header("6. CBZ 打包")
    print(f"  {C_DIM}工作目录:{C_RESET} {script_dir}")
    targets = pick_targets(script_dir)
    if not targets:
        print(f"\n  {C_YELLOW}没有子文件夹。{C_RESET}")
        wait_enter()
        return
    print(f"  {C_DIM}处理:{C_RESET} {len(targets)} 个\n")
    ok = skip = 0
    for i, t in enumerate(targets, 1):
        tag = f"{C_MAGENTA}[{i}/{len(targets)}]{C_RESET} " if len(targets) > 1 else ""
        print(f"  {C_BOLD}{tag}{t.name}{C_RESET}")
        found = False
        for root, dirs, files in os.walk(t):
            for sub in dirs:
                fp = Path(root) / sub
                if is_manga_folder(fp):
                    found = True
                    success, cbz, _ = cbz_process_folder(fp)
                    if success: ok += 1
                    else: skip += 1
        if not found:
            print(f"  {C_DIM}无漫画文件夹{C_RESET}")
    header("汇总")
    print(f"  {C_GREEN}打包:{C_RESET} {ok}")
    print(f"  {C_DIM}跳过:{C_RESET} {skip}")
    wait_enter()

def classify_main(script_dir):
    header("7. 按作者分类")
    print(f"  {C_DIM}工作目录:{C_RESET} {script_dir}")
    targets = pick_targets(script_dir)
    if not targets:
        print(f"\n  {C_YELLOW}没有子文件夹。{C_RESET}")
        wait_enter()
        return
    print(f"  {C_DIM}处理:{C_RESET} {len(targets)} 个\n")
    t_moved = t_skip = 0
    for i, t in enumerate(targets, 1):
        tag = f"{C_MAGENTA}[{i}/{len(targets)}]{C_RESET} " if len(targets) > 1 else ""
        print(f"  {C_BOLD}{tag}{t.name}{C_RESET}")
        moved, skipped, _ = classify_process_folder(t)
        t_moved += moved; t_skip += skipped
    header("汇总")
    print(f"  {C_GREEN}移动:{C_RESET} {t_moved}")
    print(f"  {C_DIM}跳过:{C_RESET} {t_skip}")
    wait_enter()


REVERT_REGISTRY = [
    (EXTRACT_MAP, "子文件夹提取", "extract-to-parent"),
    (GIF_MAP,     "GIF 重命名",    "gif-rename"),
    (DEDUP_MAP,   "(n) 去重",      "dedup-duplicates"),
    (SPLIT_MAP,   "图片视频分离",  "split-media"),
    (CBZ_MAP,     "CBZ 打包",      "cbz-pack"),
    (CLASSIFY_MAP, "按作者分类",   "classify"),
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


REVERT_HANDLERS = {
    "extract-to-parent": revert_extract,
    "gif-rename":        revert_gif,
    "dedup-duplicates":  revert_dedup,
    "split-media":       revert_split,
}


def revert_main(script_dir: Path):
    """扫描所有回溯文件，一键批量还原"""
    header("6. 操作回溯")
    print(f"  {C_DIM}工作目录:{C_RESET} {script_dir}")

    # revert 直接扫描工作目录及其子文件夹中的映射文件
    items = []
    for map_file, label, tool_id in REVERT_REGISTRY:
        for d in script_dir.iterdir():
            if not d.is_dir():
                continue
            map_path = d / map_file
            if map_path.exists():
                try:
                    with open(map_path, "r", encoding="utf-8") as f:
                        mapping = json.load(f)
                    ts = mapping.get("timestamp", "未知")[:16]
                    items.append((map_path, label, tool_id, d.name, ts, mapping))
                except Exception:
                    pass
        map_path = script_dir / map_file
        if map_path.exists():
            try:
                with open(map_path, "r", encoding="utf-8") as f:
                    mapping = json.load(f)
                ts = mapping.get("timestamp", "未知")[:16]
                items.append((map_path, label, tool_id, script_dir.name, ts, mapping))
            except Exception:
                pass

    if not items:
        print(f"\n  {C_DIM}没有可还原的操作记录。{C_RESET}")
        wait_enter()
        return

    print(f"\n  {C_DIM}待还原操作 ({len(items)} 项)：{C_RESET}\n")
    for i, (_, label, _, folder_name, ts, _) in enumerate(items, 1):
        print(f"  {C_BOLD}{i}.{C_RESET} {label}  {C_DIM}{folder_name}  {ts}{C_RESET}")

    print(f"\n  {C_YELLOW}Enter 一键还原全部，其他键取消{C_RESET}")
    confirm = input(f"  {C_CYAN}> {C_RESET}").strip()
    if confirm:
        print(f"  {C_DIM}已取消{C_RESET}")
        wait_enter()
        return

    total_files = 0
    total_dirs = 0
    for map_path, label, tool_id, folder_name, ts, mapping in items:
        handler = REVERT_HANDLERS.get(tool_id)
        if handler:
            files, dirs = handler(mapping, map_path.parent)
            total_files += files
            total_dirs += dirs
            try:
                map_path.unlink()
            except OSError:
                pass
            print(f"  {C_GREEN}✓{C_RESET} {label} — {folder_name}  ({files} 文件)")

    print(f"\n  {C_GREEN}全部还原:{C_RESET} {total_files} 文件", end="")
    if total_dirs:
        print(f" {C_DIM}{total_dirs} 目录{C_RESET}", end="")
    print()
    wait_enter()


# ═══════════════════════════════════════════════════════════
# 主菜单
# ═══════════════════════════════════════════════════════════

MENU = [
    ("1", "子文件夹提取",    "将角色文件夹内嵌套文件提取到根目录"),
    ("2", "GIF 统一重命名",  "三格式文件合并去重，统一编号"),
    ("3", "(n) 标记去重",    "检查 (n) 标记重复文件，去重或改名"),
    ("4", "去重还原",        "从 dedup-map.json 还原文件名"),
    ("5", "图片视频分离",    "分离图片和视频到不同文件夹"),
    ("6", "CBZ 打包",       "漫画文件夹打包为 CBZ 归档"),
    ("7", "按作者分类",     "散文件按作者归入合集文件夹"),
    ("8", "操作回溯",        "一键批量还原所有历史操作"),
    ("9", "切换目录",        "更换工作目录"),
    ("0", "退出",            ""),
]

HELP_TEXT = f"""
{C_BOLD}拾掇猫 — 使用教程{C_RESET}

{C_BOLD}目标选择{C_RESET}
  每个功能进入后：
    {C_CYAN}Enter{C_RESET} → 批量处理工作目录下所有子文件夹
    {C_CYAN}输入路径{C_RESET} → 只处理指定文件夹（可以是绝对路径或相对路径）
  例：Enter 处理 Nyako 下 698 个角色文件夹
  例：输入 {C_DIM}Z:\\aimanga\\NFFA\\【11{C_RESET} 只处理这一个文件夹

{C_BOLD}功能 1 · 子文件夹提取{C_RESET}
  把嵌套文件拉到根目录，空子目录自动清理。
  命名：{C_DIM}pixiv\\00001.jpg{C_RESET} → {C_DIM}pixiv_00001.jpg{C_RESET}

{C_BOLD}功能 2 · GIF 统一重命名{C_RESET}
  三格式文件合并去重，统一为「角色名1,2,3...」。
  自动定位含 GIF 的子文件夹，也可手动输入路径。

{C_BOLD}功能 3 · (n) 标记去重{C_RESET}
  处理 pixiv_00001 (2).jpg 类重复文件。
  哈希一致删 (n)，不一致改名 Pixiv_001.jpg。

{C_BOLD}功能 4 · 去重还原{C_RESET}
  从 dedup-map.json 还原功能 3 的改名操作。

{C_BOLD}功能 5 · 图片视频分离{C_RESET}
  提取嵌套视频到同级「文件夹名_视频」目录。
  有图片的文件夹：子文件夹结构原封不动，只提视频。
  纯视频文件夹：视频提取到自身根目录。

{C_BOLD}功能 6 · 操作回溯{C_RESET}
  Enter 一键还原当前工作目录下所有待回溯操作。

{C_BOLD}菜单{C_RESET}
  {C_CYAN}1-6{C_RESET}  执行功能
  {C_CYAN}7{C_RESET}    切换工作目录
  {C_CYAN}8{C_RESET}    退出
  {C_CYAN}h{C_RESET}    帮助
  {C_CYAN}Ctrl+C{C_RESET} 强制退出
"""


def show_help():
    header("使用教程")
    print(HELP_TEXT)
    wait_enter()


def main():
    script_dir = Path(__file__).resolve().parent
    working_dir = None

    while True:
        # — 选择工作目录 —
        header(f"拾掇猫  {C_DIM}v3.0{C_RESET}")
        print(f"  {C_DIM}脚本位置:{C_RESET} {script_dir}")
        if working_dir:
            print(f"  {C_DIM}当前工作目录:{C_RESET} {working_dir}")

        # 列出脚本所在目录的所有子文件夹
        candidates = sorted(
            [d for d in script_dir.iterdir() if d.is_dir()],
            key=lambda d: d.name,
        )
        if candidates:
            print(f"\n  {C_DIM}可选工作目录：{C_RESET}")
            for i, d in enumerate(candidates, 1):
                marker = f" {C_GREEN}←{C_RESET}" if working_dir and d.resolve() == working_dir else ""
                print(f"  {C_BOLD}{i:>3}.{C_RESET} {d.name}{marker}")
            print(f"\n  {C_DIM}输入编号选择，Enter = 脚本位置，路径 = 自定义{C_RESET}")
        else:
            print(f"\n  {C_DIM}Enter = 脚本位置, 输入路径 = 自定义{C_RESET}")

        custom = input(f"  {C_CYAN}> {C_RESET}").strip()
        if not custom:
            working_dir = script_dir
        elif custom.isdigit() and candidates:
            idx = int(custom)
            if 1 <= idx <= len(candidates):
                working_dir = candidates[idx - 1].resolve()
            else:
                print(f"\n  {C_RED}编号超出范围。{C_RESET}")
                wait_enter()
                continue
        else:
            custom_path = Path(custom)
            if custom_path.is_dir():
                working_dir = custom_path.resolve()
            else:
                print(f"\n  {C_RED}路径无效。{C_RESET}")
                wait_enter()
                continue

        # — 功能菜单 —
        while True:
            header(f"拾掇猫  {C_DIM}v3.0{C_RESET}")
            print(f"  {C_DIM}工作目录:{C_RESET} {working_dir}\n")

            for key, title, desc in MENU:
                if desc:
                    print(f"  {C_BOLD}{key}.{C_RESET} {title}{C_DIM} — {desc}{C_RESET}")
                else:
                    print(f"  {C_BOLD}{key}.{C_RESET} {title}")
            print(f"\n  {C_DIM}输入 {C_CYAN}h{C_DIM} 查看使用教程{C_RESET}")

            print()
            try:
                choice = input(f"  {C_CYAN}选择 >{C_RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n")
                break

            if choice == "1":
                extract_main(working_dir)
            elif choice == "2":
                gif_main(working_dir)
            elif choice == "3":
                dedup_main(working_dir)
            elif choice == "4":
                restore_main(working_dir)
            elif choice == "5":
                split_main(working_dir)
            elif choice == "6":
                cbz_main(working_dir)
            elif choice == "7":
                classify_main(working_dir)
            elif choice == "8":
                revert_main(working_dir)
            elif choice == "9":
                break
            elif choice == "0":
                print(f"\n  {C_DIM}再见。{C_RESET}\n")
                return
            elif choice.lower() == "h":
                show_help()
            else:
                print(f"\n  {C_YELLOW}无效选择，请按 1-0 或 h 查看帮助{C_RESET}")


if __name__ == "__main__":
    main()
