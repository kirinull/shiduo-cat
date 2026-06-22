"""
拾掇猫 · GUI 入口
Tkinter 图形界面。需要 nyako_core.py 在同目录。
"""
import io
import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

if getattr(sys, 'frozen', False):
    BASE = Path(sys.executable).parent
else:
    BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import nyako_core as nc


class GuiWriter(io.StringIO):
    def __init__(self, q): super().__init__(); self.q = q
    def write(self, s): super().write(s); self.q.put(s)
    def flush(self): pass


BTNS = [
    ("1. 子文件夹提取", "_run_extract"),
    ("2. GIF 重命名",   "_run_gif"),
    ("3. (n) 去重",     "_run_dedup"),
    ("4. 去重还原",     "_run_restore"),
    ("5. 视频分离",     "_run_split"),
    ("6. CBZ 打包",     "_run_cbz"),
    ("7. 按作者分类",   "_run_classify"),
    ("8. 操作回溯",     "_run_revert"),
]


class App:
    def __init__(self, root):
        self.root = root
        root.title("拾掇猫 v4.0")
        root.geometry("1100x720")
        root.minsize(900, 550)
        self.q = queue.Queue()
        self.wd = BASE
        self.busy = False
        self._cancel = False
        self._style()
        self._build()
        self._redirect()
        self._refresh()

    def _style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background="#2b2b2b", foreground="#ccc", fieldbackground="#3c3c3c")
        s.configure("TButton", padding=4, font=("Microsoft YaHei UI", 9))
        s.configure("Treeview", font=("Microsoft YaHei UI", 9), rowheight=22)
        s.configure("TLabelFrame.Label", font=("Microsoft YaHei UI", 10, "bold"))
        s.configure("Red.TButton", foreground="#ff6b6b")

    def _build(self):
        bar = ttk.Frame(self.root); bar.pack(fill=tk.X, padx=8, pady=(8, 0))
        ttk.Label(bar, text="目录:").pack(side=tk.LEFT)
        self.dir_lbl = ttk.Label(bar, text=str(self.wd), foreground="#888"); self.dir_lbl.pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text="↑", command=self._up, width=3).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="浏览…", command=self._browse).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="刷新", command=self._refresh).pack(side=tk.LEFT, padx=2)
        self.count_lbl = ttk.Label(bar, text="", foreground="#888"); self.count_lbl.pack(side=tk.RIGHT, padx=6)
        self.cancel_btn = ttk.Button(bar, text="取消", command=self._do_cancel, style="Red.TButton", state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.RIGHT, padx=4)

        mid = ttk.Frame(self.root); mid.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
        left = ttk.LabelFrame(mid, text="文件夹"); left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(left, selectmode="extended", show="tree"); self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview).pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=lambda *a: None)

        right = ttk.LabelFrame(mid, text="功能"); right.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        for i, (label, method) in enumerate(BTNS):
            r, c = i % 4, i // 4
            ttk.Button(right, text=f"{label}  Alt+{i+1}", command=getattr(self, method), width=18).grid(row=r, column=c, padx=4, pady=3, sticky="ew")
            self.root.bind(f"<Alt-Key-{i+1}>", lambda e, m=method: getattr(self, m)())
        ttk.Separator(right, orient=tk.HORIZONTAL).grid(row=5, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Button(right, text="帮助  F1", command=self._help, width=18).grid(row=6, column=0, columnspan=2, padx=4, pady=2)
        self.root.bind("<F1>", lambda e: self._help())

        bottom = ttk.LabelFrame(self.root, text="输出"); bottom.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))
        self.out = scrolledtext.ScrolledText(bottom, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 10), bg="#1e1e1e", fg="#d4d4d4", relief=tk.FLAT, height=8)
        self.out.pack(fill=tk.BOTH, expand=True)
        self.prog = ttk.Progressbar(bottom, mode="indeterminate")
        self.status = ttk.Label(self.root, text="就绪 · 选中文件夹后点击功能按钮", relief=tk.SUNKEN, anchor=tk.W)
        self.status.pack(fill=tk.X, padx=8, pady=(0, 6))

    # ── IO ──
    def _redirect(self):
        self._old_o, self._old_e = sys.stdout, sys.stderr
        sys.stdout = GuiWriter(self.q); sys.stderr = GuiWriter(self.q)
        self._poll()

    def _poll(self):
        try:
            while True: self._write(self.q.get_nowait())
        except queue.Empty: pass
        self.root.after(60, self._poll)

    def _write(self, text):
        clean = re.sub(r'\033\[[0-9;]*m', '', text)
        self.out.configure(state=tk.NORMAL)
        if '\r' in clean and '\n' not in clean:
            last = self.out.index("end-1c linestart")
            self.out.delete(last, "end-1c")
            clean = clean.lstrip('\r')
        self.out.insert(tk.END, clean)
        self.out.see(tk.END)
        self.out.configure(state=tk.DISABLED)

    # ── 目录 ──
    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.dir_lbl.configure(text=str(self.wd))
        try:
            dirs = sorted([d for d in self.wd.iterdir() if d.is_dir()], key=lambda d: d.name)
            for d in dirs:
                cnt = sum(1 for _ in d.iterdir())
                self.tree.insert("", tk.END, text=f"{d.name}  ({cnt})", values=[str(d)])
            self.count_lbl.configure(text=f"{len(dirs)} 个")
        except PermissionError:
            self.count_lbl.configure(text="无权限")

    def _up(self):
        p = self.wd.parent
        if p != self.wd: self.wd = p; self._refresh()

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.wd)
        if d: self.wd = Path(d); self._refresh()

    def _sel(self):
        return [Path(self.tree.item(i, "values")[0]) for i in self.tree.selection()]

    # ── 执行 ──
    def _run(self, fn, *args):
        if self.busy: messagebox.showwarning("忙", "上个操作仍在执行"); return
        self.busy = True; self._cancel = False
        self.cancel_btn.configure(state=tk.NORMAL)
        self.status.configure(text="执行中…")
        self.prog.pack(fill=tk.X, padx=8); self.prog.start(15)
        self.out.configure(state=tk.NORMAL); self.out.delete(1.0, tk.END); self.out.configure(state=tk.DISABLED)
        def wrap():
            try: fn(*args)
            except Exception:
                import traceback; traceback.print_exc()
            finally: self.q.put("__DONE__")
        threading.Thread(target=wrap, daemon=True).start()
        self._check()

    def _check(self):
        try:
            while True:
                s = self.q.get_nowait()
                if s.strip() == "__DONE__": self._done(); return
                self._write(s)
        except queue.Empty: pass
        self.root.after(80, self._check)

    def _done(self):
        self.busy = False
        self.cancel_btn.configure(state=tk.DISABLED)
        self.prog.stop(); self.prog.pack_forget()
        self.status.configure(text="完成 · 选中文件夹后点击功能按钮")
        sys.stdout, sys.stderr = self._old_o, self._old_e
        self._write("\n———— 完成 ————\n")

    def _do_cancel(self):
        self._cancel = True; self.status.configure(text="取消中…")

    def _pick(self, fn, empty="请选择文件夹"):
        dirs = self._sel()
        if not dirs:
            dirs = [d for d in self.wd.iterdir() if d.is_dir()]
        if not dirs:
            messagebox.showinfo("提示", empty); return
        self._run(fn, dirs)

    # ── 功能 ──
    def _run_extract(self):   self._pick(self._do_extract)
    def _do_extract(self, dirs):
        tm = tc = td = 0
        for i, d in enumerate(dirs, 1):
            if self._cancel: break
            print(f"\n[{i}/{len(dirs)}] {d.name}")
            r = nc.extract_process(d, self._prog)
            tm += r.success; tc += r.renamed; td += r.extra.get("dirs_cleaned", 0)
        print(f"\n移动 {tm}  碰撞 {tc}  清理 {td}")

    def _run_gif(self):       self._pick(self._do_gif)
    def _do_gif(self, dirs):
        for d in dirs:
            if self._cancel: break
            name = nc.extract_char_name(d)
            print(f"\n{d.name} → {name}")
            r = nc.gif_process(d, name, self._prog)
            print(f"保留 {r.success}  删重 {r.deleted}  改名 {r.renamed}  跳过 {r.skipped}")

    def _run_dedup(self):     self._pick(self._do_dedup)
    def _do_dedup(self, dirs):
        td = tr = 0
        for d in dirs:
            if self._cancel: break
            print(f"\n{d.name}")
            r = nc.dedup_process(d, self._prog)
            td += r.deleted; tr += r.renamed
            print(f"  删重 {r.deleted}  改名 {r.renamed}" if r.deleted or r.renamed else "  无 (n) 标记")
        print(f"\n删除 {td}  改名 {tr}")

    def _run_restore(self):
        dirs = [d for d in self.wd.iterdir() if d.is_dir() and (d / nc.MAP_DEDUP).exists()]
        if not dirs and (self.wd / nc.MAP_DEDUP).exists(): dirs = [self.wd]
        if not dirs: messagebox.showinfo("提示", "未找到 dedup-map.json"); return
        self._run(self._do_restore, dirs)
    def _do_restore(self, dirs):
        for d in dirs:
            if self._cancel: break
            print(f"\n{d.name}")
            r = nc.restore_process(d)
            print(f"  还原 {r.success}  不可恢复 {r.deleted}  跳过 {r.skipped}")

    def _run_split(self):     self._pick(self._do_split)
    def _do_split(self, dirs):
        tv = 0
        for d in dirs:
            if self._cancel: break
            print(f"\n{d.name}")
            r = nc.split_process(d, self._prog)
            tv += r.success
            mode = r.extra.get("mode", "")
            if r.success:
                dest = d.name if mode == "self" else f"{d.name}_视频"
                print(f"  → {r.success} 视频 → {dest}")
            else: print("  无视频")
        print(f"\n视频移动 {tv}")

    def _run_cbz(self):       self._pick(self._do_cbz)
    def _do_cbz(self, dirs):
        ok = skip = 0
        for d in dirs:
            if self._cancel: break
            for root, subs, files in os.walk(d):
                for sub in subs:
                    fp = Path(root) / sub
                    if nc.is_manga_folder(fp):
                        r = nc.cbz_process(fp, self._prog)
                        if r.success: ok += 1
                        else: skip += 1
        print(f"\n打包 {ok}  跳过 {skip}")

    def _run_classify(self):  self._pick(self._do_classify)
    def _do_classify(self, dirs):
        tm = ts = 0
        for d in dirs:
            if self._cancel: break
            print(f"\n{d.name}")
            r = nc.classify_process(d, self._prog)
            tm += r.success; ts += r.skipped
        print(f"\n移动 {tm}  跳过 {ts}")

    def _run_revert(self):
        if self.busy: return
        items = nc.revert_scan(self.wd)
        if not items: messagebox.showinfo("提示", "没有可还原的操作"); return
        self._run(self._do_revert, items)
    def _do_revert(self, items):
        for mp, label, tid, fname, ts, mapping in items:
            if self._cancel: break
            h = nc.REVERT_HANDLERS.get(tid)
            if h:
                f, d = h(mapping, mp.parent)
                try: mp.unlink()
                except OSError: pass
                print(f"✓ {label} — {fname}  ({f} 文件)")
        print("\n还原完成")

    def _prog(self, cur, total, name, tag):
        if total and (cur % max(1, total // 10) == 0 or cur == total):
            print(f"  [{cur}/{total}] {name}")

    def _help(self):
        messagebox.showinfo("帮助", """拾掇猫 v4.0

【操作】
· 左侧选中文件夹 → 点击右侧按钮
· Ctrl/Shift 多选
· Alt+1~8 快捷键

【功能】
1. 子文件夹提取
2. GIF 重命名
3. (n) 去重
4. 去重还原
5. 视频分离
6. CBZ 打包
7. 按作者分类
8. 操作回溯""")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
