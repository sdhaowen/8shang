# -*- coding: utf-8 -*-
"""
课时：清华大学出版社《信息科技》八年级上册 第2单元 第1节《从数据到大数据》
工具：数据与大数据实验室（Tkinter GUI，仅使用 Python 标准库）
功能：
  1. 生成示例数据集：模拟一天 24 小时气象记录（呼应"在线数字气象站"项目）、
     模拟共享单车骑行记录；统计数据量与字段类型。
  2. 数据产生速度模拟：可调每秒生成条数，观察计数器与内存估算的增长（体验大数据的高速性）。
  3. 存储空间估算：条数 × 单条字节，换算 KB/MB/GB，并给出《红楼梦》/电影等直观类比（体验巨量性）。
  4. "数据—信息—知识"卡片编辑器：三栏输入，保存为卡片列表，可导出。
  5. 模拟交通拥堵数据表：随机生成各路段车速记录，统计各路段平均车速（体验价值性）。
  6. 数据可导出 CSV / 实验记录可保存；提供重置、导入、帮助。
运行方法：python3 数据与大数据实验室.py
"""

import csv
import json
import random
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime, timedelta

APP_TITLE = "数据与大数据实验室 · 第2单元第1节《从数据到大数据》"

WEATHER_FIELDS = ["时间", "气温(℃)", "湿度(%)", "光照(lx)", "风力(级)"]
BIKE_FIELDS = ["记录号", "时刻", "起点站", "终点站", "骑行分钟"]
TRAFFIC_FIELDS = ["路段", "时刻", "车速(km/h)"]
ROADS = ["学校路", "滨湖大道", "青云街", "科技园路", "小七孔大道", "环城快线"]
STATIONS = ["学校", "体育馆", "公园", "市中心", "商场", "图书馆", "科技园", "火车站"]

HELP_TEXT = """【数据与大数据实验室 · 使用帮助】

一、数据集生成（标签页1）
  · 点击"生成气象数据集"：模拟在线数字气象站一天 24 小时的观测记录
    （气温呈"14时前后最高、日出前后最低"的规律，可多生成几天验证）。
  · 点击"生成骑行数据集"：模拟共享单车骑行记录（数量可调）。
  · 右侧自动统计：记录条数、每个字段的类型（数值型/文本型）。
  · 可将当前数据集导出为 CSV，也可导入已有 CSV 查看。

二、产生速度模拟（标签页2）
  · 拖动滑块设定"每秒生成条数"，点击"开始"，观察累计条数和内存
    估算不断增长——这就是大数据"高速性"的直观体验。
  · 随时"暂停/继续"，"归零"可重新开始。

三、存储空间估算（标签页2 下半部分）
  · 输入数据条数与单条字节数，点击"估算"，自动换算 KB/MB/GB/TB，
    并给出"相当于多少部《红楼梦》/多少部高清电影"的类比。

四、数据—信息—知识卡片（标签页3）
  · 在三栏分别写：原始数据 → 场景中的信息 → 归纳出的知识，
    点击"保存卡片"加入列表，可删除、可随实验记录一起导出。

五、交通拥堵数据（标签页4）
  · 点击"生成交通数据"得到各路段的车速记录表；
  · 点击"统计平均车速"查看每个路段的平均车速并判断是否拥堵，
    体会"海量记录 → 有用规律"的提炼过程。

六、菜单栏
  · 文件：导入 CSV / 导出当前数据集 CSV / 保存实验记录 / 退出
  · 操作：重置全部
  · 帮助：本说明

常见问题：
  Q: 点"开始"后数字不动？ A: 请确认已把"每秒生成条数"调到大于 0。
  Q: 导出的 CSV 用记事本打开正常、用电子表格打开乱码？
     A: 本工具用 UTF-8(带BOM) 保存，常见电子表格软件都能正确识别。
"""


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("980x680")
        root.minsize(860, 560)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TNotebook.Tab", padding=(14, 6))
        style.configure("Big.TLabel", font=("Microsoft YaHei", 13, "bold"))
        style.configure("Num.TLabel", font=("Consolas", 20, "bold"), foreground="#0f766e")

        # 数据状态
        self.dataset_name = "（尚未生成数据集）"
        self.fields = []
        self.rows = []
        self.cards = []          # 数据-信息-知识卡片
        self.traffic_rows = []
        self.exp_log = []        # 实验记录
        # 速度模拟状态
        self.sim_running = False
        self.sim_total = 0
        self.sim_seconds = 0
        self.sim_job = None

        self._build_menu()
        self._build_body()
        self._log("程序启动")
        self.set_status("欢迎使用数据与大数据实验室，请从标签页1开始体验。")

    # ---------- 界面 ----------
    def _build_menu(self):
        m = tk.Menu(self.root)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="导入 CSV…", command=self.import_csv)
        fm.add_command(label="导出当前数据集 CSV…", command=self.export_csv)
        fm.add_command(label="保存实验记录…", command=self.save_record)
        fm.add_separator()
        fm.add_command(label="退出", command=self.on_close)
        m.add_cascade(label="文件", menu=fm)
        om = tk.Menu(m, tearoff=0)
        om.add_command(label="重置全部", command=self.reset_all)
        m.add_cascade(label="操作", menu=om)
        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label="使用帮助", command=self.show_help)
        m.add_cascade(label="帮助", menu=hm)
        self.root.config(menu=m)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_body(self):
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self._build_tab_dataset()
        self._build_tab_speed()
        self._build_tab_cards()
        self._build_tab_traffic()
        self.status = tk.StringVar(value="就绪")
        bar = ttk.Label(self.root, textvariable=self.status, relief="sunken", anchor="w", padding=(8, 3))
        bar.pack(fill="x", side="bottom")

    def set_status(self, text):
        self.status.set(text)

    def _log(self, text):
        self.exp_log.append("[%s] %s" % (now_str(), text))

    # ===== 标签页1：数据集生成 =====
    def _build_tab_dataset(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text=" 1 数据集生成与类型统计 ")

        top = ttk.Frame(tab)
        top.pack(fill="x", padx=10, pady=8)
        ttk.Label(top, text="生成示例数据集：", style="Big.TLabel").pack(side="left")
        ttk.Button(top, text="生成气象数据集(24小时×天数)", command=self.gen_weather).pack(side="left", padx=4)
        ttk.Label(top, text="天数:").pack(side="left")
        self.days_var = tk.IntVar(value=3)
        ttk.Spinbox(top, from_=1, to=30, textvariable=self.days_var, width=4).pack(side="left")
        ttk.Button(top, text="生成骑行数据集", command=self.gen_bike).pack(side="left", padx=(14, 4))
        ttk.Label(top, text="条数:").pack(side="left")
        self.bike_var = tk.IntVar(value=200)
        ttk.Spinbox(top, from_=10, to=5000, increment=50, textvariable=self.bike_var, width=6).pack(side="left")

        mid = ttk.Frame(tab)
        mid.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        left = ttk.LabelFrame(mid, text="数据表（前 500 行）")
        left.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(left, show="headings", height=14)
        ys = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")

        right = ttk.LabelFrame(mid, text="数据体检卡（数据量与字段类型）")
        right.pack(side="left", fill="y", padx=(8, 0))
        self.info_text = tk.Text(right, width=38, height=18, font=("Microsoft YaHei", 10),
                                 state="disabled", bg="#f0fdfa")
        self.info_text.pack(fill="both", expand=True, padx=4, pady=4)

    def gen_weather(self):
        days = max(1, min(30, self.days_var.get()))
        rows = []
        base_day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        for d in range(days):
            day_low = random.uniform(2, 12)      # 呼应小七孔温差大的情境
            day_span = random.uniform(10, 20)
            for h in range(24):
                # 气温曲线：约 14 时最高、约 6 时（日出前后）最低
                phase = (h - 14) / 24 * 2 * 3.141592653589793
                temp = day_low + day_span * (0.5 + 0.5 * self._cos(phase)) + random.uniform(-0.8, 0.8)
                hum = max(20, min(99, 95 - (temp - day_low) * 2.4 + random.uniform(-5, 5)))
                light = 0 if h < 6 or h > 19 else max(0, int(60000 * self._cos((h - 13) / 8) + random.uniform(-4000, 4000)))
                wind = random.choice([1, 1, 2, 2, 2, 3, 3, 4])
                t = base_day + timedelta(days=d, hours=h)
                rows.append([t.strftime("%m-%d %H:00"), round(temp, 1), round(hum), light, wind])
        self.dataset_name = "模拟气象数据集（%d 天 × 24 小时）" % days
        self.fields = WEATHER_FIELDS
        self.rows = rows
        self._show_dataset()
        self._log("生成气象数据集 %d 条" % len(rows))
        self.set_status("已生成 %s，共 %d 条记录。观察：最高气温大多出现在 14 时前后。" % (self.dataset_name, len(rows)))

    @staticmethod
    def _cos(x):
        import math
        return math.cos(x)

    def gen_bike(self):
        n = max(10, min(5000, self.bike_var.get()))
        # 早晚高峰概率更高
        hour_weight = [1, 1, 1, 1, 2, 4, 10, 22, 30, 14, 8, 8, 10, 10, 8, 8, 12, 22, 28, 16, 10, 6, 4, 2]
        pool = []
        for h, w in enumerate(hour_weight):
            pool.extend([h] * w)
        rows = []
        for i in range(1, n + 1):
            h = random.choice(pool)
            t = "%02d:%02d" % (h, random.randint(0, 59))
            a, b = random.sample(STATIONS, 2)
            rows.append([i, t, a, b, random.randint(3, 45)])
        self.dataset_name = "模拟共享单车骑行数据集"
        self.fields = BIKE_FIELDS
        self.rows = rows
        self._show_dataset()
        self._log("生成骑行数据集 %d 条" % n)
        self.set_status("已生成 %s，共 %d 条。想一想：早晚哪个时段记录最多？" % (self.dataset_name, n))

    def _show_dataset(self):
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = self.fields
        for f in self.fields:
            self.tree.heading(f, text=f)
            self.tree.column(f, width=110, anchor="center")
        for r in self.rows[:500]:
            self.tree.insert("", "end", values=r)
        # 体检卡
        lines = ["数据集：%s" % self.dataset_name,
                 "记录条数：%d 条" % len(self.rows), ""]
        if self.rows:
            lines.append("字段类型统计：")
            for i, f in enumerate(self.fields):
                sample = [r[i] for r in self.rows[:200]]
                num_cnt = sum(1 for v in sample if self._is_num(v))
                tp = "数值型" if num_cnt >= len(sample) * 0.9 else "文本型"
                lines.append("  · %-10s → %s" % (f, tp))
            per = self._row_bytes()
            total = per * len(self.rows)
            lines += ["", "单条记录约 %d 字节" % per,
                      "整个数据集约 %s" % self._fmt_bytes(total), "",
                      "提示：单条数据承载的信息有限，",
                      "数据集足够大才能反映一般规律，",
                      "这正是小清要连续多天采集的原因。"]
        self.info_text.config(state="normal")
        self.info_text.delete("1.0", "end")
        self.info_text.insert("1.0", "\n".join(lines))
        self.info_text.config(state="disabled")

    @staticmethod
    def _is_num(v):
        try:
            float(v)
            return True
        except (TypeError, ValueError):
            return False

    def _row_bytes(self):
        if not self.rows:
            return 0
        sample = self.rows[:100]
        total = sum(len((",".join(str(x) for x in r)).encode("utf-8")) + 2 for r in sample)
        return max(1, total // len(sample))

    @staticmethod
    def _fmt_bytes(b):
        units = ["字节", "KB", "MB", "GB", "TB"]
        x = float(b)
        for u in units:
            if x < 1024 or u == units[-1]:
                return ("%.2f %s" % (x, u)) if u != "字节" else ("%d %s" % (int(x), u))
            x /= 1024.0
        return "%d 字节" % b

    # ===== 标签页2：速度模拟 + 存储估算 =====
    def _build_tab_speed(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text=" 2 产生速度与存储估算 ")

        f1 = ttk.LabelFrame(tab, text="数据产生速度模拟（体验大数据的高速性）")
        f1.pack(fill="x", padx=10, pady=8)
        row = ttk.Frame(f1)
        row.pack(fill="x", padx=8, pady=6)
        ttk.Label(row, text="每秒生成条数：").pack(side="left")
        self.rate_var = tk.IntVar(value=2000)
        sc = ttk.Scale(row, from_=0, to=50000, variable=self.rate_var,
                       command=lambda _v: self.rate_lbl.config(text="%d 条/秒" % self.rate_var.get()))
        sc.pack(side="left", fill="x", expand=True, padx=6)
        self.rate_lbl = ttk.Label(row, text="2000 条/秒", width=12)
        self.rate_lbl.pack(side="left")
        row2 = ttk.Frame(f1)
        row2.pack(fill="x", padx=8, pady=4)
        self.btn_sim = ttk.Button(row2, text="开始", command=self.sim_toggle)
        self.btn_sim.pack(side="left")
        ttk.Button(row2, text="归零", command=self.sim_reset).pack(side="left", padx=6)
        ttk.Label(row2, text="模拟对象：某城市共享单车骑行记录（每条约 60 字节）").pack(side="left", padx=10)
        row3 = ttk.Frame(f1)
        row3.pack(fill="x", padx=8, pady=(2, 8))
        ttk.Label(row3, text="累计：").pack(side="left")
        self.sim_cnt_lbl = ttk.Label(row3, text="0 条", style="Num.TLabel")
        self.sim_cnt_lbl.pack(side="left", padx=(0, 20))
        ttk.Label(row3, text="内存估算：").pack(side="left")
        self.sim_mem_lbl = ttk.Label(row3, text="0 字节", style="Num.TLabel")
        self.sim_mem_lbl.pack(side="left", padx=(0, 20))
        ttk.Label(row3, text="已运行：").pack(side="left")
        self.sim_sec_lbl = ttk.Label(row3, text="0 秒", style="Num.TLabel")
        self.sim_sec_lbl.pack(side="left")

        f2 = ttk.LabelFrame(tab, text="存储空间估算（体验大数据的巨量性）")
        f2.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        row4 = ttk.Frame(f2)
        row4.pack(fill="x", padx=8, pady=8)
        ttk.Label(row4, text="数据条数：").pack(side="left")
        self.est_n = tk.StringVar(value="1000000")
        ttk.Entry(row4, textvariable=self.est_n, width=14).pack(side="left")
        ttk.Label(row4, text="  单条字节数：").pack(side="left")
        self.est_b = tk.StringVar(value="60")
        ttk.Entry(row4, textvariable=self.est_b, width=8).pack(side="left")
        ttk.Button(row4, text="估算", command=self.estimate).pack(side="left", padx=10)
        self.est_out = tk.Text(f2, height=9, font=("Microsoft YaHei", 11), bg="#f0fdfa", state="disabled")
        self.est_out.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def sim_toggle(self):
        self.sim_running = not self.sim_running
        self.btn_sim.config(text="暂停" if self.sim_running else "继续")
        if self.sim_running and self.sim_job is None:
            self._sim_tick()
        if self.sim_running:
            self._log("速度模拟开始/继续，速率 %d 条/秒" % self.rate_var.get())

    def sim_reset(self):
        self.sim_running = False
        self.sim_total = 0
        self.sim_seconds = 0
        self.btn_sim.config(text="开始")
        self._sim_show()
        self._log("速度模拟归零")

    def _sim_tick(self):
        if self.sim_running:
            rate = max(0, int(self.rate_var.get()))
            self.sim_total += rate
            self.sim_seconds += 1
            self._sim_show()
        self.sim_job = self.root.after(1000, self._sim_tick)

    def _sim_show(self):
        self.sim_cnt_lbl.config(text="{:,} 条".format(self.sim_total))
        self.sim_mem_lbl.config(text=self._fmt_bytes(self.sim_total * 60))
        self.sim_sec_lbl.config(text="%d 秒" % self.sim_seconds)

    def estimate(self):
        try:
            n = int(float(self.est_n.get()))
            b = int(float(self.est_b.get()))
            if n <= 0 or b <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("输入有误", "条数和单条字节数都应是正整数，请检查后重试。")
            return
        total = n * b
        # 类比锚点：教材"10TB ≈ 66亿部《红楼梦》"；高清电影约 2GB/部
        hlm = total / (10 * 1024 ** 4) * 6.6e9
        movie = total / (2 * 1024 ** 3)
        lines = ["条数 {:,} × 单条 {} 字节".format(n, b),
                 "= 总量 %s" % self._fmt_bytes(total), "",
                 "直观类比：",
                 "  ≈ %s 部《红楼梦》（约 87 万汉字/部，按教材 10TB≈66 亿部换算）" % self._fmt_cnt(hlm),
                 "  ≈ %s 部高清电影（按 2GB/部）" % self._fmt_cnt(movie), "",
                 "教材提示：通常认为 10~100TB 是大数据的门槛；",
                 "TB、PB 已不足以衡量人类产生的数据，还有 EB、ZB 级别。"]
        self.est_out.config(state="normal")
        self.est_out.delete("1.0", "end")
        self.est_out.insert("1.0", "\n".join(lines))
        self.est_out.config(state="disabled")
        self._log("存储估算：%d 条 × %d 字节 = %s" % (n, b, self._fmt_bytes(total)))
        self.set_status("估算完成。试试把条数加几个 0，看看单位如何跃升。")

    @staticmethod
    def _fmt_cnt(x):
        if x >= 1e8:
            return "%.1f 亿" % (x / 1e8)
        if x >= 1e4:
            return "%.1f 万" % (x / 1e4)
        if x >= 1:
            return "%.1f" % x
        return "%.4f" % x

    # ===== 标签页3：卡片编辑器 =====
    def _build_tab_cards(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text=" 3 数据—信息—知识卡片 ")
        tip = ttk.Label(tab, text="围绕在线数字气象站情境，写一组卡片：原始数据 → 场景中的信息 → 归纳出的知识",
                        style="Big.TLabel")
        tip.pack(anchor="w", padx=10, pady=(10, 4))
        grid = ttk.Frame(tab)
        grid.pack(fill="x", padx=10)
        self.card_inputs = []
        for i, (name, ph) in enumerate([
                ("数据（原始记录）", "例：2025-10-03,14:00,26.5,62"),
                ("信息（场景含义）", "例：10月3日14时小七孔气温26.5℃"),
                ("知识（归纳规律）", "例：晴天最高气温多出现在14时前后")]):
            col = ttk.LabelFrame(grid, text=name)
            col.grid(row=0, column=i, sticky="nsew", padx=4)
            grid.columnconfigure(i, weight=1)
            t = tk.Text(col, height=4, width=28, font=("Microsoft YaHei", 10))
            t.pack(fill="both", expand=True, padx=4, pady=4)
            t.insert("1.0", "")
            self.card_inputs.append(t)
            ttk.Label(col, text=ph, foreground="#64748b").pack(anchor="w", padx=4, pady=(0, 4))
        btns = ttk.Frame(tab)
        btns.pack(fill="x", padx=10, pady=6)
        ttk.Button(btns, text="保存卡片", command=self.save_card).pack(side="left")
        ttk.Button(btns, text="删除选中卡片", command=self.del_card).pack(side="left", padx=6)
        lf = ttk.LabelFrame(tab, text="卡片列表")
        lf.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.card_tree = ttk.Treeview(lf, columns=("d", "i", "k"), show="headings", height=8)
        for c, t2, w in (("d", "数据", 240), ("i", "信息", 280), ("k", "知识", 300)):
            self.card_tree.heading(c, text=t2)
            self.card_tree.column(c, width=w)
        self.card_tree.pack(fill="both", expand=True, padx=4, pady=4)

    def save_card(self):
        vals = [t.get("1.0", "end").strip().replace("\n", " ") for t in self.card_inputs]
        if not all(vals):
            messagebox.showinfo("请填完整", "三栏都要填写：数据、信息、知识各写一条。\n"
                                "小提示：信息=数据+具体场景；知识=多条信息归纳出的规律。")
            return
        self.cards.append(vals)
        self.card_tree.insert("", "end", values=vals)
        for t in self.card_inputs:
            t.delete("1.0", "end")
        self._log("保存一组数据-信息-知识卡片")
        self.set_status("卡片已保存，共 %d 组。可在菜单“文件→保存实验记录”导出。" % len(self.cards))

    def del_card(self):
        sel = self.card_tree.selection()
        if not sel:
            self.set_status("请先在列表中选中要删除的卡片。")
            return
        for item in sel:
            idx = self.card_tree.index(item)
            if 0 <= idx < len(self.cards):
                self.cards.pop(idx)
            self.card_tree.delete(item)
        self.set_status("已删除选中卡片，剩余 %d 组。" % len(self.cards))

    # ===== 标签页4：交通数据 =====
    def _build_tab_traffic(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text=" 4 交通拥堵数据统计 ")
        top = ttk.Frame(tab)
        top.pack(fill="x", padx=10, pady=8)
        ttk.Button(top, text="生成交通数据(300条)", command=self.gen_traffic).pack(side="left")
        ttk.Button(top, text="统计各路段平均车速", command=self.stat_traffic).pack(side="left", padx=6)
        ttk.Label(top, text="（模拟海量车辆上报的车速记录 → 汇聚出每条路的拥堵情况）").pack(side="left", padx=8)
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        lf = ttk.LabelFrame(body, text="原始车速记录")
        lf.pack(side="left", fill="both", expand=True)
        self.tr_tree = ttk.Treeview(lf, columns=TRAFFIC_FIELDS, show="headings", height=14)
        for f in TRAFFIC_FIELDS:
            self.tr_tree.heading(f, text=f)
            self.tr_tree.column(f, width=120, anchor="center")
        ys = ttk.Scrollbar(lf, orient="vertical", command=self.tr_tree.yview)
        self.tr_tree.configure(yscrollcommand=ys.set)
        self.tr_tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        rf = ttk.LabelFrame(body, text="统计结果（信息在这里“浮现”）")
        rf.pack(side="left", fill="y", padx=(8, 0))
        self.tr_out = tk.Text(rf, width=40, height=18, font=("Microsoft YaHei", 10),
                              bg="#f0fdfa", state="disabled")
        self.tr_out.pack(fill="both", expand=True, padx=4, pady=4)

    def gen_traffic(self):
        self.traffic_rows = []
        base_speed = {r: random.uniform(15, 55) for r in ROADS}
        for _ in range(300):
            r = random.choice(ROADS)
            t = "%02d:%02d" % (random.randint(6, 21), random.randint(0, 59))
            v = max(3, round(base_speed[r] + random.uniform(-8, 8), 1))
            self.traffic_rows.append([r, t, v])
        self.tr_tree.delete(*self.tr_tree.get_children())
        for row in self.traffic_rows:
            self.tr_tree.insert("", "end", values=row)
        self._out_traffic("已生成 300 条车速记录。\n\n单看任何一条记录都没什么用，\n点击“统计各路段平均车速”，\n看看规律如何从海量记录中提炼出来。")
        self._log("生成交通车速记录 300 条")
        self.set_status("交通数据已生成，请点击“统计各路段平均车速”。")

    def stat_traffic(self):
        if not self.traffic_rows:
            self._out_traffic("请先点击“生成交通数据(300条)”。")
            return
        agg = {}
        for r, _t, v in self.traffic_rows:
            agg.setdefault(r, []).append(v)
        lines = ["各路段平均车速统计：", ""]
        for r in ROADS:
            vs = agg.get(r, [])
            if not vs:
                continue
            avg = sum(vs) / len(vs)
            level = "畅通" if avg >= 40 else ("缓行" if avg >= 25 else "拥堵")
            lines.append("%-6s %5.1f km/h（%d 条记录）→ %s" % (r, avg, len(vs), level))
        lines += ["", "判断标准：≥40 畅通 / 25~40 缓行 / <25 拥堵", "",
                  "这就是导航软件“红黄绿”路况的原理：",
                  "海量车辆位置与速度记录（数据）",
                  "→ 各路段实时车速（信息）",
                  "→ 高峰期绕开某某路更快（知识）"]
        self._out_traffic("\n".join(lines))
        self._log("完成交通数据统计")
        self.set_status("统计完成：数据经过汇聚计算才产生价值，这就是大数据的价值性。")

    def _out_traffic(self, text):
        self.tr_out.config(state="normal")
        self.tr_out.delete("1.0", "end")
        self.tr_out.insert("1.0", text)
        self.tr_out.config(state="disabled")

    # ---------- 文件操作 ----------
    def import_csv(self):
        path = filedialog.askopenfilename(title="导入 CSV", filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")])
        if not path:
            return
        for enc in ("utf-8-sig", "gbk"):
            try:
                with open(path, "r", encoding=enc, newline="") as f:
                    rows = list(csv.reader(f))
                break
            except UnicodeDecodeError:
                rows = None
        if not rows:
            messagebox.showerror("导入失败", "无法识别文件编码或文件为空（支持 UTF-8 / GBK）。")
            return
        self.dataset_name = "导入：" + path.split("/")[-1]
        self.fields = rows[0]
        self.rows = rows[1:]
        self._show_dataset()
        self.nb.select(0)
        self._log("导入 CSV：%s（%d 条）" % (path, len(self.rows)))
        self.set_status("已导入 %d 条记录（编码 %s）。" % (len(self.rows), enc))

    def export_csv(self):
        if not self.rows:
            messagebox.showinfo("暂无数据", "请先在标签页1生成或导入一个数据集。")
            return
        path = filedialog.asksaveasfilename(title="导出 CSV", defaultextension=".csv",
                                            initialfile="数据集导出.csv",
                                            filetypes=[("CSV 文件", "*.csv")])
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(self.fields)
            w.writerows(self.rows)
        self._log("导出 CSV：%s" % path)
        self.set_status("已导出 %d 条记录到 %s" % (len(self.rows), path))

    def save_record(self):
        path = filedialog.asksaveasfilename(title="保存实验记录", defaultextension=".json",
                                            initialfile="大数据实验记录.json",
                                            filetypes=[("JSON 文件", "*.json"), ("文本文件", "*.txt")])
        if not path:
            return
        record = {
            "工具": APP_TITLE,
            "保存时间": now_str(),
            "当前数据集": self.dataset_name,
            "数据集条数": len(self.rows),
            "速度模拟": {"累计条数": self.sim_total, "运行秒数": self.sim_seconds,
                         "内存估算": self._fmt_bytes(self.sim_total * 60)},
            "数据信息知识卡片": [{"数据": c[0], "信息": c[1], "知识": c[2]} for c in self.cards],
            "操作日志": self.exp_log,
        }
        if path.lower().endswith(".txt"):
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, indent=2))
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
        self.set_status("实验记录已保存到 %s" % path)

    def reset_all(self):
        if not messagebox.askyesno("重置全部", "将清空当前数据集、卡片、交通数据和模拟计数，确定吗？"):
            return
        self.dataset_name = "（尚未生成数据集）"
        self.fields, self.rows = [], []
        self.cards = []
        self.traffic_rows = []
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = []
        self.card_tree.delete(*self.card_tree.get_children())
        self.tr_tree.delete(*self.tr_tree.get_children())
        self.info_text.config(state="normal")
        self.info_text.delete("1.0", "end")
        self.info_text.config(state="disabled")
        self._out_traffic("")
        self.sim_reset()
        self._log("重置全部")
        self.set_status("已重置，可以重新开始实验。")

    def show_help(self):
        win = tk.Toplevel(self.root)
        win.title("使用帮助")
        win.geometry("640x560")
        t = tk.Text(win, font=("Microsoft YaHei", 10), wrap="word")
        t.pack(fill="both", expand=True, padx=8, pady=8)
        t.insert("1.0", HELP_TEXT)
        t.config(state="disabled")
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=(0, 8))

    def on_close(self):
        if self.sim_job is not None:
            try:
                self.root.after_cancel(self.sim_job)
            except tk.TclError:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
