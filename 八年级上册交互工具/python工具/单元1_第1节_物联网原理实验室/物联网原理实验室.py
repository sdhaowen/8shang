# -*- coding: utf-8 -*-
"""
物联网原理实验室（第1单元 第1节《从互联网到物联网》配套工具）
================================================================
功能简介：
  1. 模拟温度、湿度、光照三个虚拟传感器（手动滑块 + 自动随机漂移两种模式）；
  2. 三栏展示物联网数据流转：设备端 → 本地平台 → 控制端（消息带时间戳流动显示）；
  3. tkinter.Canvas 自绘三条实时曲线；
  4. 阈值设置与超限提醒（状态栏变色 + 日志记录）；
  5. 采集记录可导出为 CSV；支持 开始/暂停、重置、帮助。
运行方法：
  python3 物联网原理实验室.py
说明：
  仅使用 Python 标准库（tkinter / csv / random 等），不联网、不控制真实设备，
  采样间隔 0.5~5 秒可调，所有数据均为本机模拟数据。
"""

import csv
import random
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_TITLE = "物联网原理实验室 · 第1单元第1节《从互联网到物联网》"

SENSORS = [
    # (键名, 中文名, 单位, 最小值, 最大值, 初始值, 曲线颜色)
    ("temp", "温度", "℃", -10.0, 50.0, 25.0, "#e11d48"),
    ("humi", "湿度", "%", 0.0, 100.0, 55.0, "#0284c7"),
    ("light", "光照", "lx", 0.0, 1000.0, 400.0, "#d97706"),
]


class IoTLab:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("1180x760")
        root.minsize(980, 640)

        self.running = False          # 是否正在采集
        self.auto_mode = tk.BooleanVar(value=True)   # 自动漂移模式
        self.interval = tk.DoubleVar(value=1.0)      # 采样间隔（秒）
        self.after_id = None
        self.records = []             # [(时间字符串, 温度, 湿度, 光照, 状态)]
        self.history = {k: [] for k, *_ in SENSORS}  # 曲线数据
        self.max_points = 120

        self.values = {}              # 当前值变量
        self.thresholds = {}          # 阈值变量（上限）
        for key, _name, _unit, _mn, _mx, init, _c in SENSORS:
            self.values[key] = tk.DoubleVar(value=init)
        # 默认阈值：温度 35℃、湿度 80%、光照 800lx
        self.thresholds["temp"] = tk.DoubleVar(value=35.0)
        self.thresholds["humi"] = tk.DoubleVar(value=80.0)
        self.thresholds["light"] = tk.DoubleVar(value=800.0)

        self._build_ui()
        self._log_platform("本地物联网平台已就绪（127.0.0.1 进程内模拟，不连接真实网络）。")
        self._log_control("控制端就绪，等待平台推送数据……")
        self._draw_curves()

    # ---------------- 界面 ----------------
    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TLabelframe.Label", font=("Microsoft YaHei", 10, "bold"))
        style.configure("Title.TLabel", font=("Microsoft YaHei", 12, "bold"), foreground="#075985")

        top = ttk.Frame(self.root, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="物联网数据流转演示：设备端（感知）→ 本地平台（传输+处理）→ 控制端（应用）",
                  style="Title.TLabel").pack(side="left")

        # 操作区
        ops = ttk.Frame(self.root, padding=(10, 2))
        ops.pack(fill="x")
        self.btn_start = ttk.Button(ops, text="▶ 开始采集", command=self.toggle_run)
        self.btn_start.pack(side="left", padx=3)
        ttk.Button(ops, text="↺ 重置", command=self.reset).pack(side="left", padx=3)
        ttk.Button(ops, text="导出CSV", command=self.export_csv).pack(side="left", padx=3)
        ttk.Button(ops, text="帮助", command=self.show_help).pack(side="left", padx=3)
        ttk.Checkbutton(ops, text="自动随机漂移模式", variable=self.auto_mode).pack(side="left", padx=12)
        ttk.Label(ops, text="采样间隔(秒 0.5~5)：").pack(side="left")
        self.spin = ttk.Spinbox(ops, from_=0.5, to=5.0, increment=0.5,
                                textvariable=self.interval, width=5)
        self.spin.pack(side="left")

        # 三栏
        main = ttk.Frame(self.root, padding=(10, 4))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=2)
        main.columnconfigure(1, weight=3)
        main.columnconfigure(2, weight=3)
        main.rowconfigure(0, weight=3)
        main.rowconfigure(1, weight=2)

        # 左栏：设备端
        dev = ttk.Labelframe(main, text="① 设备端 · 虚拟传感器（感知）", padding=8)
        dev.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.value_labels = {}
        for key, name, unit, mn, mx, _init, color in SENSORS:
            f = ttk.Frame(dev)
            f.pack(fill="x", pady=4)
            ttk.Label(f, text=f"{name}（{unit}）", width=10).pack(side="left")
            lab = tk.Label(f, text="--", width=8, fg="white", bg=color,
                           font=("Consolas", 11, "bold"))
            lab.pack(side="right")
            self.value_labels[key] = lab
            s = ttk.Scale(dev, from_=mn, to=mx, variable=self.values[key],
                          command=lambda _v, k=key: self._on_slide(k))
            s.pack(fill="x")
        ttk.Separator(dev).pack(fill="x", pady=6)
        ttk.Label(dev, text="报警阈值（上限）设置：").pack(anchor="w")
        for key, name, unit, _mn, _mx, _init, _c in SENSORS:
            f = ttk.Frame(dev)
            f.pack(fill="x", pady=2)
            ttk.Label(f, text=f"{name}上限（{unit}）", width=12).pack(side="left")
            ttk.Entry(f, textvariable=self.thresholds[key], width=8).pack(side="left")

        # 中栏：本地平台
        plat = ttk.Labelframe(main, text="② 本地平台 · 消息流转与处理（传输+处理）", padding=6)
        plat.grid(row=0, column=1, sticky="nsew", padx=6)
        self.lst_platform = tk.Listbox(plat, font=("Consolas", 9))
        self.lst_platform.pack(fill="both", expand=True, side="left")
        sb1 = ttk.Scrollbar(plat, command=self.lst_platform.yview)
        sb1.pack(side="right", fill="y")
        self.lst_platform.config(yscrollcommand=sb1.set)

        # 右栏：控制端
        ctrl = ttk.Labelframe(main, text="③ 控制端 · 用户界面与告警（应用）", padding=6)
        ctrl.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        self.lst_control = tk.Listbox(ctrl, font=("Consolas", 9))
        self.lst_control.pack(fill="both", expand=True, side="left")
        sb2 = ttk.Scrollbar(ctrl, command=self.lst_control.yview)
        sb2.pack(side="right", fill="y")
        self.lst_control.config(yscrollcommand=sb2.set)

        # 下方：曲线
        curve = ttk.Labelframe(main, text="实时曲线（Canvas 自绘：红=温度 蓝=湿度 橙=光照）", padding=4)
        curve.grid(row=1, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        self.canvas = tk.Canvas(curve, bg="#0f172a", height=200, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._draw_curves())

        # 状态栏
        self.status = tk.Label(self.root, text="就绪：点击「开始采集」启动虚拟传感器。",
                               anchor="w", bg="#e0f2fe", fg="#075985",
                               font=("Microsoft YaHei", 10), padx=10, pady=4)
        self.status.pack(fill="x", side="bottom")

    # ---------------- 日志 ----------------
    @staticmethod
    def _ts():
        return time.strftime("%H:%M:%S")

    def _log_platform(self, msg):
        self.lst_platform.insert("end", f"[{self._ts()}] {msg}")
        self.lst_platform.see("end")
        if self.lst_platform.size() > 400:
            self.lst_platform.delete(0, 100)

    def _log_control(self, msg):
        self.lst_control.insert("end", f"[{self._ts()}] {msg}")
        self.lst_control.see("end")
        if self.lst_control.size() > 400:
            self.lst_control.delete(0, 100)

    # ---------------- 采集循环 ----------------
    def toggle_run(self):
        self.running = not self.running
        if self.running:
            self.btn_start.config(text="⏸ 暂停采集")
            self._set_status("采集中……设备端数据正在流向平台。", ok=True)
            self._log_platform("平台收到指令：开始订阅设备端数据。")
            self._tick()
        else:
            self.btn_start.config(text="▶ 开始采集")
            self._set_status("已暂停。", ok=True)
            if self.after_id:
                self.root.after_cancel(self.after_id)
                self.after_id = None

    def _on_slide(self, key):
        # 手动拖动滑块时即时刷新数值标签
        for k, name, unit, _mn, _mx, _i, _c in SENSORS:
            if k == key:
                self.value_labels[k].config(text=f"{self.values[k].get():.1f}")

    def _tick(self):
        if not self.running:
            return
        # 自动模式：随机漂移
        if self.auto_mode.get():
            for key, _n, _u, mn, mx, _i, _c in SENSORS:
                cur = self.values[key].get()
                span = (mx - mn) * 0.03
                cur = max(mn, min(mx, cur + random.uniform(-span, span)))
                self.values[key].set(cur)
        # 采样
        row_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        vals = {k: self.values[k].get() for k, *_ in SENSORS}
        alarms = []
        for key, name, unit, _mn, _mx, _i, _c in SENSORS:
            self.value_labels[key].config(text=f"{vals[key]:.1f}")
            self.history[key].append(vals[key])
            if len(self.history[key]) > self.max_points:
                self.history[key].pop(0)
            try:
                th = float(self.thresholds[key].get())
            except (tk.TclError, ValueError):
                th = float("inf")
            if vals[key] > th:
                alarms.append(f"{name}={vals[key]:.1f}{unit} 超过阈值 {th:g}{unit}")
        status = "报警" if alarms else "正常"
        self.records.append((row_ts, f"{vals['temp']:.1f}", f"{vals['humi']:.1f}",
                             f"{vals['light']:.1f}", status))
        # 三栏消息流
        self._log_platform(
            f"设备端→平台 上报: 温度{vals['temp']:.1f}℃ 湿度{vals['humi']:.1f}% 光照{vals['light']:.0f}lx")
        if alarms:
            self._log_platform("平台分析：数值超限！向控制端推送告警。")
            for a in alarms:
                self._log_control("⚠ 告警: " + a)
            self._set_status("⚠ 超限报警：" + "；".join(alarms), ok=False)
        else:
            self._log_control(
                f"平台→控制端 刷新显示: {vals['temp']:.1f}℃ / {vals['humi']:.1f}% / {vals['light']:.0f}lx（正常）")
            self._set_status(f"采集中……已记录 {len(self.records)} 条数据。", ok=True)
        self._draw_curves()
        # 下一次采样
        try:
            iv = float(self.interval.get())
        except (tk.TclError, ValueError):
            iv = 1.0
        iv = max(0.5, min(5.0, iv))
        self.after_id = self.root.after(int(iv * 1000), self._tick)

    def _set_status(self, text, ok=True):
        self.status.config(text=text,
                           bg="#e0f2fe" if ok else "#fee2e2",
                           fg="#075985" if ok else "#991b1b")

    # ---------------- 曲线 ----------------
    def _draw_curves(self):
        c = self.canvas
        c.delete("all")
        w = max(c.winfo_width(), 50)
        h = max(c.winfo_height(), 50)
        pad = 26
        # 网格
        for i in range(5):
            y = pad + (h - 2 * pad) * i / 4
            c.create_line(pad, y, w - 8, y, fill="#1e293b")
        c.create_text(w // 2, 12, text="最近 %d 个采样点" % self.max_points,
                      fill="#64748b", font=("Microsoft YaHei", 9))
        for key, name, unit, mn, mx, _i, color in SENSORS:
            data = self.history[key]
            if len(data) < 2:
                continue
            pts = []
            n = len(data)
            for i, v in enumerate(data):
                x = pad + (w - pad - 8) * i / (self.max_points - 1)
                ratio = (v - mn) / (mx - mn) if mx > mn else 0
                y = h - pad - (h - 2 * pad) * ratio
                pts.extend([x, y])
            c.create_line(*pts, fill=color, width=2, smooth=True)
            c.create_text(pad + 6, pts[-1] - 10 if pts[-1] > 30 else pts[-1] + 10,
                          text="", fill=color)
        # 图例
        lx = pad
        for key, name, unit, _mn, _mx, _i, color in SENSORS:
            c.create_rectangle(lx, h - 16, lx + 10, h - 6, fill=color, outline="")
            c.create_text(lx + 14, h - 11, text=name, anchor="w",
                          fill="#cbd5e1", font=("Microsoft YaHei", 9))
            lx += 70

    # ---------------- 导出 / 重置 / 帮助 ----------------
    def export_csv(self):
        if not self.records:
            messagebox.showinfo("导出CSV", "还没有采集数据。请先点击「开始采集」。")
            return
        path = filedialog.asksaveasfilename(
            title="导出采集记录", defaultextension=".csv",
            initialfile="物联网采集记录.csv",
            filetypes=[("CSV 文件", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f)
            wr.writerow(["时间", "温度(℃)", "湿度(%)", "光照(lx)", "状态"])
            wr.writerows(self.records)
        self._set_status(f"已导出 {len(self.records)} 条记录到：{path}", ok=True)
        messagebox.showinfo("导出CSV", f"成功导出 {len(self.records)} 条记录。")

    def reset(self):
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.running = False
        self.btn_start.config(text="▶ 开始采集")
        self.records.clear()
        for k in self.history:
            self.history[k].clear()
        for key, _n, _u, _mn, _mx, init, _c in SENSORS:
            self.values[key].set(init)
            self.value_labels[key].config(text="--")
        self.lst_platform.delete(0, "end")
        self.lst_control.delete(0, "end")
        self._log_platform("平台已重置。")
        self._log_control("控制端已重置。")
        self._draw_curves()
        self._set_status("已重置：数据与日志已清空。", ok=True)

    def show_help(self):
        win = tk.Toplevel(self.root)
        win.title("帮助 · 物联网原理实验室")
        win.geometry("560x420")
        txt = tk.Text(win, wrap="char", font=("Microsoft YaHei", 10), padx=10, pady=8)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0",
                   "【实验目的】\n"
                   "通过虚拟传感器体验物联网“感知→传输→处理→应用”的数据流转过程。\n\n"
                   "【操作步骤】\n"
                   "1. 点击「开始采集」，观察三栏消息如何从设备端流向控制端；\n"
                   "2. 勾选/取消「自动随机漂移模式」：取消后可手动拖动滑块改变传感器读数；\n"
                   "3. 修改采样间隔（0.5~5 秒），观察数据频率变化；\n"
                   "4. 修改报警阈值（如把温度上限调低到 20℃），制造一次“超限报警”，\n"
                   "   注意状态栏变红、控制端出现 ⚠ 告警消息；\n"
                   "5. 点击「导出CSV」，把采集记录保存下来，用表格软件打开分析。\n\n"
                   "【对应教材知识】\n"
                   "· 感知：传感器采集温度、湿度、光照等数据（教材：多维度感知）；\n"
                   "· 传输：设备端把数据上报到平台（真实系统经 Wi-Fi/4G/5G 传输）；\n"
                   "· 处理：平台判断数据是否超过阈值并做出决策；\n"
                   "· 应用：控制端呈现结果、发出告警，服务于用户需求。\n\n"
                   "【注意】本工具全部数据为本机模拟，不联网、不控制任何真实设备。")
        txt.config(state="disabled")
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=6)

    def on_close(self):
        if self.after_id:
            self.root.after_cancel(self.after_id)
        self.root.destroy()


def main():
    root = tk.Tk()
    app = IoTLab(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
