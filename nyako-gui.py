"""
拾掇猫 · GUI v5.0
Catppuccin Mocha 主题，统一圆角扁平设计。
需要 nyako_core.py 在同目录。
"""
import io
import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
import tkinter.ttk as ttk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext

if getattr(sys, 'frozen', False):
    BASE = Path(sys.executable).parent
else:
    BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import nyako_core as nc

# ═══════════════════════════════════════════════════════════
# Catppuccin Mocha 配色
# ═══════════════════════════════════════════════════════════
C = {
    "base":     "#1e1e2e",
    "mantle":   "#181825",
    "crust":    "#11111b",
    "surface0": "#313244",
    "surface1": "#45475a",
    "surface2": "#585b70",
    "text":     "#cdd6f4",
    "subtext":  "#a6adc8",
    "muted":    "#6c7086",
    "mauve":    "#cba6f7",
    "blue":     "#89b4fa",
    "lavender": "#b4befe",
    "green":    "#a6e3a1",
    "yellow":   "#f9e2af",
    "red":      "#f38ba8",
    "teal":     "#94e2d5",
    "pink":     "#f5c2e7",
}
FONT = ("Microsoft YaHei UI", 9)
FONT_SM = ("Microsoft YaHei UI", 8)
FONT_LG = ("Microsoft YaHei UI", 11, "bold")
FONT_MONO = ("Consolas", 10)

# ═══════════════════════════════════════════════════════════
# stdout 捕获
# ═══════════════════════════════════════════════════════════
class _W(io.StringIO):
    def __init__(self, q): super().__init__(); self.q = q
    def write(self, s): super().write(s); self.q.put(s)
    def flush(self): pass

# ═══════════════════════════════════════════════════════════
# 按钮：统一圆角扁平风格
# ═══════════════════════════════════════════════════════════
class RoundButton(tk.Frame):
    """统一风格的圆角按钮，用 Frame + Canvas 实现"""
    def __init__(self, parent, text, command, width=200, height=36, accent=C["mauve"]):
        super().__init__(parent, bg=C["surface0"], width=width, height=height, bd=0)
        self.pack_propagate(False)
        self.cmd = command
        self.accent = accent
        self.hover = False
        self._r = 8
        self._w, self._h = width, height
        self._text = text
        self._canvas = tk.Canvas(self, width=width, height=height,
                                 bg=C["surface0"], highlightthickness=0, bd=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas.bind("<Enter>", lambda e: self._set_hover(True))
        self._canvas.bind("<Leave>", lambda e: self._set_hover(False))
        self._canvas.bind("<Button-1>", lambda e: self.cmd() if self.cmd else None)
        self.after_idle(self._draw)

    def _set_hover(self, v):
        self.hover = v
        self._draw()

    def _draw(self):
        if not self._canvas.winfo_exists():
            return
        self._canvas.delete("all")
        bg = self.accent if self.hover else C["surface1"]
        fg = C["crust"] if self.hover else C["text"]
        r, w, h = self._r, self._w, self._h
        self._canvas.create_polygon(
            r, 0, w - r, 0, w, r, w, h - r, w - r, h, r, h, 0, h - r, 0, r,
            smooth=True, fill=bg, outline=""
        )
        self._canvas.create_text(w // 2, h // 2, text=self._text, fill=fg, font=FONT)

    def set_state(self, enabled):
        self.accent = self.accent if enabled else C["surface2"]
        self._draw()

# ═══════════════════════════════════════════════════════════
# 主应用
# ═══════════════════════════════════════════════════════════
class App:
    def __init__(self, root):
        self.root = root
        root.title("拾掇猫")
        root.geometry("1180x760")
        root.minsize(960, 600)
        root.configure(bg=C["base"])

        self.q = queue.Queue()
        self.wd = BASE
        self.busy = False
        self._cancel = False

        self._style()
        self._build()
        self._redirect()
        self._refresh()

    # ── ttk 样式 ──
    def _style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=C["base"], foreground=C["text"], fieldbackground=C["surface0"], borderwidth=0)
        s.configure("TFrame", background=C["base"])
        s.configure("Card.TFrame", background=C["surface0"])
        s.configure("TLabel", background=C["base"], foreground=C["text"], font=FONT)
        s.configure("Title.TLabel", background=C["base"], foreground=C["mauve"], font=FONT_LG)
        s.configure("Muted.TLabel", background=C["base"], foreground=C["muted"], font=FONT_SM)
        s.configure("Status.TLabel", background=C["mantle"], foreground=C["subtext"], font=FONT_SM)
        s.configure("Treeview", background=C["surface0"], foreground=C["text"], fieldbackground=C["surface0"], borderwidth=0, font=FONT, rowheight=26)
        s.configure("Treeview.Heading", background=C["surface1"], foreground=C["text"], font=FONT_SM)
        s.map("Treeview", background=[("selected", C["mauve"])], foreground=[("selected", C["crust"])])
        s.configure("TScrollbar", background=C["surface0"], troughcolor=C["surface0"], borderwidth=0, arrowsize=0)
        s.configure("Vertical.TScrollbar", background=C["surface1"])
        s.configure("TProgressbar", background=C["mauve"], troughcolor=C["surface0"], borderwidth=0)
        s.configure("TEntry", fieldbackground=C["surface0"], foreground=C["text"], insertcolor=C["text"], borderwidth=1)
        s.configure("Flat.TButton", background=C["surface1"], foreground=C["text"], borderwidth=0, padding=6, font=FONT)
        s.map("Flat.TButton", background=[("active", C["surface2"])])
        s.configure("Accent.TButton", background=C["mauve"], foreground=C["crust"], borderwidth=0, padding=6, font=FONT)
        s.map("Accent.TButton", background=[("active", C["lavender"])])
        s.configure("Danger.TButton", background=C["red"], foreground=C["crust"], borderwidth=0, padding=4, font=FONT_SM)
        s.map("Danger.TButton", background=[("active", "#e06a8a")])

    # ── 构建 UI ──
    def _build(self):
        # 顶部标题栏
        top = tk.Frame(self.root, bg=C["mantle"], height=48)
        top.pack(fill=tk.X)
        tk.Label(top, text="🐈 拾掇猫", bg=C["mantle"], fg=C["mauve"], font=FONT_LG).pack(side=tk.LEFT, padx=16, pady=8)
        tk.Label(top, text="v5.0", bg=C["mantle"], fg=C["muted"], font=FONT_SM).pack(side=tk.LEFT, pady=8)

        self.dir_lbl = tk.Label(top, text=str(self.wd), bg=C["mantle"], fg=C["subtext"], font=FONT_SM)
        self.dir_lbl.pack(side=tk.LEFT, padx=12, pady=8)

        # 工具按钮
        ttk.Button(top, text="↑ 上级", style="Flat.TButton", command=self._up).pack(side=tk.RIGHT, padx=4, pady=8)
        ttk.Button(top, text="浏览…", style="Flat.TButton", command=self._browse).pack(side=tk.RIGHT, padx=4, pady=8)
        ttk.Button(top, text="刷新", style="Flat.TButton", command=self._refresh).pack(side=tk.RIGHT, padx=4, pady=8)
        self.cancel_btn = ttk.Button(top, text="取消", style="Danger.TButton", command=self._do_cancel, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.RIGHT, padx=8, pady=8)

        # 主体区域
        body = tk.Frame(self.root, bg=C["base"])
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        # 左栏：文件夹列表
        left_w = tk.Frame(body, bg=C["surface0"], width=340)
        left_w.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        left_w.pack_propagate(False)

        tk.Label(left_w, text="  文件夹", bg=C["surface0"], fg=C["subtext"], font=FONT_SM, height=2, anchor="w").pack(fill=tk.X)
        self.count_lbl = tk.Label(left_w, text="", bg=C["surface0"], fg=C["muted"], font=FONT_SM, anchor="w")
        self.count_lbl.pack(fill=tk.X, padx=12, pady=(0, 4))

        tree_frame = tk.Frame(left_w, bg=C["surface0"])
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        self.tree = ttk.Treeview(tree_frame, selectmode="extended", show="tree")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)

        # 中栏：功能按钮
        mid_w = tk.Frame(body, bg=C["surface0"], width=280)
        mid_w.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        mid_w.pack_propagate(False)

        tk.Label(mid_w, text="  功能", bg=C["surface0"], fg=C["subtext"], font=FONT_SM, height=2, anchor="w").pack(fill=tk.X)

        btn_defs = [
            ("1  子文件夹提取",   self._run_extract,   C["blue"]),
            ("2  GIF 重命名",     self._run_gif,       C["pink"]),
            ("3  (n) 去重",       self._run_dedup,     C["teal"]),
            ("4  去重还原",       self._run_restore,   C["green"]),
            ("5  视频分离",       self._run_split,     C["yellow"]),
            ("6  CBZ 打包",       self._run_cbz,       C["lavender"]),
            ("7  按作者分类",     self._run_classify,  C["mauve"]),
            ("8  操作回溯",       self._run_revert,    C["red"]),
        ]
        for text, cmd, accent in btn_defs:
            btn = RoundButton(mid_w, text, cmd, width=250, height=34, accent=accent)
            btn.pack(padx=12, pady=4)
            idx = btn_defs.index((text, cmd, accent))
            self.root.bind(f"<Alt-Key-{idx + 1}>", lambda e, c=cmd: c())

        # 帮助按钮
        sep = tk.Frame(mid_w, bg=C["surface1"], height=1)
        sep.pack(fill=tk.X, padx=16, pady=10)
        RoundButton(mid_w, "帮助  F1", self._help, width=250, height=30, accent=C["surface2"]).pack(padx=12, pady=4)
        self.root.bind("<F1>", lambda e: self._help())

        # 右栏：输出区
        right_w = tk.Frame(body, bg=C["surface0"])
        right_w.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(right_w, text="  输出", bg=C["surface0"], fg=C["subtext"], font=FONT_SM, height=2, anchor="w").pack(fill=tk.X)
        self.out = scrolledtext.ScrolledText(
            right_w, wrap=tk.WORD, state=tk.DISABLED,
            font=FONT_MONO, bg=C["crust"], fg=C["text"],
            insertbackground=C["text"], relief=tk.FLAT, bd=0,
            padx=12, pady=8, height=10
        )
        self.out.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        # 底部状态栏
        self.prog = ttk.Progressbar(self.root, mode="indeterminate")
        bottom = tk.Frame(self.root, bg=C["mantle"], height=28)
        bottom.pack(fill=tk.X, side=tk.BOTTOM)
        self.status = tk.Label(bottom, text="  就绪 · 选中文件夹后点击功能按钮", bg=C["mantle"], fg=C["subtext"], font=FONT_SM, anchor="w")
        self.status.pack(fill=tk.X, padx=8, pady=4)

    # ── IO ──
    def _redirect(self):
        self._old_o, self._old_e = sys.stdout, sys.stderr
        sys.stdout = _W(self.q); sys.stderr = _W(self.q)
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
                self.tree.insert("", tk.END, text=f"  {d.name}  ({cnt})", values=[str(d)])
            self.count_lbl.configure(text=f"  {len(dirs)} 个子文件夹")
        except PermissionError:
            self.count_lbl.configure(text="  无权限")

    def _up(self):
        p = self.wd.parent
        if p != self.wd: self.wd = p; self._refresh()

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.wd)
        if d: self.wd = Path(d); self._refresh()

    def _sel(self):
        return [Path(self.tree.item(i, "values")[0]) for i in self.tree.selection()]

    # ── 执行引擎 ──
    def _run(self, fn, *args):
        if self.busy: messagebox.showwarning("忙", "上个操作仍在执行"); return
        self.busy = True; self._cancel = False
        self.cancel_btn.configure(state=tk.NORMAL)
        self.status.configure(text="  执行中…", fg=C["yellow"])
        self.prog.pack(fill=tk.X, padx=12, pady=(0, 2))
        self.prog.start(12)
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
        self.status.configure(text="  完成 · 选中文件夹后点击功能按钮", fg=C["green"])
        sys.stdout, sys.stderr = self._old_o, self._old_e
        self._write("\n———— 完成 ————\n")

    def _do_cancel(self):
        self._cancel = True
        self.status.configure(text="  取消中…", fg=C["red"])

    def _pick(self, fn, empty="请选择文件夹"):
        dirs = self._sel()
        if not dirs:
            dirs = [d for d in self.wd.iterdir() if d.is_dir()]
        if not dirs:
            messagebox.showinfo("提示", empty); return
        self._run(fn, dirs)

    def _prog(self, cur, total, name, tag):
        if total and (cur % max(1, total // 10) == 0 or cur == total):
            print(f"  [{cur}/{total}] {name}")

    # ── 功能 ──
    def _run_extract(self):  self._pick(self._do_extract)
    def _do_extract(self, dirs):
        tm = tc = td = 0
        for i, d in enumerate(dirs, 1):
            if self._cancel: break
            print(f"\n[{i}/{len(dirs)}] {d.name}")
            r = nc.extract_process(d, self._prog)
            tm += r.success; tc += r.renamed; td += r.extra.get("dirs_cleaned", 0)
        print(f"\n移动 {tm}  碰撞 {tc}  清理 {td}")

    def _run_gif(self):      self._pick(self._do_gif)
    def _do_gif(self, dirs):
        for d in dirs:
            if self._cancel: break
            name = nc.extract_char_name(d)
            print(f"\n{d.name} → {name}")
            r = nc.gif_process(d, name, self._prog)
            print(f"保留 {r.success}  删重 {r.deleted}  改名 {r.renamed}  跳过 {r.skipped}")

    def _run_dedup(self):    self._pick(self._do_dedup)
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

    def _run_split(self):    self._pick(self._do_split)
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

    def _run_cbz(self):      self._pick(self._do_cbz)
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

    def _run_classify(self): self._pick(self._do_classify)
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

    # ── 帮助 ──
    def _help(self):
        win = tk.Toplevel(self.root)
        win.title("帮助")
        win.geometry("440x520")
        win.configure(bg=C["base"])
        win.resizable(False, False)

        tk.Label(win, text="拾掇猫 v5.0", bg=C["base"], fg=C["mauve"], font=FONT_LG).pack(pady=(16, 4))
        tk.Label(win, text="帮你收拾文件的猫", bg=C["base"], fg=C["muted"], font=FONT_SM).pack(pady=(0, 16))

        help_text = """操作
  · 左栏选中文件夹，点中栏按钮执行
  · Ctrl/Shift 多选
  · Alt+1~8 快捷键

功能
  1  子文件夹提取 — 嵌套文件拉到根目录
  2  GIF 重命名 — 三格式合并去重
  3  (n) 去重 — 处理标记重复文件
  4  去重还原 — 从 dedup-map.json 还原
  5  视频分离 — 提取嵌套视频到 _视频
  6  CBZ 打包 — 漫画文件夹→CBZ
  7  按作者分类 — 散文件归入合集
  8  操作回溯 — 一键还原全部

工具栏
  ↑ 上级 — 回到父目录
  浏览 — 打开文件夹选择器
  取消 — 中止当前操作
  F1 — 帮助"""
        txt = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=FONT, bg=C["surface0"], fg=C["text"],
                                        relief=tk.FLAT, bd=0, padx=16, pady=12, width=48, height=22)
        txt.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        txt.insert(tk.END, help_text)
        txt.configure(state=tk.DISABLED)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
