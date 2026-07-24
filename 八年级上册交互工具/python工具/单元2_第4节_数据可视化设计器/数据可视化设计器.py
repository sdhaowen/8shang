# -*- coding: utf-8 -*-
"""
数据可视化设计器
==========================================================
课时：清华版《信息科技》八年级上册 第2单元 第4节《数据可视化》
配套项目：在线数字气象站（荔波小七孔气温探究）

功能：
  1. 导入 CSV 数据（自动检测 UTF-8 / GBK 等常见编码），或一键载入
     内置示例：小七孔 24 小时气象数据、一周天气统计。
  2. 选择 X / Y 字段与图表类型（柱状图 / 折线图 / 饼图 / 散点图），
     设置标题、坐标轴名称、颜色、是否显示图例，一键绘制。
  3. 绘图引擎自动选择：
     · 已安装 matplotlib：用 FigureCanvasTkAgg 嵌入高质量图表，
       支持另存为 PNG；
     · 未安装 matplotlib：自动降级为 tkinter.Canvas 自绘版本
       （四种图表均支持，坐标轴、刻度、标题齐全），可另存为
       PostScript(.ps) 文件，并提示安装 matplotlib 可获得 PNG 导出。
  4. 图表配置可保存 / 载入 JSON，便于复现设计。
  5. 实验记录自动累积，可导出 TXT；帮助窗口讲解图表选择方法。

运行方法：
  python3 数据可视化设计器.py
  核心功能仅依赖 Python 标准库；matplotlib 为可选增强（见 requirements.txt）。
"""

import csv
import io
import json
import math
import os

# ---- 可选增强：matplotlib（没有也能运行） ----
try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    matplotlib.rcParams["font.sans-serif"] = [
        "SimHei", "Microsoft YaHei", "PingFang SC", "WenQuanYi Micro Hei",
        "Noto Sans CJK SC", "sans-serif"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

APP_TITLE = "数据可视化设计器 · 第2单元第4节 数据可视化"

CHART_TYPES = ["柱状图", "折线图", "饼图", "散点图"]
COLOR_NAMES = {
    "工作室粉": "#ec4899", "罗兰紫": "#8b5cf6", "天空蓝": "#3b82f6",
    "草木绿": "#10b981", "暖阳橙": "#f59e0b", "热情红": "#ef4444",
}
PIE_COLORS = ["#ec4899", "#8b5cf6", "#3b82f6", "#10b981", "#f59e0b",
              "#ef4444", "#14b8a6", "#f472b6"]

# ---------------------------------------------------------------
# 内置示例数据
# ---------------------------------------------------------------
_TEMPS = [13.5, 13.1, 12.8, 12.4, 12.1, 11.8, 11.5, 12.3, 14.0, 16.2, 18.5, 20.6,
          22.4, 23.8, 24.6, 24.2, 23.3, 21.8, 19.9, 18.2, 16.8, 15.6, 14.7, 14.0]
_HUMS = [88, 89, 90, 91, 92, 93, 94, 90, 84, 78, 72, 66,
         61, 57, 55, 56, 59, 64, 70, 75, 79, 82, 84, 86]


def sample_weather24():
    rows = [["时刻", "气温", "湿度"]]
    for h in range(24):
        rows.append([str(h), str(_TEMPS[h]), str(_HUMS[h])])
    return rows


def sample_week():
    return [["天气", "天数"], ["晴", "3"], ["多云", "2"], ["阴", "1"], ["小雨", "1"]]


# ---------------------------------------------------------------
# 纯函数（不依赖 GUI）
# ---------------------------------------------------------------
def to_float(s):
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def read_csv_auto(path):
    """自动检测编码读取 CSV，返回列表的列表（含表头）。"""
    raw = open(path, "rb").read()
    text = None
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    return [row for row in reader if any(str(c).strip() for c in row)]


def extract_xy(rows, xi, yi):
    """提取 (X标签列表, X数值列表或None, Y数值列表)。"""
    xlabels, xnums, ynums = [], [], []
    all_x_numeric = True
    for r in rows:
        if xi < len(r) and yi < len(r):
            y = to_float(r[yi])
            if y is None:
                continue
            xlabels.append(str(r[xi]))
            xv = to_float(r[xi])
            if xv is None:
                all_x_numeric = False
            xnums.append(xv)
            ynums.append(y)
    return xlabels, (xnums if all_x_numeric else None), ynums


def nice_ticks(vmin, vmax, n=5):
    """生成大约 n 个刻度值。"""
    if vmax <= vmin:
        vmax = vmin + 1
    span = vmax - vmin
    return [vmin + span * i / n for i in range(n + 1)]


# ---------------------------------------------------------------
# GUI
# ---------------------------------------------------------------
def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    class App:
        def __init__(self, root):
            self.root = root
            root.title(APP_TITLE)
            root.geometry("1120x700")
            root.minsize(920, 580)
            self.headers = []
            self.rows = []
            self.record = []
            self.mpl_fig = None
            self.mpl_canvas = None
            self._build()
            self.load_sample24()

        def _build(self):
            root = self.root
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass
            style.configure("TButton", padding=5)
            style.configure("Head.TLabel", font=("", 11, "bold"), foreground="#9d174d")

            top = ttk.Frame(root, padding=(8, 6))
            top.pack(fill="x")
            ttk.Button(top, text="导入 CSV", command=self.import_csv).pack(side="left", padx=3)
            ttk.Button(top, text="示例：24小时气象", command=self.load_sample24).pack(side="left", padx=3)
            ttk.Button(top, text="示例：一周天气", command=self.load_sample_week).pack(side="left", padx=3)
            ttk.Button(top, text="保存配置 JSON", command=self.save_config).pack(side="left", padx=3)
            ttk.Button(top, text="载入配置 JSON", command=self.load_config).pack(side="left", padx=3)
            ttk.Button(top, text="导出实验记录", command=self.export_record).pack(side="left", padx=3)
            ttk.Button(top, text="帮助", command=self.show_help).pack(side="right", padx=3)
            engine = ("绘图引擎：matplotlib（可导出 PNG）" if HAS_MPL
                      else "绘图引擎：tkinter.Canvas 自绘（安装 matplotlib 可获得 PNG 导出）")
            ttk.Label(top, text=engine,
                      foreground="#059669" if HAS_MPL else "#92400e").pack(side="right", padx=8)

            body = ttk.Frame(root, padding=6)
            body.pack(fill="both", expand=True)
            body.columnconfigure(1, weight=1)
            body.rowconfigure(0, weight=1)

            # ---- 左侧属性面板 ----
            left = ttk.Frame(body)
            left.grid(row=0, column=0, sticky="ns", padx=(0, 8))

            fd = ttk.LabelFrame(left, text="数据与字段", padding=8)
            fd.pack(fill="x", pady=(0, 6))
            ttk.Label(fd, text="X 字段：").grid(row=0, column=0, sticky="w")
            self.cb_x = ttk.Combobox(fd, state="readonly", width=14)
            self.cb_x.grid(row=0, column=1, pady=2)
            ttk.Label(fd, text="Y 字段：").grid(row=1, column=0, sticky="w")
            self.cb_y = ttk.Combobox(fd, state="readonly", width=14)
            self.cb_y.grid(row=1, column=1, pady=2)
            self.lab_data = ttk.Label(fd, text="（未载入数据）", foreground="#71717a")
            self.lab_data.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

            fs = ttk.LabelFrame(left, text="图表样式", padding=8)
            fs.pack(fill="x", pady=6)
            ttk.Label(fs, text="图表类型：").grid(row=0, column=0, sticky="w")
            self.cb_type = ttk.Combobox(fs, state="readonly", width=14, values=CHART_TYPES)
            self.cb_type.set("折线图")
            self.cb_type.grid(row=0, column=1, pady=2)
            ttk.Label(fs, text="标题：").grid(row=1, column=0, sticky="w")
            self.ent_title = ttk.Entry(fs, width=17)
            self.ent_title.insert(0, "小七孔一天气温变化")
            self.ent_title.grid(row=1, column=1, pady=2)
            ttk.Label(fs, text="X 轴名称：").grid(row=2, column=0, sticky="w")
            self.ent_xlab = ttk.Entry(fs, width=17)
            self.ent_xlab.insert(0, "时刻")
            self.ent_xlab.grid(row=2, column=1, pady=2)
            ttk.Label(fs, text="Y 轴名称：").grid(row=3, column=0, sticky="w")
            self.ent_ylab = ttk.Entry(fs, width=17)
            self.ent_ylab.insert(0, "气温/℃")
            self.ent_ylab.grid(row=3, column=1, pady=2)
            ttk.Label(fs, text="颜色：").grid(row=4, column=0, sticky="w")
            self.cb_color = ttk.Combobox(fs, state="readonly", width=14,
                                         values=list(COLOR_NAMES.keys()))
            self.cb_color.set("罗兰紫")
            self.cb_color.grid(row=4, column=1, pady=2)
            self.var_legend = tk.BooleanVar(value=True)
            ttk.Checkbutton(fs, text="显示图例", variable=self.var_legend).grid(
                row=5, column=0, columnspan=2, sticky="w")

            fa = ttk.LabelFrame(left, text="操作", padding=8)
            fa.pack(fill="x", pady=6)
            ttk.Button(fa, text="绘制图表 ▶", command=self.draw).pack(fill="x", pady=2)
            ttk.Button(fa, text="保存图片", command=self.save_image).pack(fill="x", pady=2)
            ttk.Button(fa, text="重置", command=self.reset_all).pack(fill="x", pady=2)

            # ---- 右侧画板 ----
            right = ttk.Frame(body)
            right.grid(row=0, column=1, sticky="nsew")
            right.rowconfigure(0, weight=1)
            right.columnconfigure(0, weight=1)
            self.chart_holder = ttk.Frame(right)
            self.chart_holder.grid(row=0, column=0, sticky="nsew")
            self.chart_holder.rowconfigure(0, weight=1)
            self.chart_holder.columnconfigure(0, weight=1)
            if HAS_MPL:
                self.mpl_fig = Figure(figsize=(6.4, 4.6), dpi=100)
                self.mpl_canvas = FigureCanvasTkAgg(self.mpl_fig, master=self.chart_holder)
                self.mpl_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
                self.tk_canvas = None
            else:
                self.tk_canvas = tk.Canvas(self.chart_holder, bg="white",
                                           highlightthickness=1,
                                           highlightbackground="#e4e4e7")
                self.tk_canvas.grid(row=0, column=0, sticky="nsew")

            self.status = ttk.Label(root, text="就绪", anchor="w", relief="sunken",
                                    padding=(8, 3))
            self.status.pack(fill="x", side="bottom")

        # ---------- 数据 ----------
        def set_data(self, rows, source):
            self.headers = [str(h) for h in rows[0]]
            self.rows = rows[1:]
            for cb in (self.cb_x, self.cb_y):
                cb.configure(values=self.headers)
            self.cb_x.set(self.headers[0])
            self.cb_y.set(self.headers[1] if len(self.headers) > 1 else self.headers[0])
            self.lab_data.configure(text="%s：%d 行 × %d 列" %
                                    (source, len(self.rows), len(self.headers)))
            self.log("载入数据：%s（%d 行）" % (source, len(self.rows)))
            self.set_status("已载入 " + source)

        def load_sample24(self):
            self.set_data(sample_weather24(), "示例·24小时气象")
            self.ent_title.delete(0, "end")
            self.ent_title.insert(0, "小七孔一天气温变化")
            self.ent_xlab.delete(0, "end")
            self.ent_xlab.insert(0, "时刻")
            self.ent_ylab.delete(0, "end")
            self.ent_ylab.insert(0, "气温/℃")
            self.cb_type.set("折线图")
            self.draw()

        def load_sample_week(self):
            self.set_data(sample_week(), "示例·一周天气统计")
            self.ent_title.delete(0, "end")
            self.ent_title.insert(0, "小七孔一周天气占比")
            self.ent_xlab.delete(0, "end")
            self.ent_xlab.insert(0, "天气类型")
            self.ent_ylab.delete(0, "end")
            self.ent_ylab.insert(0, "天数")
            self.cb_type.set("饼图")
            self.draw()

        def import_csv(self):
            path = filedialog.askopenfilename(
                title="选择 CSV 文件", filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")])
            if not path:
                return
            try:
                rows = read_csv_auto(path)
            except Exception as e:
                messagebox.showerror("导入失败", "无法读取文件：%s" % e)
                return
            if len(rows) < 2:
                messagebox.showwarning("提示", "文件内容不足（至少需要表头 + 1 行数据）")
                return
            self.set_data(rows, os.path.basename(path))

        def reset_all(self):
            self.record = []
            self.load_sample24()
            self.set_status("已重置")

        # ---------- 绘图 ----------
        def current_config(self):
            return {
                "x_field": self.cb_x.get(), "y_field": self.cb_y.get(),
                "chart_type": self.cb_type.get(), "title": self.ent_title.get(),
                "xlabel": self.ent_xlab.get(), "ylabel": self.ent_ylab.get(),
                "color": self.cb_color.get(), "legend": bool(self.var_legend.get()),
            }

        def draw(self):
            cfg = self.current_config()
            if cfg["x_field"] not in self.headers or cfg["y_field"] not in self.headers:
                messagebox.showwarning("提示", "请先选择 X、Y 字段")
                return
            xi = self.headers.index(cfg["x_field"])
            yi = self.headers.index(cfg["y_field"])
            xlabels, xnums, ynums = extract_xy(self.rows, xi, yi)
            if not ynums:
                messagebox.showwarning(
                    "提示", "Y 字段「%s」没有数值数据，请换一个数值列" % cfg["y_field"])
                return
            ctype = cfg["chart_type"]
            if ctype == "散点图" and xnums is None:
                messagebox.showwarning(
                    "提示", "散点图需要 X 也是数值列（如「时刻」「气温」）。\n"
                    "当前 X 字段「%s」含文字，无法作散点图，请换字段或图表类型。" % cfg["x_field"])
                return
            if ctype == "饼图" and len(ynums) > 12:
                messagebox.showwarning(
                    "提示", "饼图适合类别较少的占比数据（当前 %d 项太多了）。\n"
                    "建议：载入「一周天气」示例试试，或改用折线图/柱状图。" % len(ynums))
                return
            if HAS_MPL:
                self.draw_mpl(cfg, xlabels, xnums, ynums)
            else:
                self.draw_tk(cfg, xlabels, xnums, ynums)
            self.log("绘制%s：X=%s，Y=%s，标题《%s》" %
                     (ctype, cfg["x_field"], cfg["y_field"], cfg["title"]))
            self.set_status("已绘制" + ctype)

        def draw_mpl(self, cfg, xlabels, xnums, ynums):
            color = COLOR_NAMES.get(cfg["color"], "#8b5cf6")
            fig = self.mpl_fig
            fig.clear()
            ax = fig.add_subplot(111)
            ctype = cfg["chart_type"]
            if ctype == "柱状图":
                ax.bar(range(len(ynums)), ynums, color=color, label=cfg["y_field"])
                ax.set_xticks(range(len(ynums)))
                step = max(1, len(xlabels) // 12)
                ax.set_xticklabels([l if i % step == 0 else ""
                                    for i, l in enumerate(xlabels)], fontsize=8)
            elif ctype == "折线图":
                ax.plot(range(len(ynums)), ynums, color=color, marker="o",
                        markersize=3, label=cfg["y_field"])
                ax.set_xticks(range(len(ynums)))
                step = max(1, len(xlabels) // 12)
                ax.set_xticklabels([l if i % step == 0 else ""
                                    for i, l in enumerate(xlabels)], fontsize=8)
                ax.grid(True, alpha=0.3)
            elif ctype == "饼图":
                ax.pie(ynums, labels=xlabels, autopct="%.0f%%",
                       colors=PIE_COLORS[:len(ynums)])
            else:  # 散点图
                ax.scatter(xnums, ynums, color=color, alpha=0.8, label=cfg["y_field"])
                ax.grid(True, alpha=0.3)
            ax.set_title(cfg["title"])
            if ctype != "饼图":
                ax.set_xlabel(cfg["xlabel"])
                ax.set_ylabel(cfg["ylabel"])
                if cfg["legend"]:
                    ax.legend()
            fig.tight_layout()
            self.mpl_canvas.draw()

        def draw_tk(self, cfg, xlabels, xnums, ynums):
            cv = self.tk_canvas
            cv.delete("all")
            cv.update_idletasks()
            W = max(cv.winfo_width(), 480)
            H = max(cv.winfo_height(), 360)
            color = COLOR_NAMES.get(cfg["color"], "#8b5cf6")
            ctype = cfg["chart_type"]
            cv.create_text(W / 2, 18, text=cfg["title"], font=("", 13, "bold"),
                           fill="#3b0764")
            padl, padr, padt, padb = 66, (150 if cfg["legend"] else 30), 40, 56
            iw, ih = W - padl - padr, H - padt - padb

            if ctype == "饼图":
                total = sum(ynums)
                cx, cy = padl + iw / 2, padt + ih / 2
                r = min(iw, ih) / 2 - 10
                start = 90.0
                for i, v in enumerate(ynums):
                    extent = -v / total * 360.0
                    cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=start,
                                  extent=extent, fill=PIE_COLORS[i % len(PIE_COLORS)],
                                  outline="white", width=2)
                    mid = math.radians(start + extent / 2)
                    lx = cx + math.cos(mid) * r * 0.62
                    ly = cy - math.sin(mid) * r * 0.62
                    cv.create_text(lx, ly, text="%.0f%%" % (v / total * 100),
                                   fill="white", font=("", 10, "bold"))
                    start += extent
                if cfg["legend"]:
                    for i, lab in enumerate(xlabels):
                        y = padt + 10 + i * 22
                        cv.create_rectangle(W - padr + 14, y, W - padr + 28, y + 14,
                                            fill=PIE_COLORS[i % len(PIE_COLORS)], outline="")
                        cv.create_text(W - padr + 34, y + 7, anchor="w",
                                       text="%s（%g）" % (lab, ynums[i]), font=("", 9))
                return

            # 带坐标轴的三种图
            if ctype == "散点图":
                xmin, xmax = min(xnums), max(xnums)
                if xmax == xmin:
                    xmax = xmin + 1
                xpad = (xmax - xmin) * 0.06
                xmin, xmax = xmin - xpad, xmax + xpad
            ymin = min(0, min(ynums)) if ctype == "柱状图" else min(ynums)
            ymax = max(ynums)
            if ymax == ymin:
                ymax = ymin + 1
            ypad = (ymax - ymin) * 0.12
            if ctype != "柱状图":
                ymin -= ypad
            ymax += ypad

            def sy(v):
                return padt + ih - (v - ymin) / (ymax - ymin) * ih

            cv.create_line(padl, padt, padl, padt + ih, fill="#a1a1aa")
            cv.create_line(padl, padt + ih, padl + iw, padt + ih, fill="#a1a1aa")
            for tv in nice_ticks(ymin, ymax):
                y = sy(tv)
                cv.create_line(padl - 4, y, padl, y, fill="#a1a1aa")
                cv.create_line(padl, y, padl + iw, y, fill="#f4f4f5")
                cv.create_text(padl - 8, y, anchor="e", text="%g" % round(tv, 2),
                               font=("", 8), fill="#52525b")
            cv.create_text(padl + iw, padt + ih + 34, anchor="e",
                           text=cfg["xlabel"], font=("", 9), fill="#3f3f46")
            cv.create_text(16, padt, anchor="w", text=cfg["ylabel"],
                           font=("", 9), fill="#3f3f46")

            if ctype == "散点图":
                def sx(v):
                    return padl + (v - xmin) / (xmax - xmin) * iw
                for i in range(7):
                    xv = xmin + (xmax - xmin) * i / 6
                    cv.create_line(sx(xv), padt + ih, sx(xv), padt + ih + 4, fill="#a1a1aa")
                    cv.create_text(sx(xv), padt + ih + 14, text="%g" % round(xv, 1),
                                   font=("", 8), fill="#52525b")
                for x, y in zip(xnums, ynums):
                    cv.create_oval(sx(x) - 4, sy(y) - 4, sx(x) + 4, sy(y) + 4,
                                   fill=color, outline="white")
            else:
                n = len(ynums)
                step = iw / n
                skip = max(1, n // 12)
                for i, lab in enumerate(xlabels):
                    if i % skip == 0:
                        cv.create_text(padl + step * (i + 0.5), padt + ih + 14,
                                       text=lab[:6], font=("", 8), fill="#52525b")
                if ctype == "柱状图":
                    bw = min(step * 0.62, 56)
                    for i, v in enumerate(ynums):
                        x = padl + step * i + (step - bw) / 2
                        cv.create_rectangle(x, sy(v), x + bw, sy(ymin),
                                            fill=color, outline="")
                else:  # 折线图
                    pts = []
                    for i, v in enumerate(ynums):
                        pts.extend([padl + step * (i + 0.5), sy(v)])
                    cv.create_line(*pts, fill=color, width=2, smooth=False)
                    for i, v in enumerate(ynums):
                        x = padl + step * (i + 0.5)
                        cv.create_oval(x - 3, sy(v) - 3, x + 3, sy(v) + 3,
                                       fill=color, outline="white")
            if cfg["legend"]:
                cv.create_rectangle(W - padr + 14, padt + 8, W - padr + 28, padt + 22,
                                    fill=color, outline="")
                cv.create_text(W - padr + 34, padt + 15, anchor="w",
                               text=cfg["y_field"], font=("", 9))

        # ---------- 保存 ----------
        def save_image(self):
            if HAS_MPL:
                path = filedialog.asksaveasfilename(
                    title="保存图表 PNG", defaultextension=".png",
                    initialfile="气象图表.png", filetypes=[("PNG 图片", "*.png")])
                if not path:
                    return
                try:
                    self.mpl_fig.savefig(path, dpi=150)
                except Exception as e:
                    messagebox.showerror("保存失败", str(e))
                    return
                self.log("导出图片：" + path)
                messagebox.showinfo("保存成功", "PNG 已保存到：\n" + path)
            else:
                path = filedialog.asksaveasfilename(
                    title="保存图表 PostScript", defaultextension=".ps",
                    initialfile="气象图表.ps", filetypes=[("PostScript", "*.ps")])
                if not path:
                    return
                try:
                    self.tk_canvas.postscript(file=path, colormode="color")
                except Exception as e:
                    messagebox.showerror("保存失败", str(e))
                    return
                self.log("导出图片(PostScript)：" + path)
                messagebox.showinfo(
                    "保存成功",
                    "已保存为 PostScript 文件：\n%s\n\n"
                    "提示：安装 matplotlib（pip install matplotlib）后重新运行，\n"
                    "即可直接导出 PNG 图片。" % path)

        def save_config(self):
            path = filedialog.asksaveasfilename(
                title="保存图表配置", defaultextension=".json",
                initialfile="图表配置.json", filetypes=[("JSON 文件", "*.json")])
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self.current_config(), f, ensure_ascii=False, indent=2)
            except OSError as e:
                messagebox.showerror("保存失败", str(e))
                return
            self.log("保存配置：" + path)
            self.set_status("配置已保存：" + path)

        def load_config(self):
            path = filedialog.askopenfilename(
                title="载入图表配置", filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")])
            if not path:
                return
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except (OSError, ValueError) as e:
                messagebox.showerror("载入失败", "不是有效的配置文件：%s" % e)
                return
            if cfg.get("x_field") in self.headers:
                self.cb_x.set(cfg["x_field"])
            if cfg.get("y_field") in self.headers:
                self.cb_y.set(cfg["y_field"])
            if cfg.get("chart_type") in CHART_TYPES:
                self.cb_type.set(cfg["chart_type"])
            for ent, key in ((self.ent_title, "title"), (self.ent_xlab, "xlabel"),
                             (self.ent_ylab, "ylabel")):
                if key in cfg:
                    ent.delete(0, "end")
                    ent.insert(0, str(cfg[key]))
            if cfg.get("color") in COLOR_NAMES:
                self.cb_color.set(cfg["color"])
            self.var_legend.set(bool(cfg.get("legend", True)))
            self.log("载入配置：" + path)
            self.draw()

        def export_record(self):
            path = filedialog.asksaveasfilename(
                title="导出实验记录", defaultextension=".txt",
                initialfile="可视化实验记录.txt", filetypes=[("文本文件", "*.txt")])
            if not path:
                return
            lines = ["====== 数据可视化实验记录（数据可视化设计器）======", ""]
            lines.append("绘图引擎：%s" % ("matplotlib" if HAS_MPL else "tkinter.Canvas 自绘"))
            lines.append("")
            if self.record:
                lines.extend("%d. %s" % (i + 1, r) for i, r in enumerate(self.record))
            else:
                lines.append("（暂无操作记录）")
            lines.append("")
            lines.append("当前图表配置：")
            lines.append(json.dumps(self.current_config(), ensure_ascii=False, indent=2))
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
            except OSError as e:
                messagebox.showerror("导出失败", str(e))
                return
            messagebox.showinfo("导出成功", "实验记录已保存到：\n" + path)

        def show_help(self):
            win = tk.Toplevel(self.root)
            win.title("帮助 · 图表选择与使用说明")
            win.geometry("560x480")
            t = tk.Text(win, wrap="word", font=("", 10), padx=10, pady=8)
            t.pack(fill="both", expand=True)
            t.insert("end",
                     "【使用流程】\n"
                     "1. 载入数据：导入 CSV，或点「示例：24小时气象 / 一周天气」。\n"
                     "2. 选择 X / Y 字段和图表类型，填好标题与坐标轴名称。\n"
                     "3. 点「绘制图表」查看效果，满意后「保存图片」。\n"
                     "4. 「保存配置 JSON」记录本次设计，下次可一键复现。\n\n"
                     "【怎样选图表类型】（教材第4节要点）\n"
                     "· 柱状图：比较数据大小最直观（如各月降水量对比）。\n"
                     "· 折线图：反映数据变化趋势（如一天气温变化）。\n"
                     "· 饼图：表示各部分占总体的百分比（如一周天气占比），\n"
                     "  注意各部分合计应为 100%。\n"
                     "· 散点图：观察两个数值变量的关系（如气温与湿度）。\n"
                     "记住：图表最重要的是可读性——过分追求美观而无法有效\n"
                     "传达信息的图表是失败的。\n\n"
                     "【两种绘图引擎】\n"
                     "· 已安装 matplotlib：嵌入高质量图表，支持 PNG 导出，\n"
                     "  对应教材中 plt.plot / plt.bar / plt.scatter / plt.pie。\n"
                     "· 未安装 matplotlib：使用 tkinter.Canvas 自绘（无需联网\n"
                     "  安装任何东西），图片可另存为 PostScript(.ps)。\n\n"
                     "【常见问题】\n"
                     "· 提示 Y 字段无数值：请把 Y 换成数值列（如「气温」）。\n"
                     "· 散点图要求 X 也是数值列。\n"
                     "· 饼图项目太多：请使用类别少的数据（如一周天气）。\n"
                     "· 中文乱码：CSV 建议保存为 UTF-8 编码。\n"
                     "· matplotlib 中文显示为方块：系统缺中文字体，可改用\n"
                     "  Canvas 自绘模式（卸载 matplotlib）或安装中文字体。\n")
            t.configure(state="disabled")

        def log(self, text):
            self.record.append(text)

        def set_status(self, text):
            self.status.configure(text=text)

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
