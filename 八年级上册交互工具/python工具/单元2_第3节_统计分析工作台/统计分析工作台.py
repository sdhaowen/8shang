# -*- coding: utf-8 -*-
"""
统计分析工作台
==========================================================
课时：清华版《信息科技》八年级上册 第2单元 第3节《数据的统计分析》
配套项目：在线数字气象站（荔波小七孔气温探究）

功能：
  1. 导入 CSV 数据（自动检测 UTF-8 / GBK 等常见编码），或一键载入
     内置的"小七孔 24 小时气象示例数据"。
  2. 选择字段，计算 计数/总和/平均/中位数/众数/最大/最小/极差/标准差。
  3. 分组统计：按某一列分组，对另一数值列求平均，表格 + 柱状图对比。
  4. 简单线性回归：手写最小二乘法，输出斜率、截距，可输入自变量做预测，
     散点 + 趋势线图。
  5. 分析结论文本区（可编辑），一键导出分析报告 TXT 与统计结果 CSV。
  6. 帮助窗口解释各统计量的含义。

运行方法：
  python3 统计分析工作台.py
  仅依赖 Python 标准库（tkinter、statistics、csv）。
  如已安装 pandas，程序会自动用 pandas 读取 CSV（可选加速，非必需）。
"""

import csv
import io
import json
import math
import os
import statistics
import sys

try:
    import pandas as _pd  # 可选加速，未安装时自动降级为标准库
except ImportError:
    _pd = None

APP_TITLE = "统计分析工作台 · 第2单元第3节 数据的统计分析"

# ---------------------------------------------------------------
# 内置示例数据：小七孔气象站一天 24 小时记录（教学示例数据）
# ---------------------------------------------------------------
SAMPLE_HEADERS = ["时刻", "气温", "湿度", "光照", "风力", "时段"]
_TEMPS = [13.5, 13.1, 12.8, 12.4, 12.1, 11.8, 11.5, 12.3, 14.0, 16.2, 18.5, 20.6,
          22.4, 23.8, 24.6, 24.2, 23.3, 21.8, 19.9, 18.2, 16.8, 15.6, 14.7, 14.0]
_HUMS = [88, 89, 90, 91, 92, 93, 94, 90, 84, 78, 72, 66,
         61, 57, 55, 56, 59, 64, 70, 75, 79, 82, 84, 86]
_LIGHT = [0, 0, 0, 0, 0, 0, 2, 8, 20, 35, 48, 58,
          65, 68, 66, 58, 45, 28, 12, 3, 0, 0, 0, 0]
_WIND = [1.2, 1.0, 0.9, 0.8, 0.8, 0.7, 0.9, 1.1, 1.4, 1.8, 2.2, 2.5,
         2.8, 3.0, 3.1, 2.9, 2.6, 2.2, 1.9, 1.6, 1.4, 1.3, 1.2, 1.1]


def sample_rows():
    """返回内置示例数据（列表的列表，含表头）。"""
    rows = [SAMPLE_HEADERS[:]]
    for h in range(24):
        duan = "白天" if 8 <= h <= 18 else "夜间"
        rows.append([str(h), str(_TEMPS[h]), str(_HUMS[h]),
                     str(_LIGHT[h]), str(_WIND[h]), duan])
    return rows


# ---------------------------------------------------------------
# 纯计算函数（不依赖 GUI，便于自测）
# ---------------------------------------------------------------
def to_float(s):
    """尝试把字符串转为 float，失败返回 None。"""
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def numeric_column(rows, col_index):
    """提取某列中所有能转成数值的数据。rows 不含表头。"""
    out = []
    for r in rows:
        if col_index < len(r):
            v = to_float(r[col_index])
            if v is not None:
                out.append(v)
    return out


def compute_stats(values):
    """对数值列表计算常见统计量，返回 (名称, 值) 列表。"""
    if not values:
        return []
    res = [
        ("计数", len(values)),
        ("总和", round(sum(values), 4)),
        ("平均值", round(statistics.fmean(values), 4)),
        ("中位数", round(statistics.median(values), 4)),
    ]
    try:
        res.append(("众数", statistics.mode(values)))
    except statistics.StatisticsError:
        res.append(("众数", "无唯一众数"))
    res.append(("最大值", max(values)))
    res.append(("最小值", min(values)))
    res.append(("极差", round(max(values) - min(values), 4)))
    if len(values) >= 2:
        res.append(("标准差", round(statistics.stdev(values), 4)))
    else:
        res.append(("标准差", "样本不足"))
    return res


def group_mean(rows, group_idx, value_idx):
    """按 group_idx 列分组，对 value_idx 列求平均。返回 [(组名, 平均值, 个数)]，按组名排序。"""
    buckets = {}
    for r in rows:
        if group_idx < len(r) and value_idx < len(r):
            v = to_float(r[value_idx])
            if v is None:
                continue
            key = str(r[group_idx]).strip()
            buckets.setdefault(key, []).append(v)
    out = []
    for key in sorted(buckets.keys()):
        vals = buckets[key]
        out.append((key, round(statistics.fmean(vals), 4), len(vals)))
    return out


def linreg(xs, ys):
    """手写最小二乘法。返回 (斜率 b, 截距 a)，即 y = b*x + a。数据不足返回 None。"""
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    xs, ys = xs[:n], ys[:n]
    sx = sum(xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxx = sum(x * x for x in xs)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:
        return None
    b = (n * sxy - sx * sy) / denom
    a = (sy - b * sx) / n
    return (b, a)


def reg_rmse(xs, ys, b, a):
    """回归的均方根误差。"""
    n = min(len(xs), len(ys))
    if n == 0:
        return 0.0
    s = sum((ys[i] - (b * xs[i] + a)) ** 2 for i in range(n))
    return math.sqrt(s / n)


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
    if _pd is not None:
        try:
            df = _pd.read_csv(io.StringIO(text))
            rows = [list(map(str, df.columns))]
            for _, row in df.iterrows():
                rows.append([str(x) for x in row.tolist()])
            return rows
        except Exception:
            pass  # pandas 解析失败则退回标准库
    reader = csv.reader(io.StringIO(text))
    return [row for row in reader if any(str(c).strip() for c in row)]


# ---------------------------------------------------------------
# GUI 部分
# ---------------------------------------------------------------
def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    class App:
        def __init__(self, root):
            self.root = root
            root.title(APP_TITLE)
            root.geometry("1060x680")
            root.minsize(900, 560)
            self.headers = []
            self.rows = []
            self.last_stats = []          # [(统计量, 值)]
            self.last_group = []          # [(组, 平均, 个数)]
            self.last_reg = None          # (b, a, rmse, x字段, y字段)
            self.record = []              # 实验记录行
            self._build()
            self.load_sample()

        # ---------- 界面搭建 ----------
        def _build(self):
            root = self.root
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass
            style.configure("TButton", padding=5)
            style.configure("Title.TLabel", font=("", 11, "bold"), foreground="#4f46e5")

            # 顶部工具条
            top = ttk.Frame(root, padding=(8, 6))
            top.pack(fill="x")
            ttk.Button(top, text="导入 CSV", command=self.import_csv).pack(side="left", padx=3)
            ttk.Button(top, text="载入内置气象示例", command=self.load_sample).pack(side="left", padx=3)
            ttk.Button(top, text="重置", command=self.reset_all).pack(side="left", padx=3)
            ttk.Button(top, text="导出报告 TXT", command=self.export_txt).pack(side="left", padx=3)
            ttk.Button(top, text="导出结果 CSV", command=self.export_csv).pack(side="left", padx=3)
            ttk.Button(top, text="帮助", command=self.show_help).pack(side="right", padx=3)
            self.pandas_lab = ttk.Label(
                top, text=("pandas：已启用加速" if _pd is not None else "pandas：未安装（标准库模式）"),
                foreground="#059669" if _pd is not None else "#92400e")
            self.pandas_lab.pack(side="right", padx=8)

            body = ttk.Frame(root, padding=6)
            body.pack(fill="both", expand=True)
            body.columnconfigure(1, weight=1)
            body.rowconfigure(0, weight=1)

            # 左侧：操作区
            left = ttk.Frame(body)
            left.grid(row=0, column=0, sticky="ns", padx=(0, 6))

            f1 = ttk.LabelFrame(left, text="① 描述统计", padding=8)
            f1.pack(fill="x", pady=(0, 6))
            ttk.Label(f1, text="数值字段：").grid(row=0, column=0, sticky="w")
            self.cb_field = ttk.Combobox(f1, state="readonly", width=14)
            self.cb_field.grid(row=0, column=1, pady=2)
            ttk.Button(f1, text="计算统计量", command=self.do_stats).grid(
                row=1, column=0, columnspan=2, sticky="ew", pady=3)

            f2 = ttk.LabelFrame(left, text="② 分组统计（平均分析+对比）", padding=8)
            f2.pack(fill="x", pady=6)
            ttk.Label(f2, text="分组字段：").grid(row=0, column=0, sticky="w")
            self.cb_group = ttk.Combobox(f2, state="readonly", width=14)
            self.cb_group.grid(row=0, column=1, pady=2)
            ttk.Label(f2, text="求平均字段：").grid(row=1, column=0, sticky="w")
            self.cb_gval = ttk.Combobox(f2, state="readonly", width=14)
            self.cb_gval.grid(row=1, column=1, pady=2)
            ttk.Button(f2, text="分组求平均并画柱状图", command=self.do_group).grid(
                row=2, column=0, columnspan=2, sticky="ew", pady=3)

            f3 = ttk.LabelFrame(left, text="③ 回归分析（最小二乘）", padding=8)
            f3.pack(fill="x", pady=6)
            ttk.Label(f3, text="自变量 X：").grid(row=0, column=0, sticky="w")
            self.cb_x = ttk.Combobox(f3, state="readonly", width=14)
            self.cb_x.grid(row=0, column=1, pady=2)
            ttk.Label(f3, text="因变量 Y：").grid(row=1, column=0, sticky="w")
            self.cb_y = ttk.Combobox(f3, state="readonly", width=14)
            self.cb_y.grid(row=1, column=1, pady=2)
            ttk.Button(f3, text="拟合趋势线并画散点图", command=self.do_reg).grid(
                row=2, column=0, columnspan=2, sticky="ew", pady=3)
            ttk.Label(f3, text="预测：输入 X =").grid(row=3, column=0, sticky="w")
            self.ent_pred = ttk.Entry(f3, width=10)
            self.ent_pred.grid(row=3, column=1, sticky="w", pady=2)
            ttk.Button(f3, text="预测 Y 值", command=self.do_predict).grid(
                row=4, column=0, columnspan=2, sticky="ew", pady=3)
            self.lab_pred = ttk.Label(f3, text="（先拟合，再预测）", foreground="#64748b")
            self.lab_pred.grid(row=5, column=0, columnspan=2, sticky="w")

            # 右侧：结果区（选项卡）
            self.nb = ttk.Notebook(body)
            self.nb.grid(row=0, column=1, sticky="nsew")

            # 数据表页
            page_data = ttk.Frame(self.nb)
            self.nb.add(page_data, text=" 数据表 ")
            self.tree_data = ttk.Treeview(page_data, show="headings", height=12)
            ysb = ttk.Scrollbar(page_data, orient="vertical", command=self.tree_data.yview)
            xsb = ttk.Scrollbar(page_data, orient="horizontal", command=self.tree_data.xview)
            self.tree_data.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
            self.tree_data.pack(side="left", fill="both", expand=True)
            ysb.pack(side="right", fill="y")
            xsb.pack(side="bottom", fill="x")

            # 统计结果页
            page_stat = ttk.Frame(self.nb)
            self.nb.add(page_stat, text=" 统计结果 ")
            self.tree_stat = ttk.Treeview(page_stat, show="headings",
                                          columns=("k", "v"), height=10)
            self.tree_stat.heading("k", text="统计量")
            self.tree_stat.heading("v", text="数值")
            self.tree_stat.column("k", width=140, anchor="center")
            self.tree_stat.column("v", width=180, anchor="center")
            self.tree_stat.pack(fill="both", expand=True, padx=4, pady=4)

            # 分组统计页
            page_grp = ttk.Frame(self.nb)
            self.nb.add(page_grp, text=" 分组统计 ")
            page_grp.columnconfigure(0, weight=1)
            page_grp.rowconfigure(1, weight=1)
            self.tree_grp = ttk.Treeview(page_grp, show="headings",
                                         columns=("g", "m", "n"), height=5)
            for c, t, w in (("g", "组别", 120), ("m", "平均值", 120), ("n", "数据个数", 90)):
                self.tree_grp.heading(c, text=t)
                self.tree_grp.column(c, width=w, anchor="center")
            self.tree_grp.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
            self.cv_bar = tk.Canvas(page_grp, bg="white", highlightthickness=1,
                                    highlightbackground="#cbd5e1")
            self.cv_bar.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)

            # 回归图页
            page_reg = ttk.Frame(self.nb)
            self.nb.add(page_reg, text=" 回归散点图 ")
            self.cv_reg = tk.Canvas(page_reg, bg="white", highlightthickness=1,
                                    highlightbackground="#cbd5e1")
            self.cv_reg.pack(fill="both", expand=True, padx=4, pady=4)

            # 结论页
            page_conc = ttk.Frame(self.nb)
            self.nb.add(page_conc, text=" 分析结论（可编辑） ")
            ttk.Label(page_conc, text="程序会自动追加结论草稿，你可以像分析师一样修改措辞：",
                      style="Title.TLabel").pack(anchor="w", padx=6, pady=(6, 2))
            self.txt_conc = tk.Text(page_conc, wrap="word", height=14, font=("", 10))
            self.txt_conc.pack(fill="both", expand=True, padx=6, pady=4)
            self.txt_conc.insert("end", "【分析结论草稿区】\n")

            # 状态栏
            self.status = ttk.Label(root, text="就绪", anchor="w", relief="sunken", padding=(8, 3))
            self.status.pack(fill="x", side="bottom")

        # ---------- 数据载入 ----------
        def set_data(self, rows, source):
            if not rows:
                self.set_status("数据为空")
                return
            self.headers = [str(h) for h in rows[0]]
            self.rows = rows[1:]
            cols = [str(i) for i in range(len(self.headers))]
            self.tree_data.configure(columns=cols)
            for i, h in enumerate(self.headers):
                self.tree_data.heading(str(i), text=h)
                self.tree_data.column(str(i), width=90, anchor="center")
            for it in self.tree_data.get_children():
                self.tree_data.delete(it)
            for r in self.rows:
                self.tree_data.insert("", "end", values=r)
            for cb in (self.cb_field, self.cb_group, self.cb_gval, self.cb_x, self.cb_y):
                cb.configure(values=self.headers)
            # 智能默认
            def pick(name, default_idx):
                return name if name in self.headers else self.headers[min(default_idx, len(self.headers) - 1)]
            self.cb_field.set(pick("气温", 1))
            self.cb_group.set(pick("时段", 0))
            self.cb_gval.set(pick("气温", 1))
            self.cb_x.set(pick("时刻", 0))
            self.cb_y.set(pick("气温", 1))
            self.nb.select(0)
            self.record.append("载入数据：%s（%d 行 × %d 列）" % (source, len(self.rows), len(self.headers)))
            self.set_status("已载入 %s：%d 行 × %d 列" % (source, len(self.rows), len(self.headers)))

        def load_sample(self):
            self.set_data(sample_rows(), "内置小七孔24小时气象示例")

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
            self.set_data(rows, os.path.basename(path))

        def reset_all(self):
            self.last_stats, self.last_group, self.last_reg = [], [], None
            self.record = []
            for it in self.tree_stat.get_children():
                self.tree_stat.delete(it)
            for it in self.tree_grp.get_children():
                self.tree_grp.delete(it)
            self.cv_bar.delete("all")
            self.cv_reg.delete("all")
            self.txt_conc.delete("1.0", "end")
            self.txt_conc.insert("end", "【分析结论草稿区】\n")
            self.lab_pred.configure(text="（先拟合，再预测）")
            self.load_sample()
            self.set_status("已重置")

        # ---------- 分析动作 ----------
        def _col_index(self, combo):
            name = combo.get()
            if name in self.headers:
                return self.headers.index(name)
            return -1

        def do_stats(self):
            ci = self._col_index(self.cb_field)
            if ci < 0:
                messagebox.showwarning("提示", "请先选择字段")
                return
            vals = numeric_column(self.rows, ci)
            if not vals:
                messagebox.showwarning("提示", "该字段没有可用的数值数据，请换一个字段")
                return
            self.last_stats = compute_stats(vals)
            for it in self.tree_stat.get_children():
                self.tree_stat.delete(it)
            for k, v in self.last_stats:
                self.tree_stat.insert("", "end", values=(k, v))
            self.nb.select(1)
            name = self.cb_field.get()
            d = dict(self.last_stats)
            conc = ("「%s」共 %s 个数据：平均 %s，中位数 %s，最大 %s，最小 %s，极差 %s。" %
                    (name, d.get("计数"), d.get("平均值"), d.get("中位数"),
                     d.get("最大值"), d.get("最小值"), d.get("极差")))
            self.append_conclusion(conc)
            self.record.append("描述统计（%s）：%s" % (name, "; ".join("%s=%s" % (k, v) for k, v in self.last_stats)))
            self.set_status("统计完成：字段「%s」" % name)

        def do_group(self):
            gi, vi = self._col_index(self.cb_group), self._col_index(self.cb_gval)
            if gi < 0 or vi < 0:
                messagebox.showwarning("提示", "请选择分组字段和求平均字段")
                return
            res = group_mean(self.rows, gi, vi)
            if not res:
                messagebox.showwarning("提示", "分组结果为空，请检查字段选择（求平均字段应为数值列）")
                return
            if len(res) > 24:
                messagebox.showwarning("提示", "分组数太多（%d 组），请选择类别较少的分组字段（如「时段」）" % len(res))
                return
            self.last_group = res
            for it in self.tree_grp.get_children():
                self.tree_grp.delete(it)
            for g, m, n in res:
                self.tree_grp.insert("", "end", values=(g, m, n))
            self.draw_bar(res, "各「%s」的「%s」平均值对比" % (self.cb_group.get(), self.cb_gval.get()))
            self.nb.select(2)
            top = max(res, key=lambda t: t[1])
            conc = "按「%s」分组对比：「%s」组的平均「%s」最高，为 %s。" % (
                self.cb_group.get(), top[0], self.cb_gval.get(), top[1])
            self.append_conclusion(conc)
            self.record.append("分组统计：" + "; ".join("%s=%s(n=%d)" % t for t in res))
            self.set_status("分组统计完成，共 %d 组" % len(res))

        def do_reg(self):
            xi, yi = self._col_index(self.cb_x), self._col_index(self.cb_y)
            if xi < 0 or yi < 0:
                messagebox.showwarning("提示", "请选择 X、Y 字段")
                return
            xs, ys = [], []
            for r in self.rows:
                if xi < len(r) and yi < len(r):
                    x, y = to_float(r[xi]), to_float(r[yi])
                    if x is not None and y is not None:
                        xs.append(x)
                        ys.append(y)
            res = linreg(xs, ys)
            if res is None:
                messagebox.showwarning("提示", "数据不足或 X 全部相同，无法拟合，请换字段")
                return
            b, a = res
            e = reg_rmse(xs, ys, b, a)
            self.last_reg = (b, a, e, self.cb_x.get(), self.cb_y.get())
            self.draw_scatter(xs, ys, b, a,
                              "「%s→%s」散点与最小二乘趋势线" % (self.cb_x.get(), self.cb_y.get()),
                              self.cb_x.get(), self.cb_y.get())
            self.nb.select(3)
            trend = "上升" if b > 0 else ("下降" if b < 0 else "持平")
            conc = ("回归分析：%s 每增加 1，%s 平均变化 %+.4f（%s趋势），"
                    "拟合直线 y = %.4f×x %+.4f，RMSE=%.3f。" %
                    (self.cb_x.get(), self.cb_y.get(), b, trend, b, a, e))
            self.append_conclusion(conc)
            self.record.append("回归：y=%.4f*x%+.4f RMSE=%.3f (X=%s,Y=%s)" %
                               (b, a, e, self.cb_x.get(), self.cb_y.get()))
            self.lab_pred.configure(text="已拟合：y = %.3f×x %+.3f" % (b, a))
            self.set_status("回归拟合完成：斜率 %.4f，截距 %.4f" % (b, a))

        def do_predict(self):
            if self.last_reg is None:
                messagebox.showinfo("提示", "请先点击「拟合趋势线」得到回归方程，再做预测")
                return
            v = to_float(self.ent_pred.get())
            if v is None:
                messagebox.showwarning("提示", "请输入一个数字作为 X 值（如 25 表示 25 时/第25个单位）")
                return
            b, a, e, xn, yn = self.last_reg
            pred = b * v + a
            self.lab_pred.configure(text="当 %s=%g 时，预测 %s ≈ %.3f" % (xn, v, yn, pred))
            self.append_conclusion("预测：当 %s=%g 时，%s ≈ %.3f（外推预测是粗略的，仅供参考）。" % (xn, v, yn, pred))
            self.record.append("预测：%s=%g → %s≈%.3f" % (xn, v, yn, pred))
            self.set_status("预测完成")

        # ---------- 绘图 ----------
        def draw_bar(self, data, title):
            cv = self.cv_bar
            cv.delete("all")
            cv.update_idletasks()
            W = max(cv.winfo_width(), 420)
            H = max(cv.winfo_height(), 240)
            padl, padr, padt, padb = 60, 20, 36, 44
            vmax = max(d[1] for d in data)
            vmin = min(0, min(d[1] for d in data))
            if vmax == vmin:
                vmax = vmin + 1
            span = (vmax - vmin) * 1.15
            def sy(v):
                return H - padb - (v - vmin) / span * (H - padt - padb)
            cv.create_text(W / 2, 16, text=title, font=("", 11, "bold"), fill="#312e81")
            cv.create_line(padl, padt, padl, H - padb, fill="#94a3b8")
            cv.create_line(padl, H - padb, W - padr, H - padb, fill="#94a3b8")
            # y 轴刻度
            step = max(round(span / 5, 2), 0.01)
            t = vmin
            while t <= vmin + span + 1e-9:
                y = sy(t)
                cv.create_line(padl - 4, y, padl, y, fill="#94a3b8")
                cv.create_line(padl, y, W - padr, y, fill="#eef2ff")
                cv.create_text(padl - 8, y, text=("%g" % round(t, 2)), anchor="e",
                               font=("", 8), fill="#64748b")
                t += step
            n = len(data)
            bw = min(70, (W - padl - padr) / n * 0.6)
            gap = (W - padl - padr) / n
            colors = ["#6366f1", "#818cf8", "#a5b4fc", "#4f46e5", "#4338ca", "#c7d2fe"]
            for i, (g, m, cnt) in enumerate(data):
                x = padl + gap * i + (gap - bw) / 2
                cv.create_rectangle(x, sy(m), x + bw, sy(vmin), fill=colors[i % len(colors)], outline="")
                cv.create_text(x + bw / 2, sy(m) - 9, text=("%g" % m), font=("", 9), fill="#312e81")
                cv.create_text(x + bw / 2, H - padb + 14, text=str(g)[:8], font=("", 9), fill="#334155")
            cv.create_text(W - padr, H - padb + 30, text="组别", anchor="e", font=("", 9), fill="#64748b")

        def draw_scatter(self, xs, ys, b, a, title, xname, yname):
            cv = self.cv_reg
            cv.delete("all")
            cv.update_idletasks()
            W = max(cv.winfo_width(), 420)
            H = max(cv.winfo_height(), 260)
            padl, padr, padt, padb = 64, 24, 36, 46
            xmin, xmax = min(xs), max(xs)
            ymin, ymax = min(ys), max(ys)
            if xmax == xmin:
                xmax = xmin + 1
            if ymax == ymin:
                ymax = ymin + 1
            xpad = (xmax - xmin) * 0.08
            ypad = (ymax - ymin) * 0.12
            xmin, xmax = xmin - xpad, xmax + xpad
            ymin, ymax = ymin - ypad, ymax + ypad
            def sx(x):
                return padl + (x - xmin) / (xmax - xmin) * (W - padl - padr)
            def sy(y):
                return H - padb - (y - ymin) / (ymax - ymin) * (H - padt - padb)
            cv.create_text(W / 2, 16, text=title, font=("", 11, "bold"), fill="#312e81")
            cv.create_line(padl, padt, padl, H - padb, fill="#94a3b8")
            cv.create_line(padl, H - padb, W - padr, H - padb, fill="#94a3b8")
            for i in range(6):
                xv = xmin + (xmax - xmin) * i / 5
                yv = ymin + (ymax - ymin) * i / 5
                cv.create_line(sx(xv), H - padb, sx(xv), H - padb + 4, fill="#94a3b8")
                cv.create_text(sx(xv), H - padb + 14, text="%g" % round(xv, 1), font=("", 8), fill="#64748b")
                cv.create_line(padl - 4, sy(yv), padl, sy(yv), fill="#94a3b8")
                cv.create_line(padl, sy(yv), W - padr, sy(yv), fill="#eef2ff")
                cv.create_text(padl - 8, sy(yv), text="%g" % round(yv, 1), anchor="e", font=("", 8), fill="#64748b")
            cv.create_text(W - padr, H - padb + 30, text=xname, anchor="e", font=("", 9), fill="#334155")
            cv.create_text(14, padt + 4, text=yname, anchor="w", font=("", 9), fill="#334155")
            for x, y in zip(xs, ys):
                cv.create_oval(sx(x) - 3, sy(y) - 3, sx(x) + 3, sy(y) + 3,
                               fill="#6366f1", outline="white")
            # 趋势线
            y1, y2 = b * xmin + a, b * xmax + a
            cv.create_line(sx(xmin), sy(y1), sx(xmax), sy(y2), fill="#dc2626", width=2, dash=(6, 4))
            cv.create_text(W - padr - 6, padt + 14, anchor="e", fill="#dc2626", font=("", 9),
                           text="趋势线 y = %.3f×x %+.3f" % (b, a))

        # ---------- 结论与导出 ----------
        def append_conclusion(self, text):
            self.txt_conc.insert("end", "· " + text + "\n")
            self.txt_conc.see("end")

        def export_txt(self):
            path = filedialog.asksaveasfilename(
                title="导出分析报告", defaultextension=".txt",
                initialfile="气象数据分析报告.txt", filetypes=[("文本文件", "*.txt")])
            if not path:
                return
            lines = ["====== 气象数据分析报告（统计分析工作台）======", ""]
            lines.append("【实验记录】")
            lines.extend("  %d. %s" % (i + 1, r) for i, r in enumerate(self.record))
            if self.last_stats:
                lines.append("")
                lines.append("【描述统计】")
                lines.extend("  %s：%s" % (k, v) for k, v in self.last_stats)
            if self.last_group:
                lines.append("")
                lines.append("【分组统计】")
                lines.extend("  %s：平均 %s（%d 个数据）" % t for t in self.last_group)
            if self.last_reg:
                b, a, e, xn, yn = self.last_reg
                lines.append("")
                lines.append("【回归分析】y = %.4f×x %+.4f（X=%s，Y=%s，RMSE=%.3f）" % (b, a, xn, yn, e))
            lines.append("")
            lines.append("【分析结论】")
            lines.append(self.txt_conc.get("1.0", "end").strip())
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
            except OSError as e:
                messagebox.showerror("导出失败", str(e))
                return
            self.set_status("报告已导出：" + path)
            messagebox.showinfo("导出成功", "分析报告已保存到：\n" + path)

        def export_csv(self):
            if not (self.last_stats or self.last_group):
                messagebox.showinfo("提示", "请先执行「描述统计」或「分组统计」，再导出结果")
                return
            path = filedialog.asksaveasfilename(
                title="导出统计结果 CSV", defaultextension=".csv",
                initialfile="统计结果.csv", filetypes=[("CSV 文件", "*.csv")])
            if not path:
                return
            try:
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f)
                    if self.last_stats:
                        w.writerow(["描述统计（字段：%s）" % self.cb_field.get()])
                        w.writerow(["统计量", "数值"])
                        w.writerows(self.last_stats)
                        w.writerow([])
                    if self.last_group:
                        w.writerow(["分组统计（%s 分组，求 %s 平均）" % (self.cb_group.get(), self.cb_gval.get())])
                        w.writerow(["组别", "平均值", "数据个数"])
                        w.writerows(self.last_group)
            except OSError as e:
                messagebox.showerror("导出失败", str(e))
                return
            self.set_status("结果已导出：" + path)
            messagebox.showinfo("导出成功", "统计结果已保存到：\n" + path)

        def show_help(self):
            win = tk.Toplevel(self.root)
            win.title("帮助 · 统计量含义与使用说明")
            win.geometry("560x480")
            t = tk.Text(win, wrap="word", font=("", 10), padx=10, pady=8)
            t.pack(fill="both", expand=True)
            t.insert("end",
                     "【使用流程】\n"
                     "1. 导入 CSV（自动识别编码）或点「载入内置气象示例」。\n"
                     "2. ① 描述统计：选一个数值字段（如「气温」），计算九种统计量。\n"
                     "3. ② 分组统计：如按「时段」分组求「气温」平均，比较白天与夜间。\n"
                     "4. ③ 回归分析：如 X=时刻、Y=气温，拟合趋势线，再输入 X 做预测。\n"
                     "5. 在「分析结论」页修改措辞，最后导出报告 TXT / 结果 CSV。\n\n"
                     "【统计量含义】\n"
                     "· 计数：数据的个数。\n"
                     "· 总和：所有数据相加。\n"
                     "· 平均值：总和÷个数，反映整体水平，但会被极端值拉动。\n"
                     "· 中位数：排序后位于中间的值，对极端值稳健。\n"
                     "· 众数：出现次数最多的值。\n"
                     "· 最大/最小值：数据的上下边界（如一天的最高/最低气温）。\n"
                     "· 极差：最大值−最小值，反映波动范围（如一天温差）。\n"
                     "· 标准差：数据偏离平均值的平均程度，越大越分散。\n\n"
                     "【回归分析】\n"
                     "用最小二乘法找一条使所有点偏差平方和最小的直线 y=b·x+a：\n"
                     "b 是斜率（X 每增加 1，Y 平均变化多少），a 是截距。\n"
                     "RMSE 是均方根误差，越小说明直线越贴近数据。\n"
                     "注意：外推预测只是粗略估计，离数据范围越远越不可靠。\n\n"
                     "【常见问题】\n"
                     "· 提示「没有可用数值」：所选列是文字列，请换数值列。\n"
                     "· 分组太多：请选类别少的列（如「时段」）作分组字段。\n"
                     "· 中文乱码：程序已自动尝试 UTF-8/GBK 等编码，仍失败请将\n"
                     "  文件另存为 UTF-8 编码的 CSV。\n")
            t.configure(state="disabled")

        def set_status(self, text):
            self.status.configure(text=text)

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
