"""
拾掇猫 · CLI 入口
命令行菜单版。需要 nyako_core.py 在同目录。
"""
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nyako_core as nc

# ── ANSI ──
RST = "\033[0m"
B   = "\033[1m"
DIM = "\033[2m"
GRN = "\033[32m"
YEL = "\033[33m"
RED = "\033[31m"
CYN = "\033[36m"
MAG = "\033[35m"
W   = shutil.get_terminal_size().columns


def bar(p, w=30):
    f = int(w * p)
    return f"{CYN}{'█'*f}{'░'*(w-f)}{RST} {p*100:5.1f}%"


def hdr(t):
    line = f" {t} "
    pad = max(0, (W - len(line)) // 2)
    print(f"\n{B}{'─'*pad}{line}{'─'*(W-pad-len(line))}{RST}\n")


def wait():
    input(f"\n{DIM}按 Enter 返回菜单…{RST}")


def prog(current, total, name, tag):
    if total and (current % max(1, total // 20) == 0 or current == total):
        sys.stdout.write(f"\r  {bar(current / total)}  {current}/{total}  {name}")
        sys.stdout.flush()


# ── 目标选择 ──
def pick_targets(wd: Path) -> list[Path]:
    subs = sorted([d for d in wd.iterdir() if d.is_dir()], key=lambda d: d.name)
    print(f"  {DIM}子文件夹:{RST} {len(subs)} 个")
    print(f"  {CYN}Enter{RST}=全部  {CYN}路径{RST}=单个  {CYN}s{RST}=勾选")
    c = input(f"  {CYN}> {RST}").strip()
    if not c:
        return subs
    if c.lower() == "s":
        for i, d in enumerate(subs, 1):
            print(f"  {B}{i:>4}.{RST} {d.name}")
        sel = input(f"  {CYN}编号(空格分隔,如 1 3 5-8){RST}> ").strip()
        if not sel:
            return subs
        picked = []
        for part in sel.split():
            if "-" in part:
                try:
                    a, b = part.split("-", 1)
                    picked.extend(range(int(a), int(b) + 1))
                except ValueError:
                    pass
            else:
                try: picked.append(int(part))
                except ValueError: pass
        return [subs[i - 1] for i in picked if 1 <= i <= len(subs)]
    p = Path(c)
    if p.is_dir(): return [p.resolve()]
    joined = wd / c
    if joined.is_dir(): return [joined.resolve()]
    print(f"  {RED}路径无效，使用全部{RST}")
    return subs


# ── 功能入口 ──
def run_extract(wd):
    hdr("1. 子文件夹提取")
    targets = pick_targets(wd)
    if not targets: print(f"  {YEL}无子文件夹{RST}"); wait(); return
    print(f"  {DIM}处理:{RST} {len(targets)} 个\n")
    tm = tc = td = 0
    for i, t in enumerate(targets, 1):
        print(f"  {MAG}[{i}/{len(targets)}]{RST} {B}{t.name}{RST}")
        r = nc.extract_process(t, prog)
        tm += r.success; tc += r.renamed; td += r.extra.get("dirs_cleaned", 0)
        print()
    hdr("汇总")
    print(f"  {GRN}移动:{RST} {tm}  {YEL}碰撞:{RST} {tc}  {DIM}清理:{RST} {td}")
    wait()


def run_gif(wd):
    hdr("2. GIF 统一重命名")
    targets = pick_targets(wd)
    if not targets: print(f"  {YEL}无子文件夹{RST}"); wait(); return
    print()
    for i, t in enumerate(targets, 1):
        name = nc.extract_char_name(t)
        print(f"  {MAG}[{i}/{len(targets)}]{RST} {B}{t.name}{RST} → {DIM}{name}{RST}")
        r = nc.gif_process(t, name, prog)
        print(f"  {GRN}保留:{RST} {r.success}  {RED}删重:{RST} {r.deleted}  {CYN}改名:{RST} {r.renamed}  {DIM}跳过:{RST} {r.skipped}\n")
    wait()


def run_dedup(wd):
    hdr("3. (n) 标记去重")
    targets = pick_targets(wd)
    if not targets: print(f"  {YEL}无子文件夹{RST}"); wait(); return
    print()
    td = tr = 0
    for i, t in enumerate(targets, 1):
        print(f"  {MAG}[{i}/{len(targets)}]{RST} {B}{t.name}{RST}")
        r = nc.dedup_process(t, prog)
        td += r.deleted; tr += r.renamed
        if r.deleted or r.renamed:
            print(f"  {RED}删重:{RST} {r.deleted}  {CYN}改名:{RST} {r.renamed}")
        else:
            print(f"  {DIM}无 (n) 标记{RST}")
        print()
    hdr("汇总")
    print(f"  {RED}删除:{RST} {td}  {CYN}改名:{RST} {tr}")
    wait()


def run_restore(wd):
    hdr("4. 去重还原")
    dirs = [d for d in wd.iterdir() if d.is_dir() and (d / nc.MAP_DEDUP).exists()]
    if not dirs and (wd / nc.MAP_DEDUP).exists():
        dirs = [wd]
    if not dirs:
        print(f"  {YEL}未找到 {nc.MAP_DEDUP}{RST}"); wait(); return
    print(f"  {DIM}待还原:{RST} {len(dirs)} 个\n")
    for i, d in enumerate(dirs, 1):
        print(f"  {MAG}[{i}/{len(dirs)}]{RST} {B}{d.name}{RST}")
        r = nc.restore_process(d)
        print(f"  {GRN}还原:{RST} {r.success}  {RED}不可恢复:{RST} {r.deleted}  {YEL}跳过:{RST} {r.skipped}\n")
    wait()


def run_split(wd):
    hdr("5. 图片视频分离")
    targets = pick_targets(wd)
    if not targets: print(f"  {YEL}无子文件夹{RST}"); wait(); return
    print()
    tv = 0
    for i, t in enumerate(targets, 1):
        print(f"  {MAG}[{i}/{len(targets)}]{RST} {B}{t.name}{RST}")
        r = nc.split_process(t, prog)
        tv += r.success
        mode = r.extra.get("mode", "")
        if r.success:
            dest = t.name if mode == "self" else f"{t.name}_视频"
            print(f"  {CYN}→ {r.success} 视频 → {dest}{RST}")
        else:
            print(f"  {DIM}无视频{RST}")
        print()
    hdr("汇总")
    print(f"  {CYN}视频移动:{RST} {tv}")
    wait()


def run_cbz(wd):
    hdr("6. CBZ 打包")
    targets = pick_targets(wd)
    if not targets: print(f"  {YEL}无子文件夹{RST}"); wait(); return
    print()
    ok = skip = 0
    for i, t in enumerate(targets, 1):
        print(f"  {MAG}[{i}/{len(targets)}]{RST} {B}{t.name}{RST}")
        found = False
        for root, subdirs, files in os.walk(t):
            for sub in subdirs:
                fp = Path(root) / sub
                if nc.is_manga_folder(fp):
                    found = True
                    r = nc.cbz_process(fp, prog)
                    if r.success: ok += 1
                    else: skip += 1
        if not found:
            print(f"  {DIM}无漫画文件夹{RST}")
        print()
    hdr("汇总")
    print(f"  {GRN}打包:{RST} {ok}  {DIM}跳过:{RST} {skip}")
    wait()


def run_classify(wd):
    hdr("7. 按作者分类")
    targets = pick_targets(wd)
    if not targets: print(f"  {YEL}无子文件夹{RST}"); wait(); return
    print()
    tm = ts = 0
    for i, t in enumerate(targets, 1):
        print(f"  {MAG}[{i}/{len(targets)}]{RST} {B}{t.name}{RST}")
        r = nc.classify_process(t, prog)
        tm += r.success; ts += r.skipped
        print(f"  {GRN}移动:{RST} {r.success}  {DIM}跳过:{RST} {r.skipped}\n")
    hdr("汇总")
    print(f"  {GRN}移动:{RST} {tm}  {DIM}跳过:{RST} {ts}")
    wait()


def run_revert(wd):
    hdr("8. 操作回溯")
    items = nc.revert_scan(wd)
    if not items:
        print(f"  {DIM}无可还原操作{RST}"); wait(); return
    print(f"  {DIM}待还原 ({len(items)} 项):{RST}\n")
    for i, (_, label, _, fname, ts, _) in enumerate(items, 1):
        print(f"  {B}{i}.{RST} {label}  {DIM}{fname}  {ts}{RST}")
    print(f"\n  {YEL}Enter 一键全部还原，其他键取消{RST}")
    if input(f"  {CYN}> {RST}").strip():
        print(f"  {DIM}已取消{RST}"); wait(); return
    r = nc.revert_execute(items)
    print(f"\n  {GRN}还原:{RST} {r.success} 文件  {DIM}{r.extra.get('dirs', 0)} 目录{RST}")
    wait()


def show_help():
    hdr("使用教程")
    print(f"""{B}目标选择{RST}
  {CYN}Enter{RST} → 批量处理全部子文件夹
  {CYN}路径{RST} → 指定单个文件夹
  {CYN}s{RST}    → 列表勾选（支持 1 3 5-8）

{B}功能{RST}
  1. 子文件夹提取 — 嵌套文件拉到根目录
  2. GIF 重命名 — 三格式合并去重
  3. (n) 去重 — 处理标记重复文件
  4. 去重还原 — 从 dedup-map.json 还原
  5. 视频分离 — 提取嵌套视频到 _视频
  6. CBZ 打包 — 漫画文件夹→CBZ
  7. 按作者分类 — 散文件归入合集
  8. 操作回溯 — 一键还原全部

{B}快捷键{RST}
  {CYN}1-8{RST} 功能  {CYN}9{RST} 切换目录  {CYN}0{RST} 退出  {CYN}h{RST} 帮助
""")


MENU = [
    ("1", "子文件夹提取"),
    ("2", "GIF 统一重命名"),
    ("3", "(n) 标记去重"),
    ("4", "去重还原"),
    ("5", "图片视频分离"),
    ("6", "CBZ 打包"),
    ("7", "按作者分类"),
    ("8", "操作回溯"),
    ("9", "切换目录"),
    ("0", "退出"),
]

DISPATCH = {
    "1": run_extract, "2": run_gif, "3": run_dedup, "4": run_restore,
    "5": run_split, "6": run_cbz, "7": run_classify, "8": run_revert,
}


def main():
    script_dir = Path(__file__).resolve().parent
    if getattr(sys, 'frozen', False):
        script_dir = Path(sys.executable).parent
    wd = None

    while True:
        hdr(f"拾掇猫  {DIM}v4.0{RST}")
        print(f"  {DIM}脚本:{RST} {script_dir}")
        if wd:
            print(f"  {DIM}当前:{RST} {wd}")
        candidates = sorted([d for d in script_dir.iterdir() if d.is_dir()], key=lambda d: d.name)
        if candidates:
            print(f"\n  {DIM}可选目录:{RST}")
            for i, d in enumerate(candidates, 1):
                mk = f" {GRN}←{RST}" if wd and d.resolve() == wd else ""
                print(f"  {B}{i:>3}.{RST} {d.name}{mk}")
            print(f"\n  {DIM}编号选择, Enter=脚本位置, 路径=自定义{RST}")
        c = input(f"  {CYN}> {RST}").strip()
        if not c:
            wd = script_dir
        elif c.isdigit() and candidates:
            idx = int(c)
            if 1 <= idx <= len(candidates):
                wd = candidates[idx - 1].resolve()
            else:
                print(f"  {RED}超出范围{RST}"); wait(); continue
        else:
            p = Path(c)
            if p.is_dir(): wd = p.resolve()
            else: print(f"  {RED}无效{RST}"); wait(); continue

        while True:
            hdr(f"拾掇猫  {DIM}v4.0{RST}")
            print(f"  {DIM}工作目录:{RST} {wd}\n")
            for k, t in MENU:
                print(f"  {B}{k}.{RST} {t}")
            print(f"\n  {DIM}输入 {CYN}h{DIM} 查看教程{RST}\n")
            try:
                choice = input(f"  {CYN}选择 >{RST} ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n"); return

            if choice in DISPATCH:
                DISPATCH[choice](wd)
            elif choice == "9":
                break
            elif choice == "0":
                print(f"\n  {DIM}再见。{RST}\n"); return
            elif choice.lower() == "h":
                show_help(); wait()
            else:
                print(f"\n  {YEL}无效，按 0-9 或 h{RST}")


if __name__ == "__main__":
    main()
