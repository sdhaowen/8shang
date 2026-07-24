# -*- coding: utf-8 -*-
"""
传感器数据采集实验室（虚拟）
配套课时：清华大学出版社《信息科技》八年级上册 第1单元 第3节《物联网的感知》
功能：
  1. 四通道虚拟传感器数据发生器：温度、空气湿度、光照、土壤湿度；
     每通道可选 手动滑块 / 自动漂移 / 正弦波动 三种数据模式。
  2. 采样间隔 0.2~10 秒可调，用 after() 驱动，不阻塞界面。
  3. tkinter.Canvas 实时多通道曲线（不同颜色 + 图例）。
  4. 每通道可设阈值上下限，超限时数值变红并写入报警日志。
  5. ttk.Treeview 数据表格显示最近采样记录。
  6. 导出 CSV、清空/重置、帮助窗口。
运行方法：python3 传感器数据采集实验室.py
说明：全部使用 Python 标准库（tkinter），完全离线，数据均为虚拟仿真，
      不连接、不控制任何真实设备。
"""

import csv
import math
import random
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_TITLE = "传感器数据采集实验室（虚拟） · 八年级上册 第1单元 第3节 物联网的感知"

# 通道定义：键、显示名、单位、量程、曲线颜色、初始值
CHANNELS = [
    {"key": "temp",  "name": "温度",     "unit": "℃",  "lo": 0.0,  "hi": 50.0,  "color": "#e74c3c", "init": 25.0},
    {"key": "humi",  "name": "空气湿度", "unit": "%RH", "lo": 0.0,  "hi": 100.0, "color": "#3498db", "init": 55.0},
    {"key": "light", "name": "光照",     "unit": "lx",  "lo": 0.0,  "hi": 1000.0, "color": "#f39c12", "init": 500.0},
    {"key": "soil",  "name": "土壤湿度", "unit": "%",   "lo": 0.0,  "hi": 100.0, "color": "#27ae60", "init": 60.0},
]
MODES = ("手动滑块", "自动漂移", "正弦波动")
MAX_POINTS = 240          # 曲线保留点数
MAX_TABLE_ROWS = 200      # 表格保留行数

HELP_TEXT = """【工具用途】
本工具模拟物联网智能终端从多种传感器"采样"数据的过程，
帮助理解：采样间隔、模拟量的连续变化、阈值报警等概念。
所有数据均为程序生成的虚拟数据，不连接真实硬件。

【操作步骤】
1. 在左侧为每个通道选择数据模式：
   · 手动滑块：由你拖动滑块决定当前读数（好比亲手转动旋钮传感器）；
   · 自动漂移：数值缓慢随机游走（模拟自然环境缓变）；
   · 正弦波动：数值按正弦规律起伏（模拟昼夜周期变化）。
2. 设置采样间隔（0.2~10 秒），点击【开始采集】。
3. 观察右侧实时曲线与下方数据表格。
4. 在"阈值"处为通道设置下限/上限，超限时该通道读数变红，
   并写入报警日志（模拟"缺水提醒""光照不足提醒"等功能）。
5. 点击【导出CSV】把采集记录保存下来，可用表格软件打开分析。

【常见问题】
· 曲线不动：请先点击【开始采集】。
· 报警不触发：检查阈值是否留有合理区间（下限应小于上限）。
· 数值单位：温度℃、空气湿度%RH、光照lx、土壤湿度%（教材指出
  土壤缺水时土壤湿度传感器输出值将减少）。
"""


class VirtualSensor:
    """一个通道的虚拟传感器数据发生器（可独立于 GUI 测试）"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.value = cfg["init"]
        self.manual = cfg["init"]
        self.mode = "自动漂移"
        self.t0 = time.time()

    def read(self):
        lo, hi = self.cfg["lo"], self.cfg["hi"]
        span = hi - lo
        if self.mode == "手动滑块":
            self.value = self.manual
        elif self.mode == "自动漂移":
            self.value += random.uniform(-0.02, 0.02) * span
        else:  # 正弦波动
            phase = (time.time() - self.t0) / 30.0 * 2 * math.pi
            center = lo + span * 0.5
            self.value = center + span * 0.35 * math.sin(phase) \
                + random.uniform(-0.01, 0.01) * span
        self.value = max(lo, min(hi, self.value))
        return round(self.value, 1)


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("1180x720")
        root.minsize(980, 620)

        self.sensors = {c["key"]: VirtualSensor(c) for c in CHANNELS}
        self.history = {c["key"]: [] for c in CHANNELS}   # [(t, v), ...]
        self.records = []        # 采样记录（用于导出）
        self.alarms = []         # 报警日志（用于导出）
        self.running = False
        self.after_id = None
        self.sample_count = 0

        self._build_style()
        self._build_ui()
        self._draw_chart()
        self._set_status("就绪：设置好模式与采样间隔后，点击【开始采集】。")

    # ---------------- 界面 ----------------
    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TLabelframe.Label", font=("Microsoft YaHei", 10, "bold"))
        style.configure("Alarm.TLabel", foreground="#c0392b")

    def _build_ui(self):
        # 顶部操作条
        top = ttk.Frame(self.root, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="采样间隔(秒)：").pack(side="left")
        self.var_interval = tk.DoubleVar(value=1.0)
        sp = ttk.Spinbox(top, from_=0.2, to=10.0, increment=0.2,
                         textvariable=self.var_interval, width=6)
        sp.pack(side="left", padx=(0, 12))
        self.btn_start = ttk.Button(top, text="▶ 开始采集", command=self.start)
        self.btn_start.pack(side="left", padx=3)
        self.btn_stop = ttk.Button(top, text="⏸ 停止", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=3)
        ttk.Button(top, text="导出CSV", command=self.export_csv).pack(side="left", padx=3)
        ttk.Button(top, text="导出报警日志", command=self.export_alarms).pack(side="left", padx=3)
        ttk.Button(top, text="清空数据", command=self.clear_data).pack(side="left", padx=3)
        ttk.Button(top, text="全部重置", command=self.reset_all).pack(side="left", padx=3)
        ttk.Button(top, text="帮助", command=self.show_help).pack(side="right", padx=3)

        body = ttk.Frame(self.root, padding=(10, 0, 10, 4))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=3)
        body.rowconfigure(1, weight=2)

        # 左：通道控制（输入区）
        left = ttk.LabelFrame(body, text="通道控制（虚拟传感器输入区）", padding=8)
        left.grid(row=0, column=0, rowspan=2, sticky="nsw", padx=(0, 8), pady=4)
        self.ch_widgets = {}
        for cfg in CHANNELS:
            self._build_channel_box(left, cfg)

        # 右上：曲线（结果区1）
        chart_box = ttk.LabelFrame(body, text="实时曲线（多通道示波器）", padding=6)
        chart_box.grid(row=0, column=1, sticky="nsew", pady=4)
        self.canvas = tk.Canvas(chart_box, bg="#1c1f26", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw_chart())

        # 右下：表格 + 报警日志（结果区2）
        bottom = ttk.Frame(body)
        bottom.grid(row=1, column=1, sticky="nsew", pady=4)
        bottom.columnconfigure(0, weight=3)
        bottom.columnconfigure(1, weight=2)
        bottom.rowconfigure(0, weight=1)

        table_box = ttk.LabelFrame(bottom, text="最近采样记录", padding=4)
        table_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        cols = ["序号", "时间"] + ["%s(%s)" % (c["name"], c["unit"]) for c in CHANNELS]
        self.tree = ttk.Treeview(table_box, columns=cols, show="headings", height=7)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=92, anchor="center")
        self.tree.column("序号", width=52)
        self.tree.column("时间", width=90)
        vsb = ttk.Scrollbar(table_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        alarm_box = ttk.LabelFrame(bottom, text="报警日志（超限记录）", padding=4)
        alarm_box.grid(row=0, column=1, sticky="nsew")
        self.txt_alarm = tk.Text(alarm_box, height=7, width=34, state="disabled",
                                 bg="#fff8f0", fg="#c0392b",
                                 font=("Microsoft YaHei", 9))
        avsb = ttk.Scrollbar(alarm_box, orient="vertical", command=self.txt_alarm.yview)
        self.txt_alarm.configure(yscrollcommand=avsb.set)
        self.txt_alarm.pack(side="left", fill="both", expand=True)
        avsb.pack(side="right", fill="y")

        # 状态栏
        self.var_status = tk.StringVar()
        bar = ttk.Label(self.root, textvariable=self.var_status, relief="sunken",
                        anchor="w", padding=(8, 3))
        bar.pack(fill="x", side="bottom")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_channel_box(self, parent, cfg):
        key = cfg["key"]
        box = ttk.LabelFrame(parent, text="%s（%s）" % (cfg["name"], cfg["unit"]), padding=6)
        box.pack(fill="x", pady=3)

        row1 = ttk.Frame(box)
        row1.pack(fill="x")
        ttk.Label(row1, text="模式：").pack(side="left")
        var_mode = tk.StringVar(value="自动漂移")
        cmb = ttk.Combobox(row1, textvariable=var_mode, values=MODES,
                           width=8, state="readonly")
        cmb.pack(side="left")
        lbl_val = tk.Label(row1, text="--", width=9, font=("Consolas", 11, "bold"),
                           fg=cfg["color"])
        lbl_val.pack(side="right")

        var_manual = tk.DoubleVar(value=cfg["init"])
        scale = ttk.Scale(box, from_=cfg["lo"], to=cfg["hi"], variable=var_manual)
        scale.pack(fill="x", pady=(4, 2))

        row2 = ttk.Frame(box)
        row2.pack(fill="x")
        ttk.Label(row2, text="阈值 下限").pack(side="left")
        var_lo = tk.StringVar(value="")
        ttk.Entry(row2, textvariable=var_lo, width=6).pack(side="left", padx=2)
        ttk.Label(row2, text="上限").pack(side="left")
        var_hi = tk.StringVar(value="")
        ttk.Entry(row2, textvariable=var_hi, width=6).pack(side="left", padx=2)
        ttk.Label(row2, text="(留空=不报警)", foreground="#888").pack(side="left", padx=2)

        def on_mode(_e=None):
            self.sensors[key].mode = var_mode.get()
            self._set_status("通道[%s] 切换为 %s 模式。" % (cfg["name"], var_mode.get()))
        cmb.bind("<<ComboboxSelected>>", on_mode)

        def on_manual(_v=None):
            self.sensors[key].manual = var_manual.get()
        scale.configure(command=on_manual)

        self.ch_widgets[key] = {
            "mode": var_mode, "manual": var_manual, "label": lbl_val,
            "lo": var_lo, "hi": var_hi, "cfg": cfg,
        }

    # ---------------- 采集逻辑 ----------------
    def start(self):
        if self.running:
            return
        try:
            iv = float(self.var_interval.get())
        except (tk.TclError, ValueError):
            messagebox.showwarning("提示", "采样间隔请输入 0.2~10 之间的数字。")
            return
        if not (0.2 <= iv <= 10.0):
            messagebox.showwarning("提示", "采样间隔必须在 0.2~10 秒之间。")
            return
        self.running = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._set_status("采集中… 间隔 %.1f 秒。" % iv)
        self._sample_loop()

    def stop(self):
        self.running = False
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self._set_status("已停止采集。共 %d 条记录，%d 条报警。"
                         % (len(self.records), len(self.alarms)))

    def _sample_loop(self):
        if not self.running:
            return
        self._do_sample()
        try:
            iv = max(0.2, min(10.0, float(self.var_interval.get())))
        except (tk.TclError, ValueError):
            iv = 1.0
        self.after_id = self.root.after(int(iv * 1000), self._sample_loop)

    def _do_sample(self):
        self.sample_count += 1
        now = time.time()
        ts = time.strftime("%H:%M:%S", time.localtime(now))
        row = {"序号": self.sample_count, "时间": ts}
        for cfg in CHANNELS:
            key = cfg["key"]
            v = self.sensors[key].read()
            row[key] = v
            self.history[key].append((now, v))
            if len(self.history[key]) > MAX_POINTS:
                self.history[key].pop(0)
            self._check_alarm(cfg, v, ts)
        self.records.append(row)
        self._update_value_labels(row)
        self._append_table_row(row)
        self._draw_chart()

    def _check_alarm(self, cfg, v, ts):
        w = self.ch_widgets[cfg["key"]]
        alarm = None
        try:
            lo_s = w["lo"].get().strip()
            if lo_s and v < float(lo_s):
                alarm = "低于下限 %s" % lo_s
        except ValueError:
            pass
        try:
            hi_s = w["hi"].get().strip()
            if alarm is None and hi_s and v > float(hi_s):
                alarm = "高于上限 %s" % hi_s
        except ValueError:
            pass
        w["alarm"] = alarm is not None
        if alarm:
            msg = "[%s] %s=%.1f%s %s" % (ts, cfg["name"], v, cfg["unit"], alarm)
            self.alarms.append({"时间": ts, "通道": cfg["name"],
                                "数值": v, "说明": alarm})
            self.txt_alarm.configure(state="normal")
            self.txt_alarm.insert("end", msg + "\n")
            self.txt_alarm.see("end")
            self.txt_alarm.configure(state="disabled")

    def _update_value_labels(self, row):
        for cfg in CHANNELS:
            w = self.ch_widgets[cfg["key"]]
            v = row[cfg["key"]]
            w["label"].configure(
                text="%.1f%s" % (v, cfg["unit"]),
                fg="#c0392b" if w.get("alarm") else cfg["color"])

    def _append_table_row(self, row):
        vals = [row["序号"], row["时间"]] + ["%.1f" % row[c["key"]] for c in CHANNELS]
        self.tree.insert("", 0, values=vals)
        kids = self.tree.get_children()
        if len(kids) > MAX_TABLE_ROWS:
            self.tree.delete(kids[-1])

    # ---------------- 曲线 ----------------
    def _draw_chart(self):
        cv = self.canvas
        cv.delete("all")
        w = cv.winfo_width() or 640
        h = cv.winfo_height() or 300
        pad_l, pad_r, pad_t, pad_b = 46, 12, 26, 22
        pw, ph = w - pad_l - pad_r, h - pad_t - pad_b
        if pw < 60 or ph < 40:
            return
        # 网格
        for i in range(5):
            y = pad_t + ph * i / 4
            cv.create_line(pad_l, y, w - pad_r, y, fill="#33384a")
            cv.create_text(pad_l - 6, y, text="%d%%" % (100 - i * 25),
                           anchor="e", fill="#7f8aa3", font=("Consolas", 8))
        cv.create_text(pad_l, 12, anchor="w", fill="#aab4cc",
                       text="纵轴为各通道量程百分比；横轴为最近 %d 个采样点" % MAX_POINTS,
                       font=("Microsoft YaHei", 8))
        # 图例
        lx = pad_l + 4
        for cfg in CHANNELS:
            cv.create_rectangle(lx, h - 16, lx + 10, h - 8,
                                fill=cfg["color"], outline="")
            cv.create_text(lx + 14, h - 12, anchor="w", fill="#d7dcea",
                           text=cfg["name"], font=("Microsoft YaHei", 8))
            lx += 14 + len(cfg["name"]) * 12 + 18
        # 曲线
        for cfg in CHANNELS:
            pts = self.history[cfg["key"]]
            if len(pts) < 2:
                continue
            lo, hi = cfg["lo"], cfg["hi"]
            coords = []
            n = len(pts)
            for i, (_t, v) in enumerate(pts):
                x = pad_l + pw * i / (MAX_POINTS - 1)
                frac = (v - lo) / (hi - lo)
                y = pad_t + ph * (1 - frac)
                coords.extend([x, y])
            cv.create_line(*coords, fill=cfg["color"], width=2, smooth=False)

    # ---------------- 导出 / 清空 / 帮助 ----------------
    def export_csv(self):
        if not self.records:
            messagebox.showinfo("提示", "还没有采集数据，请先点击【开始采集】。")
            return
        path = filedialog.asksaveasfilename(
            title="导出采样记录", defaultextension=".csv",
            initialfile="传感器采样记录.csv",
            filetypes=[("CSV 文件", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f)
            wr.writerow(["序号", "时间"] + ["%s(%s)" % (c["name"], c["unit"]) for c in CHANNELS])
            for r in self.records:
                wr.writerow([r["序号"], r["时间"]] + [r[c["key"]] for c in CHANNELS])
        self._set_status("已导出 %d 条采样记录到 %s" % (len(self.records), path))
        messagebox.showinfo("导出成功", "已导出 %d 条采样记录。" % len(self.records))

    def export_alarms(self):
        if not self.alarms:
            messagebox.showinfo("提示", "报警日志为空。可先设置阈值并采集触发报警。")
            return
        path = filedialog.asksaveasfilename(
            title="导出报警日志", defaultextension=".csv",
            initialfile="传感器报警日志.csv",
            filetypes=[("CSV 文件", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f)
            wr.writerow(["时间", "通道", "数值", "说明"])
            for a in self.alarms:
                wr.writerow([a["时间"], a["通道"], a["数值"], a["说明"]])
        self._set_status("已导出 %d 条报警日志到 %s" % (len(self.alarms), path))

    def clear_data(self):
        if not messagebox.askyesno("确认", "确定清空所有采样数据与报警日志吗？"):
            return
        self.records.clear()
        self.alarms.clear()
        self.sample_count = 0
        for k in self.history:
            self.history[k].clear()
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.txt_alarm.configure(state="normal")
        self.txt_alarm.delete("1.0", "end")
        self.txt_alarm.configure(state="disabled")
        self._draw_chart()
        self._set_status("数据已清空。")

    def reset_all(self):
        self.stop()
        self.clear_data()
        self.var_interval.set(1.0)
        for cfg in CHANNELS:
            w = self.ch_widgets[cfg["key"]]
            w["mode"].set("自动漂移")
            w["manual"].set(cfg["init"])
            w["lo"].set("")
            w["hi"].set("")
            w["label"].configure(text="--", fg=cfg["color"])
            self.sensors[cfg["key"]] = VirtualSensor(cfg)
        self._set_status("已恢复默认设置。")

    def show_help(self):
        win = tk.Toplevel(self.root)
        win.title("帮助 · 传感器数据采集实验室")
        win.geometry("560x520")
        win.transient(self.root)
        txt = tk.Text(win, wrap="word", font=("Microsoft YaHei", 10),
                      padx=12, pady=10)
        txt.insert("1.0", HELP_TEXT)
        txt.configure(state="disabled")
        vsb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=vsb.set)
        txt.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    def _set_status(self, s):
        self.var_status.set(" " + s)

    def on_close(self):
        self.running = False
        if self.after_id:
            try:
                self.root.after_cancel(self.after_id)
            except tk.TclError:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
