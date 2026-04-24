"""
BMP to RGB666 (.bin) Converter
将 240x240 24-bit BMP 图片转换为 RGB666 格式的二进制文件
格式：每像素 3 字节，R/G/B 各 6 位左移 2 位对齐至 8 位
"""

import os
import struct
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
from pathlib import Path
import threading


# ──────────────────────────────────────────────
#  核心转换逻辑
# ──────────────────────────────────────────────

REQUIRED_WIDTH  = 240
REQUIRED_HEIGHT = 240
EXPECTED_BYTES  = REQUIRED_WIDTH * REQUIRED_HEIGHT * 3   # 172 800


def convert_bmp_to_rgb666_bin(src_path: Path, dst_path: Path) -> tuple[bool, str]:
    """
    将单张 BMP 图片转换为 RGB666 .bin 文件。
    返回 (成功标志, 消息字符串)
    """
    name = src_path.name

    # ── 1. 格式检查：必须是 .bmp ──
    if src_path.suffix.lower() != ".bmp":
        return False, f'照片 "{name}" 格式不符转换失败（非 BMP 文件）'

    # ── 2. 读取 BMP 文件头，验证分辨率 ──
    try:
        with open(src_path, "rb") as f:
            header = f.read(54)          # BMP 标准文件头 14 + DIB 头 40 = 54 字节

        # 签名校验
        if header[:2] != b"BM":
            return False, f'照片 "{name}" 格式不符转换失败（BMP 签名错误）'

        # 宽高（偏移 18, 22；有符号 32 位小端）
        width  = struct.unpack_from("<i", header, 18)[0]
        height = struct.unpack_from("<i", header, 22)[0]
        abs_height = abs(height)         # 高度可为负（自上而下存储）

        if width != REQUIRED_WIDTH or abs_height != REQUIRED_HEIGHT:
            return False, (f'照片 "{name}" 格式不符转换失败'
                           f'（分辨率 {width}x{abs_height}，需 {REQUIRED_WIDTH}x{REQUIRED_HEIGHT}）')

        # 位深度（偏移 28）
        bit_count = struct.unpack_from("<H", header, 28)[0]
        if bit_count != 24:
            return False, f'照片 "{name}" 格式不符转换失败（位深度 {bit_count}，需 24-bit）'

    except Exception as e:
        return False, f'照片 "{name}" 读取失败：{e}'

    # ── 3. 使用纯 Python 解析像素（无需 Pillow）──
    try:
        with open(src_path, "rb") as f:
            raw = f.read()

        # 像素数据偏移（偏移 10，4 字节无符号小端）
        pixel_offset = struct.unpack_from("<I", raw, 10)[0]

        # BMP 每行字节数须对齐到 4 字节
        row_size = ((REQUIRED_WIDTH * 3 + 3) // 4) * 4   # = 720（240×3 整除 4）

        # BMP 默认自下而上存储（height > 0）；height < 0 表示自上而下
        top_down = (height < 0)

        # 预分配输出缓冲区
        buf = bytearray(EXPECTED_BYTES)
        idx = 0

        for row in range(REQUIRED_HEIGHT):
            # 计算该行在文件中的偏移
            if top_down:
                row_offset = pixel_offset + row * row_size
            else:
                row_offset = pixel_offset + (REQUIRED_HEIGHT - 1 - row) * row_size

            for col in range(REQUIRED_WIDTH):
                px_off = row_offset + col * 3
                b8, g8, r8 = raw[px_off], raw[px_off + 1], raw[px_off + 2]

                # 24-bit → 6-bit（保留高 6 位）
                r6 = (r8 >> 2) & 0x3F
                g6 = (g8 >> 2) & 0x3F
                b6 = (b8 >> 2) & 0x3F

                # 左移 2 位，低 2 位补 0，对齐到 8 位
                buf[idx]     = r6 << 2
                buf[idx + 1] = g6 << 2
                buf[idx + 2] = b6 << 2
                idx += 3

    except Exception as e:
        return False, f'照片 "{name}" 转换出错：{e}'

    # ── 4. 写入 .bin 文件 ──
    try:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        out_file = dst_path / (src_path.stem + ".bin")
        with open(out_file, "wb") as f:
            f.write(buf)
        assert len(buf) == EXPECTED_BYTES
        return True, f'✔ "{name}" → "{out_file.name}"  ({len(buf):,} 字节)'
    except Exception as e:
        return False, f'照片 "{name}" 写入失败：{e}'


def batch_convert(src_dir: Path, dst_dir: Path, log_callback, done_callback):
    """在子线程中批量转换，通过回调更新 UI。"""
    files = list(src_dir.iterdir()) if src_dir.is_dir() else []
    total = len(files)
    ok_count = err_count = 0

    log_callback(f"=== 开始转换，共发现 {total} 个文件 ===\n")

    for i, f in enumerate(files, 1):
        log_callback(f"[{i}/{total}] 处理: {f.name}")
        success, msg = convert_bmp_to_rgb666_bin(f, dst_dir)
        log_callback(f"  {msg}\n")
        if success:
            ok_count += 1
        else:
            err_count += 1

    log_callback(
        f"\n=== 转换完成 ===\n"
        f"  成功: {ok_count} 个\n"
        f"  失败: {err_count} 个\n"
    )
    done_callback()


# ──────────────────────────────────────────────
#  GUI
# ──────────────────────────────────────────────

class App(tk.Tk):
    # ── 配色方案 ──
    BG        = "#1e1e2e"
    PANEL     = "#27273a"
    ACCENT    = "#7c6af7"
    ACCENT_HV = "#9d90ff"
    FG        = "#cdd6f4"
    FG_DIM    = "#6c7086"
    SUCCESS   = "#a6e3a1"
    ERROR     = "#f38ba8"
    MONO      = ("Consolas", 9)

    def __init__(self):
        super().__init__()
        self.title("BMP → RGB666 Converter")
        self.geometry("720x560")
        self.resizable(True, True)
        self.configure(bg=self.BG)
        self._running = False

        # 默认路径
        base = Path(__file__).parent
        self._src_var = tk.StringVar(value=str(base / "pictures" / "24bit"))
        self._dst_var = tk.StringVar(value=str(base / "pictures" / "18bit"))

        self._build_ui()
        self._apply_style()

    # ── 构建界面 ──────────────────────────────
    def _build_ui(self):
        pad = dict(padx=16, pady=8)

        # ─ 标题栏 ─
        title_frame = tk.Frame(self, bg=self.PANEL, height=52)
        title_frame.pack(fill="x")
        tk.Label(
            title_frame, text="🖼  BMP → RGB666 Converter",
            bg=self.PANEL, fg=self.FG,
            font=("Segoe UI", 14, "bold")
        ).pack(side="left", padx=20, pady=10)
        tk.Label(
            title_frame, text="ESP32-C3  ST7789  240×240",
            bg=self.PANEL, fg=self.FG_DIM,
            font=("Segoe UI", 9)
        ).pack(side="right", padx=20, pady=10)

        # ─ 路径区 ─
        path_frame = tk.Frame(self, bg=self.BG)
        path_frame.pack(fill="x", **pad)

        self._make_path_row(path_frame, "输入文件夹（24-bit BMP）：", self._src_var, 0)
        self._make_path_row(path_frame, "输出文件夹（RGB666 .bin）：", self._dst_var, 1)

        path_frame.columnconfigure(1, weight=1)

        # ─ 操作按钮 ─
        btn_frame = tk.Frame(self, bg=self.BG)
        btn_frame.pack(fill="x", padx=16, pady=4)

        self._btn_convert = tk.Button(
            btn_frame, text="▶  开始转换",
            command=self._on_convert,
            bg=self.ACCENT, fg="white",
            activebackground=self.ACCENT_HV, activeforeground="white",
            font=("Segoe UI", 10, "bold"),
            relief="flat", cursor="hand2",
            padx=24, pady=8
        )
        self._btn_convert.pack(side="left", padx=(0, 8))

        self._btn_clear = tk.Button(
            btn_frame, text="🗑  清除日志",
            command=self._clear_log,
            bg=self.PANEL, fg=self.FG_DIM,
            activebackground="#32324a", activeforeground=self.FG,
            font=("Segoe UI", 10),
            relief="flat", cursor="hand2",
            padx=16, pady=8
        )
        self._btn_clear.pack(side="left")

        # 进度条
        self._progress = ttk.Progressbar(btn_frame, mode="indeterminate", length=160)
        self._progress.pack(side="right", padx=8)

        # ─ 日志区 ─
        log_frame = tk.Frame(self, bg=self.PANEL, bd=0)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(4, 16))

        tk.Label(
            log_frame, text="  转换日志",
            bg=self.PANEL, fg=self.FG_DIM,
            font=("Segoe UI", 8)
        ).pack(anchor="w", pady=(6, 0))

        self._log = scrolledtext.ScrolledText(
            log_frame,
            bg="#12121e", fg=self.FG,
            insertbackground=self.FG,
            font=self.MONO,
            relief="flat", bd=0,
            wrap="word",
            state="disabled"
        )
        self._log.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # 标签着色
        self._log.tag_config("ok",  foreground=self.SUCCESS)
        self._log.tag_config("err", foreground=self.ERROR)
        self._log.tag_config("hdr", foreground=self.ACCENT, font=("Consolas", 9, "bold"))

    def _make_path_row(self, parent, label, var, row):
        tk.Label(
            parent, text=label,
            bg=self.BG, fg=self.FG_DIM,
            font=("Segoe UI", 9)
        ).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))

        entry = tk.Entry(
            parent, textvariable=var,
            bg=self.PANEL, fg=self.FG,
            insertbackground=self.FG,
            relief="flat", bd=6,
            font=("Segoe UI", 9)
        )
        entry.grid(row=row, column=1, sticky="ew", pady=4)

        tk.Button(
            parent, text="…",
            command=lambda v=var: self._browse(v),
            bg=self.PANEL, fg=self.FG,
            activebackground=self.ACCENT, activeforeground="white",
            relief="flat", cursor="hand2",
            font=("Segoe UI", 10, "bold"),
            padx=10, pady=2
        ).grid(row=row, column=2, sticky="e", padx=(6, 0), pady=4)

    def _apply_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "TProgressbar",
            troughcolor=self.PANEL,
            background=self.ACCENT,
            thickness=6
        )

    # ── 事件处理 ──────────────────────────────
    def _browse(self, var: tk.StringVar):
        folder = filedialog.askdirectory(initialdir=var.get() or ".")
        if folder:
            var.set(folder)

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _on_convert(self):
        if self._running:
            return
        src = Path(self._src_var.get().strip())
        dst = Path(self._dst_var.get().strip())

        if not src.is_dir():
            self._append_log(f'[错误] 输入文件夹不存在：{src}\n', tag="err")
            return

        self._running = True
        self._btn_convert.configure(state="disabled", text="转换中…")
        self._progress.start(12)

        thread = threading.Thread(
            target=batch_convert,
            args=(src, dst, self._queue_log, self._on_done),
            daemon=True
        )
        thread.start()

    def _queue_log(self, msg: str):
        """从子线程安全地写日志（通过 after 回调到主线程）。"""
        self.after(0, self._append_log, msg)

    def _append_log(self, msg: str, tag: str = None):
        self._log.configure(state="normal")

        # 自动着色
        if tag is None:
            if msg.startswith("✔"):
                tag = "ok"
            elif "失败" in msg or "错误" in msg or "[错误]" in msg:
                tag = "err"
            elif msg.startswith("==="):
                tag = "hdr"

        if tag:
            self._log.insert("end", msg + "\n", tag)
        else:
            self._log.insert("end", msg + "\n")

        self._log.see("end")
        self._log.configure(state="disabled")

    def _on_done(self):
        self.after(0, self._finish_ui)

    def _finish_ui(self):
        self._running = False
        self._progress.stop()
        self._btn_convert.configure(state="normal", text="▶  开始转换")


# ──────────────────────────────────────────────
#  入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
