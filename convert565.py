"""
BMP to RGB565 (.bin) Converter
将 240x240 24-bit BMP 图片转换为 RGB565 格式的二进制文件
格式：每像素 3 字节（R-G-B 顺序），多余低位裁切补 0
  Byte 0 (R) : 取高 5 位 → R5 << 3（低 3 位补 0）
  Byte 1 (G) : 取高 6 位 → G6 << 2（低 2 位补 0）
  Byte 2 (B) : 取高 5 位 → B5 << 3（低 3 位补 0）
总大小恒为 240 × 240 × 3 = 172,800 字节
"""

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


def convert_bmp_to_rgb565_bin(src_path: Path, dst_path: Path) -> tuple[bool, str]:
    """
    将单张 BMP 图片转换为 RGB565 .bin 文件。
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

    # ── 3. 解析像素并转换为 RGB565（纯标准库，无需 Pillow）──
    try:
        with open(src_path, "rb") as f:
            raw = f.read()

        # 像素数据偏移（偏移 10，4 字节无符号小端）
        pixel_offset = struct.unpack_from("<I", raw, 10)[0]

        # BMP 每行字节数须对齐到 4 字节边界
        row_size = ((REQUIRED_WIDTH * 3 + 3) // 4) * 4   # = 720（240×3 整除 4）

        # BMP 默认自下而上存储（height > 0）；height < 0 表示自上而下
        top_down = (height < 0)

        # 预分配输出缓冲区（全零初始化，低位补 0 已由初始化完成）
        buf = bytearray(EXPECTED_BYTES)
        idx = 0

        for row in range(REQUIRED_HEIGHT):
            if top_down:
                row_offset = pixel_offset + row * row_size
            else:
                row_offset = pixel_offset + (REQUIRED_HEIGHT - 1 - row) * row_size

            for col in range(REQUIRED_WIDTH):
                px_off = row_offset + col * 3
                # BMP 像素以 B-G-R 顺序存储
                b8, g8, r8 = raw[px_off], raw[px_off + 1], raw[px_off + 2]

                # RGB565 裁切规则（多余低位补 0）：
                #   R: 8bit → 5bit，丢弃低 3 位，再左移 3 位还原到 8 位位宽
                #   G: 8bit → 6bit，丢弃低 2 位，再左移 2 位还原到 8 位位宽
                #   B: 8bit → 5bit，丢弃低 3 位，再左移 3 位还原到 8 位位宽
                r5 = (r8 >> 3) & 0x1F   # 保留高 5 位
                g6 = (g8 >> 2) & 0x3F   # 保留高 6 位
                b5 = (b8 >> 3) & 0x1F   # 保留高 5 位

                buf[idx]     = r5 << 3  # 低 3 位补 0
                buf[idx + 1] = g6 << 2  # 低 2 位补 0
                buf[idx + 2] = b5 << 3  # 低 3 位补 0
                idx += 3

    except Exception as e:
        return False, f'照片 "{name}" 转换出错：{e}'

    # ── 4. 写入 .bin 文件 ──
    try:
        dst_path.mkdir(parents=True, exist_ok=True)
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
        success, msg = convert_bmp_to_rgb565_bin(f, dst_dir)
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
#  GUI  —  暖橙色系，与 RGB666 版本明确区分
# ──────────────────────────────────────────────

class App(tk.Tk):
    # ── 配色方案（Warm Ember Dark）──
    BG        = "#1c1710"   # 深棕底色
    PANEL     = "#252015"   # 面板深色
    ACCENT    = "#e07b2a"   # 橙色主色
    ACCENT_HV = "#f59840"   # 橙色高亮
    FG        = "#f0e0c0"   # 暖白前景
    FG_DIM    = "#7a6a50"   # 暗淡辅助文字
    SUCCESS   = "#88c97a"   # 绿色成功
    ERROR     = "#e05a5a"   # 红色失败
    LOG_BG    = "#110e08"   # 日志区背景
    MONO      = ("Consolas", 9)

    def __init__(self):
        super().__init__()
        self.title("BMP → RGB565 Converter")
        self.geometry("720x560")
        self.resizable(True, True)
        self.configure(bg=self.BG)
        self._running = False

        # 默认路径
        base = Path(__file__).parent
        self._src_var = tk.StringVar(value=str(base / "pictures" / "24bit"))
        self._dst_var = tk.StringVar(value=str(base / "pictures" / "565"))

        self._build_ui()
        self._apply_style()

    # ── 构建界面 ──────────────────────────────
    def _build_ui(self):
        pad = dict(padx=16, pady=8)

        # ─ 标题栏 ─
        title_frame = tk.Frame(self, bg=self.PANEL, height=56)
        title_frame.pack(fill="x")
        title_frame.pack_propagate(False)

        # 左侧：彩色格式徽章 + 标题
        left = tk.Frame(title_frame, bg=self.PANEL)
        left.pack(side="left", padx=16, pady=10)

        badge = tk.Label(
            left, text=" RGB565 ",
            bg=self.ACCENT, fg="#1c1710",
            font=("Segoe UI", 8, "bold"),
            relief="flat", padx=4
        )
        badge.pack(side="left", padx=(0, 10))

        tk.Label(
            left, text="BMP → RGB565 Converter",
            bg=self.PANEL, fg=self.FG,
            font=("Segoe UI", 13, "bold")
        ).pack(side="left")

        # 右侧：副标题
        tk.Label(
            title_frame, text="ESP32-C3  ST7789  240×240",
            bg=self.PANEL, fg=self.FG_DIM,
            font=("Segoe UI", 9)
        ).pack(side="right", padx=20)

        # ─ 格式说明条 ─
        info_bar = tk.Frame(self, bg="#2a1e0a", height=26)
        info_bar.pack(fill="x")
        info_bar.pack_propagate(False)
        tk.Label(
            info_bar,
            text="  R(5bit) · G(6bit) · B(5bit)  │  每像素 3 字节  │  总大小 172,800 字节  │  低位截断补 0",
            bg="#2a1e0a", fg=self.ACCENT,
            font=("Segoe UI", 8)
        ).pack(side="left", pady=4)

        # ─ 路径区 ─
        path_frame = tk.Frame(self, bg=self.BG)
        path_frame.pack(fill="x", **pad)

        self._make_path_row(path_frame, "输入文件夹（24-bit BMP）：", self._src_var, 0)
        self._make_path_row(path_frame, "输出文件夹（RGB565 .bin）：", self._dst_var, 1)

        path_frame.columnconfigure(1, weight=1)

        # ─ 操作按钮 ─
        btn_frame = tk.Frame(self, bg=self.BG)
        btn_frame.pack(fill="x", padx=16, pady=4)

        self._btn_convert = tk.Button(
            btn_frame, text="▶  开始转换",
            command=self._on_convert,
            bg=self.ACCENT, fg="#1c1710",
            activebackground=self.ACCENT_HV, activeforeground="#1c1710",
            font=("Segoe UI", 10, "bold"),
            relief="flat", cursor="hand2",
            padx=24, pady=8
        )
        self._btn_convert.pack(side="left", padx=(0, 8))

        self._btn_clear = tk.Button(
            btn_frame, text="🗑  清除日志",
            command=self._clear_log,
            bg=self.PANEL, fg=self.FG_DIM,
            activebackground="#352c1a", activeforeground=self.FG,
            font=("Segoe UI", 10),
            relief="flat", cursor="hand2",
            padx=16, pady=8
        )
        self._btn_clear.pack(side="left")

        # 进度条
        self._progress = ttk.Progressbar(btn_frame, mode="indeterminate",
                                          style="Ember.Horizontal.TProgressbar",
                                          length=160)
        self._progress.pack(side="right", padx=8)

        # ─ 日志区 ─
        log_frame = tk.Frame(self, bg=self.PANEL, bd=0)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(4, 16))

        # 日志标题行
        log_title = tk.Frame(log_frame, bg=self.PANEL)
        log_title.pack(fill="x")
        tk.Label(
            log_title, text="  转换日志",
            bg=self.PANEL, fg=self.FG_DIM,
            font=("Segoe UI", 8)
        ).pack(side="left", pady=(6, 0))

        self._log = scrolledtext.ScrolledText(
            log_frame,
            bg=self.LOG_BG, fg=self.FG,
            insertbackground=self.FG,
            font=self.MONO,
            relief="flat", bd=0,
            wrap="word",
            state="disabled"
        )
        self._log.pack(fill="both", expand=True, padx=8, pady=(2, 8))

        # 标签着色
        self._log.tag_config("ok",  foreground=self.SUCCESS)
        self._log.tag_config("err", foreground=self.ERROR)
        self._log.tag_config("hdr", foreground=self.ACCENT,
                              font=("Consolas", 9, "bold"))

    def _make_path_row(self, parent, label, var, row):
        tk.Label(
            parent, text=label,
            bg=self.BG, fg=self.FG_DIM,
            font=("Segoe UI", 9)
        ).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))

        tk.Entry(
            parent, textvariable=var,
            bg=self.PANEL, fg=self.FG,
            insertbackground=self.FG,
            relief="flat", bd=6,
            font=("Segoe UI", 9)
        ).grid(row=row, column=1, sticky="ew", pady=4)

        tk.Button(
            parent, text="…",
            command=lambda v=var: self._browse(v),
            bg=self.PANEL, fg=self.FG,
            activebackground=self.ACCENT, activeforeground="#1c1710",
            relief="flat", cursor="hand2",
            font=("Segoe UI", 10, "bold"),
            padx=10, pady=2
        ).grid(row=row, column=2, sticky="e", padx=(6, 0), pady=4)

    def _apply_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Ember.Horizontal.TProgressbar",
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
            if msg.strip().startswith("✔"):
                tag = "ok"
            elif "失败" in msg or "错误" in msg or "[错误]" in msg:
                tag = "err"
            elif msg.strip().startswith("==="):
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
