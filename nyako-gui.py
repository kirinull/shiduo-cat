"""
nyako-gui.py — 拾掇猫 GUI 版 v4.0
双击运行。需要 nyako_core.py 在同目录。
"""
import io, json, os, queue, re, sys, threading, tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

if getattr(sys, 'frozen', False):
    BASE = Path(sys.executable).parent
else:
    BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import nyako_core as nc


# ---- stdout / stderr ----
class GuiWriter(io.StringIO):
    def __init__(self, q): super().__init__(); self.q = q
    def write(self, s): super().write(s); self.q.put(s)
    def flush(self): pass


# ---- 按钮配置 ----
BTN_DEFS = [
    ("1. 子文件夹提取",  "_run_extract",   "Alt+1"),
    ("2. GIF 重命名",    "_run_gif",       "Alt+2"),
    ("3. (n) 去重",      "_run_dedup",     "Alt+3"),
    ("4. 去重还原",      "_run_restore",   "Alt+4"),
    ("5. 视频分离",      "_run_split",     "Alt+5"),
    ("6. CBZ 打包",      "_run_cbz",       "Alt+6"),
    ("7. 按作者分类",    "_run_classify",  "Alt+7"),
    ("8. 操作回溯",      "_run_revert",    "Alt+8"),
]


class NyakoGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("拾掇猫 v4.0")
        root.geometry("1100x720")
        root.minsize(900, 550)
        root.configure(bg="#2b2b2b")

        self.out_q = queue.Queue()
        self.work_dir = BASE
        self.running = False
        self._cancel = False

        self._style()
        self._build()
        self._redirect()
        self._refresh_tree()

    # ==================== 样式 ====================
    def _style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background="#2b2b2b", foreground="#cccccc", fieldbackground="#3c3c3c")
        s.configure("TButton", padding=4, font=("Microsoft YaHei UI", 9))
        s.configure("Treeview", font=("Microsoft YaHei UI", 9), rowheight=22)
        s.configure("TLabelFrame", font=("Microsoft YaHei UI", 10, "bold"))
        s.configure("TLabel", font=("Microsoft YaHei UI", 9))
        s.configure("Red.TButton", foreground="#ff6b6b")

    # ==================== UI ====================
    def _build(self):
        # 顶部工具栏
        bar = ttk.Frame(self.root)
        bar.pack(fill=tk.X, padx=8, pady=(8, 0))
        ttk.Label(bar, text="工作目录:").pack(side=tk.LEFT)
        self.dir_label = ttk.Label(bar, text=str(self.work_dir), foreground="#888888")
        self.dir_label.pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text="↑上级", command=self._go_up, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="浏览…", command=self._browse).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="刷新", command=self._refresh_tree).pack(side=tk.LEFT, padx=2)
        self.dir_count_label = ttk.Label(bar, text="", foreground="#888888")
        self.dir_count_label.pack(side=tk.RIGHT, padx=6)
        self.cancel_btn = ttk.Button(bar, text="取消", command=self._do_cancel, style="Red.TButton", state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.RIGHT, padx=4)

        # 主体
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        # 左：目录树
        left = ttk.LabelFrame(main, text="文件夹")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(left, selectmode="extended", show="tree", columns=("path",))
        self.tree.column("#0", width=280, minwidth=150)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scroll.set)

        # 右：按钮面板（2列网格）
        right = ttk.LabelFrame(main, text="功能")
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        for i, (label, method, key) in enumerate(BTN_DEFS):
            row, col = i % 4, i // 4
            btn = ttk.Button(right, text=f"{label}  {key}", command=getattr(self, method), width=18)
            btn.grid(row=row, column=col, padx=4, pady=3, sticky="ew")
            # 键盘快捷键
            self.root.bind(f"<Alt-Key-{i+1}>", lambda e, m=method: getattr(self, m)())
        # 帮助在右下角
        ttk.Separator(right, orient=tk.HORIZONTAL).grid(row=5, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Button(right, text="帮助  F1", command=self._help, width=18).grid(row=6, column=0, columnspan=2, padx=4, pady=2)
        self.root.bind("<F1>", lambda e: self._help())

        # 底部：输出 + 进度
        bottom = ttk.LabelFrame(self.root, text="输出")
        bottom.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))
        self.out = scrolledtext.ScrolledText(
            bottom, wrap=tk.WORD, state=tk.DISABLED,
            font=("Consolas", 10), bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="#d4d4d4", relief=tk.FLAT, height=8
        )
        self.out.pack(fill=tk.BOTH, expand=True)

        self.progress = ttk.Progressbar(bottom, mode="indeterminate")
        self.status = ttk.Label(self.root, text="就绪 · 选中文件夹后点击功能按钮", relief=tk.SUNKEN, anchor=tk.W)
        self.status.pack(fill=tk.X, padx=8, pady=(0, 6))

    # ==================== IO ====================
    def _redirect(self):
        self._old_stdout, self._old_stderr = sys.stdout, sys.stderr
        sys.stdout = GuiWriter(self.out_q)
        sys.stderr = GuiWriter(self.out_q)
        self._poll()

    def _poll(self):
        try:
            while True:
                self._write_out(self.out_q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(60, self._poll)

    def _write_out(self, text: str):
        clean = re.sub(r'\033\[[0-9;]*m', '', text)
        self.out.configure(state=tk.NORMAL)
        if '\r' in clean and '\n' not in clean:
            last = self.out.index("end-1c linestart")
            self.out.delete(last, "end-1c")
            clean = clean.lstrip('\r')
        self.out.insert(tk.END, clean)
        self.out.see(tk.END)
        self.out.configure(state=tk.DISABLED)

    # ==================== 目录 ====================
    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.dir_label.configure(text=str(self.work_dir))
        try:
            dirs = sorted([d for d in self.work_dir.iterdir() if d.is_dir()], key=lambda d: d.name)
            for d in dirs:
                count = sum(1 for _ in d.iterdir())
                self.tree.insert("", tk.END, text=f"{d.name}  ({count})", values=[str(d)])
            self.dir_count_label.configure(text=f"{len(dirs)} 个")
        except PermissionError:
            self.dir_count_label.configure(text="无权限")

    def _go_up(self):
        parent = self.work_dir.parent
        if parent != self.work_dir:
            self.work_dir = parent
            self._refresh_tree()

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.work_dir)
        if d:
            self.work_dir = Path(d)
            self._refresh_tree()

    def _get_selected(self) -> list[Path]:
        return [Path(self.tree.item(i, "values")[0]) for i in self.tree.selection()]

    # ==================== 执行引擎 ====================
    def _pick_and_run(self, fn, filter_gif=False, empty_msg="请选择文件夹"):
        """统一的目录选择→执行流程"""
        if self.running:
            messagebox.showwarning("忙", "上个操作仍在执行")
            return
        dirs = self._get_selected()
        if not dirs:
            if filter_gif:
                dirs = [d for d in self.work_dir.iterdir() if d.is_dir() and "GIF" in d.name]
            else:
                dirs = [d for d in self.work_dir.iterdir() if d.is_dir()]
        if not dirs:
            messagebox.showinfo("提示", empty_msg)
            return
        self._run(fn, dirs)

    def _run(self, fn, *args):
        self.running = True
        self._cancel = False
        self.cancel_btn.configure(state=tk.NORMAL)
        self.status.configure(text="执行中…")
        self.progress.pack(fill=tk.X, padx=8)
        self.progress.start(15)
        self.out.configure(state=tk.NORMAL)
        self.out.delete(1.0, tk.END)
        self.out.configure(state=tk.DISABLED)

        def wrapper():
            try:
                fn(*args)
            except Exception:
                import traceback
                traceback.print_exc()
            finally:
                self.out_q.put("__DONE__")
        self.thread = threading.Thread(target=wrapper, daemon=True)
        self.thread.start()
        self._check()

    def _check(self):
        try:
            while True:
                s = self.out_q.get_nowait()
                if s.strip() == "__DONE__":
                    self._finish()
                    return
                self._write_out(s)
        except queue.Empty:
            pass
        self.root.after(80, self._check)

    def _finish(self):
        self.running = False
        self.cancel_btn.configure(state=tk.DISABLED)
        self.progress.stop()
        self.progress.pack_forget()
        self.status.configure(text="完成 · 选中文件夹后点击功能按钮")
        sys.stdout, sys.stderr = self._old_stdout, self._old_stderr
        self._write_out("\n———— 完成 ————\n")

    def _do_cancel(self):
        self._cancel = True
        self.status.configure(text="取消中…")

    # ==================== 功能 ====================
    def _run_extract(self):
        self._pick_and_run(self._do_extract, empty_msg="请选择子文件夹")

    def _do_extract(self, dirs):
        t_m = t_c = t_r = 0
        for i, d in enumerate(dirs, 1):
            if self._cancel: break
            print(f"\n[{i}/{len(dirs)}] {d.name}")
            m, c, r, _ = nc.extract_in_folder(d)
            t_m += m; t_c += c; t_r += r
        print(f"\n移动 {t_m}  碰撞 {t_c}  清理 {t_r}")

    def _run_gif(self):
        self._pick_and_run(self._do_gif, filter_gif=True, empty_msg="未找到 GIF 文件夹，请选择或确认目录")

    def _do_gif(self, dirs):
        for d in dirs:
            if self._cancel: break
            name = nc.gif_extract_char_name(d)
            print(f"\n{d.name}  →  角色名: {name}")
            k, deleted, renamed, skipped = nc.gif_process_folder(d, name)
            print(f"保留 {k}  删重 {deleted}  改名 {renamed}  跳过 {skipped}")

    def _run_dedup(self):
        self._pick_and_run(self._do_dedup)

    def _do_dedup(self, dirs):
        t_d = t_r = 0
        for d in dirs:
            if self._cancel: break
            print(f"\n{d.name}")
            deleted, renamed, skipped = nc.dedup_process_folder(d)
            t_d += deleted; t_r += renamed
            print(f"  删重 {deleted}  改名 {renamed}" if deleted or renamed else "  无 (n) 标记")
        print(f"\n删除 {t_d}  改名 {t_r}")

    def _run_restore(self):
        dirs = self._get_selected()
        if not dirs:
            dirs = [d for d in self.work_dir.iterdir() if d.is_dir() and (d / "dedup-map.json").exists()]
        if not dirs:
            messagebox.showinfo("提示", "未找到 dedup-map.json")
            return
        self._run(self._do_restore, dirs)

    def _do_restore(self, dirs):
        for d in dirs:
            if self._cancel: break
            print(f"\n{d.name}")
            r, deleted, failed = nc.restore_folder(d)
            print(f"  还原 {r}  无法恢复 {deleted}  跳过 {failed}")

    def _run_split(self):
        self._pick_and_run(self._do_split)

    def _do_split(self, dirs):
        t_v = 0
        for d in dirs:
            if self._cancel: break
            print(f"\n{d.name}")
            vid_m, mode, acted = nc.split_process_folder(d)
            t_v += vid_m
            if acted:
                dest = d.name if mode == 0 else f"{d.name}_视频"
                print(f"  → {vid_m} 视频 → {dest}")
            else:
                print("  无视频")
        print(f"\n视频移动 {t_v}")

    def _run_cbz(self):
        self._pick_and_run(self._do_cbz)

    def _do_cbz(self, dirs):
        ok = skip = 0
        for d in dirs:
            if self._cancel: break
            found = False
            for root, subdirs, files in os.walk(d):
                for sub in subdirs:
                    fp = Path(root) / sub
                    if nc.is_manga_folder(fp):
                        found = True
                        success, cbz, _ = nc.cbz_process_folder(fp)
                        if success: ok += 1
                        else: skip += 1
            if not found:
                print(f"\n{d.name}  无漫画文件夹")
        print(f"\n打包 {ok}  跳过 {skip}")

    def _run_classify(self):
        self._pick_and_run(self._do_classify)

    def _do_classify(self, dirs):
        t_m = t_s = 0
        for d in dirs:
            if self._cancel: break
            print(f"\n{d.name}")
            moved, skipped, _ = nc.classify_process_folder(d)
            t_m += moved; t_s += skipped
        print(f"\n移动 {t_m}  跳过 {t_s}")

    def _run_revert(self):
        if self.running: return
        items = []
        for map_file, label, tool_id in nc.REVERT_REGISTRY:
            for d in self.work_dir.iterdir():
                if not d.is_dir(): continue
                mp = d / map_file
                if mp.exists():
                    try:
                        with open(mp, "r", encoding="utf-8") as f: m = json.load(f)
                        ts = m.get("timestamp", "?")[:16]
                        handler = nc.REVERT_HANDLERS.get(tool_id)
                        items.append((mp, label, tool_id, d.name, ts, m, handler))
                    except Exception: pass
            mp = self.work_dir / map_file
            if mp.exists():
                try:
                    with open(mp, "r", encoding="utf-8") as f: m = json.load(f)
                    ts = m.get("timestamp", "?")[:16]
                    handler = nc.REVERT_HANDLERS.get(tool_id)
                    items.append((mp, label, tool_id, self.work_dir.name, ts, m, handler))
                except Exception: pass
        if not items:
            messagebox.showinfo("提示", "没有可还原的操作")
            return
        self._run(self._do_revert, items)

    def _do_revert(self, items):
        t_f = t_d = 0
        for mp, label, tool_id, folder_name, ts, mapping, handler in items:
            if self._cancel: break
            if handler:
                files, dirs = handler(mapping, mp.parent)
                t_f += files; t_d += dirs
                try: mp.unlink()
                except OSError: pass
                print(f"✓ {label} — {folder_name}  ({files} 文件)")
        print(f"\n还原 {t_f} 文件  {t_d} 目录")

    # ==================== 帮助 ====================
    def _help(self):
        msg = """拾掇猫 v4.0

【操作】
· 左侧树选中文件夹 → 点击右侧按钮执行
· Ctrl/Shift 多选，双击进入子目录
· Alt+1~8 快捷键直接启动

【功能】
1. 子文件夹提取 — 嵌套文件拉到根目录
2. GIF 重命名 — 三格式合并去重
3. (n) 去重 — 处理带标记的重复文件
4. 去重还原 — 从 dedup-map.json 还原
5. 视频分离 — 提取嵌套视频到 {名称}_视频
6. CBZ 打包 — 漫画文件夹→CBZ 归档
7. 按作者分类 — 散文件归入 [作者]合集
8. 操作回溯 — 一键还原全部操作

【工具栏】
· ↑上级 — 回到父目录
· 浏览 — 打开文件夹选择器
· 取消 — 中止当前操作
· F1 — 帮助"""
        messagebox.showinfo("帮助", msg)


def main():
    root = tk.Tk()
    NyakoGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
