# -*- coding: utf-8 -*-
"""
课时：清华大学出版社《信息科技》八年级上册 第1单元 第5节《物联网的控制》
工具：虚拟执行器控制台（Tkinter 版）
功能：
  1. Canvas 虚拟设备面板：LED（可变色）、蜂鸣器（闪烁+可选发声）、继电器（触点动画）、
     舵机（摇臂角度）、风扇（旋转动画）、水泵（水滴动画）
  2. 虚拟传感器滑块：温度 / 土壤湿度 / 光照
  3. 控制规则编辑器（Treeview）：传感器、比较符、阈值、执行器、动作；可添加/删除/启用停用
  4. 手动 / 自动模式切换；自动模式下传感器变化触发规则并记录日志
  5. 控制序列播放：按时间顺序执行一串动作，可播放/暂停/重置
  6. 导出日志与规则（JSON / CSV）、导入规则（JSON）、帮助窗口
运行方法：python3 虚拟执行器控制台.py （仅用 Python 标准库，无需安装第三方库）
说明：全部设备为虚拟模拟，不连接真实硬件；蜂鸣器在 Windows 上可用 winsound 真实发声，
      其他系统自动降级为视觉闪烁提示。
"""

import csv
import json
import math
import sys
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import winsound  # 仅 Windows 可用
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

SENSORS = ["温度", "土壤湿度", "光照"]
SENSOR_UNIT = {"温度": "℃", "土壤湿度": "%", "光照": "lx"}
OPS = [">", "<", ">=", "<="]
ACTUATORS = ["LED补光灯", "风扇", "水泵", "蜂鸣器", "继电器"]
ACTIONS = ["开启", "关闭"]

DEMO_SEQUENCE = [
    (0.5, "LED补光灯", "开启"),
    (1.0, "舵机", "90"),
    (1.0, "继电器", "开启"),
    (1.0, "风扇", "开启"),
    (1.5, "水泵", "开启"),
    (1.5, "蜂鸣器", "开启"),
    (1.0, "蜂鸣器", "关闭"),
    (0.8, "水泵", "关闭"),
    (0.8, "风扇", "关闭"),
    (0.8, "继电器", "关闭"),
    (0.8, "舵机", "0"),
    (0.8, "LED补光灯", "关闭"),
]

HELP_TEXT = """【虚拟执行器控制台 · 使用帮助】

一、认识界面
  左侧：虚拟传感器滑块（温度/土壤湿度/光照）+ 模式切换 + 控制序列播放。
  中间：Canvas 虚拟设备面板，6 台执行器的状态实时可见。
  右侧：控制规则编辑器与运行日志。

二、手动模式
  点击设备下方的开关按钮直接控制执行器；
  拖动"舵机角度"滑块让摇臂转到 0~180°；
  用 R/G/B 三个滑块给 LED 调色（对应教材 RGB 混色原理）。

三、自动模式
  1. 在右侧编辑器中添加规则，例如：当 温度 > 30 时 开启 风扇；
  2. 切换到自动模式；
  3. 拖动左侧传感器滑块，观察执行器自动响应，
     日志会记录触发时间与原因。
  注意：规则方向要写对！风扇用于降温，应在温度"高于"阈值时开启。

四、控制序列
  点击"播放演示序列"，程序按时间顺序执行一串动作（像一段小节目），
  可随时暂停、继续、重置。

五、导入导出
  菜单"文件"中可导出规则/日志为 JSON 或 CSV，也可导入规则 JSON。

六、常见问题
  Q: 蜂鸣器为什么不响？
  A: 只有 Windows 系统能用 winsound 真实发声，其他系统以图标闪烁代替。
  Q: 自动模式下点设备按钮没反应？
  A: 自动模式下执行器由规则接管，请切回手动模式。
"""


class Console:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("虚拟执行器控制台 —— 八年级上册 第1单元 第5节《物联网的控制》")
        root.geometry("1180x720")
        root.minsize(1020, 640)

        self.auto_mode = tk.BooleanVar(value=False)
        self.mute = tk.BooleanVar(value=not HAS_WINSOUND)
        # 执行器状态
        self.state = {a: False for a in ACTUATORS}
        self.servo_angle = tk.IntVar(value=0)
        self.led_rgb = [tk.IntVar(value=244), tk.IntVar(value=63), tk.IntVar(value=94)]
        self.fan_phase = 0.0
        self.buzz_blink = False
        self.drop_phase = 0.0
        self.rules = []      # dict: sensor, op, th, actuator, action, enabled
        self.logs = []       # (time_str, msg)
        # 序列播放
        self.seq_steps = list(DEMO_SEQUENCE)
        self.seq_index = 0
        self.seq_running = False
        self.seq_after = None
        self._closing = False

        self._build_menu()
        self._build_layout()
        self._draw_static()
        self.log("程序启动。当前为手动模式，先点点各设备的开关试试。")
        self._tick()

    # ---------------- 界面构建 ----------------
    def _build_menu(self):
        m = tk.Menu(self.root)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="导出规则 JSON", command=lambda: self.export_rules("json"))
        fm.add_command(label="导出规则 CSV", command=lambda: self.export_rules("csv"))
        fm.add_command(label="导入规则 JSON", command=self.import_rules)
        fm.add_separator()
        fm.add_command(label="导出日志 JSON", command=lambda: self.export_logs("json"))
        fm.add_command(label="导出日志 CSV", command=lambda: self.export_logs("csv"))
        fm.add_separator()
        fm.add_command(label="退出", command=self.on_close)
        m.add_cascade(label="文件", menu=fm)
        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label="使用帮助", command=self.show_help)
        m.add_cascade(label="帮助", menu=hm)
        self.root.config(menu=m)

    def _build_layout(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TLabelframe.Label", font=("", 10, "bold"))

        main = ttk.Frame(self.root, padding=6)
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=3)
        main.columnconfigure(2, weight=2)
        main.rowconfigure(0, weight=1)

        # ---- 左侧：传感器 + 模式 + 序列 ----
        left = ttk.Frame(main)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 6))

        sf = ttk.Labelframe(left, text="虚拟传感器（输入区）", padding=8)
        sf.pack(fill="x")
        self.sensor_vars = {}
        ranges = {"温度": (0, 50, 25), "土壤湿度": (0, 100, 60), "光照": (0, 1000, 500)}
        for name in SENSORS:
            lo, hi, init = ranges[name]
            var = tk.DoubleVar(value=init)
            self.sensor_vars[name] = var
            row = ttk.Frame(sf)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=name, width=8).pack(side="left")
            lab = ttk.Label(row, text=f"{init:.0f}{SENSOR_UNIT[name]}", width=7)
            lab.pack(side="right")
            s = ttk.Scale(row, from_=lo, to=hi, variable=var,
                          command=lambda v, n=name, l=lab: self.on_sensor(n, l))
            s.pack(side="left", fill="x", expand=True, padx=4)

        mf = ttk.Labelframe(left, text="控制模式", padding=8)
        mf.pack(fill="x", pady=6)
        self.mode_btn = ttk.Button(mf, text="当前：手动模式（点击切换）", command=self.toggle_mode)
        self.mode_btn.pack(fill="x")
        ttk.Checkbutton(mf, text="蜂鸣器静音（非 Windows 自动静音）",
                        variable=self.mute).pack(anchor="w", pady=(6, 0))

        qf = ttk.Labelframe(left, text="控制序列播放（操作区）", padding=8)
        qf.pack(fill="both", expand=True, pady=6)
        ttk.Label(qf, text="按时间顺序执行一串动作：").pack(anchor="w")
        self.seq_list = tk.Listbox(qf, height=12, font=("", 9))
        self.seq_list.pack(fill="both", expand=True, pady=4)
        for i, (delay, dev, act) in enumerate(self.seq_steps):
            self.seq_list.insert("end", f"{i+1:02d}. 等待{delay}s → {dev} {act}")
        bf = ttk.Frame(qf)
        bf.pack(fill="x")
        self.seq_btn = ttk.Button(bf, text="▶ 播放演示序列", command=self.seq_toggle)
        self.seq_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))
        ttk.Button(bf, text="⟲ 重置", command=self.seq_reset).pack(side="left", expand=True, fill="x")

        # ---- 中间：设备面板 ----
        mid = ttk.Labelframe(main, text="虚拟设备面板（结果区）", padding=4)
        mid.grid(row=0, column=1, sticky="nsew", padx=(0, 6))
        self.cv = tk.Canvas(mid, bg="#1b1024", highlightthickness=0)
        self.cv.pack(fill="both", expand=True)

        ctrl = ttk.Frame(mid)
        ctrl.pack(fill="x", pady=4)
        # 手动开关按钮
        self.dev_btns = {}
        for a in ACTUATORS:
            b = ttk.Button(ctrl, text=a + " 开", width=10,
                           command=lambda a=a: self.manual_toggle(a))
            b.pack(side="left", padx=2)
            self.dev_btns[a] = b

        ctrl2 = ttk.Frame(mid)
        ctrl2.pack(fill="x", pady=2)
        ttk.Label(ctrl2, text="舵机角度").pack(side="left")
        self.servo_lab = ttk.Label(ctrl2, text="0°", width=5)
        ttk.Scale(ctrl2, from_=0, to=180, variable=self.servo_angle,
                  command=self.on_servo).pack(side="left", fill="x", expand=True, padx=4)
        self.servo_lab.pack(side="left")
        for i, ch in enumerate("RGB"):
            ttk.Label(ctrl2, text=ch).pack(side="left", padx=(8, 0))
            ttk.Scale(ctrl2, from_=0, to=255, variable=self.led_rgb[i], length=70,
                      command=lambda v: None).pack(side="left")

        # ---- 右侧：规则 + 日志 ----
        right = ttk.Frame(main)
        right.grid(row=0, column=2, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        rf = ttk.Labelframe(right, text="控制规则编辑器", padding=6)
        rf.grid(row=0, column=0, sticky="ew")
        r1 = ttk.Frame(rf)
        r1.pack(fill="x")
        ttk.Label(r1, text="当").pack(side="left")
        self.c_sen = ttk.Combobox(r1, values=SENSORS, width=8, state="readonly")
        self.c_sen.current(0)
        self.c_sen.pack(side="left", padx=2)
        self.c_op = ttk.Combobox(r1, values=OPS, width=3, state="readonly")
        self.c_op.current(0)
        self.c_op.pack(side="left", padx=2)
        self.c_th = ttk.Spinbox(r1, from_=0, to=1000, width=6)
        self.c_th.delete(0, "end")
        self.c_th.insert(0, "30")
        self.c_th.pack(side="left", padx=2)
        ttk.Label(r1, text="时").pack(side="left")
        r2 = ttk.Frame(rf)
        r2.pack(fill="x", pady=3)
        self.c_do = ttk.Combobox(r2, values=ACTIONS, width=5, state="readonly")
        self.c_do.current(0)
        self.c_do.pack(side="left", padx=2)
        self.c_act = ttk.Combobox(r2, values=ACTUATORS, width=9, state="readonly")
        self.c_act.current(1)
        self.c_act.pack(side="left", padx=2)
        ttk.Button(r2, text="＋添加", width=6, command=self.add_rule).pack(side="left", padx=2)
        ttk.Button(r2, text="－删除", width=6, command=self.del_rule).pack(side="left", padx=2)
        ttk.Button(r2, text="启用/停用", width=8, command=self.toggle_rule).pack(side="left", padx=2)

        tf = ttk.Labelframe(right, text="规则列表", padding=4)
        tf.grid(row=1, column=0, sticky="nsew", pady=4)
        cols = ("sensor", "op", "th", "act", "do", "en")
        self.tree = ttk.Treeview(tf, columns=cols, show="headings", height=6)
        heads = ["传感器", "比较", "阈值", "执行器", "动作", "启用"]
        widths = [70, 40, 50, 76, 46, 42]
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(fill="both", expand=True)

        lf = ttk.Labelframe(right, text="运行日志（时间 · 触发原因）", padding=4)
        lf.grid(row=2, column=0, sticky="nsew")
        self.log_box = tk.Text(lf, height=8, font=("", 9), state="disabled",
                               bg="#140b1c", fg="#e7d6e0")
        self.log_box.pack(fill="both", expand=True)
        ttk.Button(lf, text="清空日志", command=self.clear_logs).pack(anchor="e", pady=2)

        # 状态栏
        self.status = ttk.Label(self.root, text="就绪 · 全部设备为虚拟模拟，不连接真实硬件",
                                relief="sunken", anchor="w")
        self.status.pack(fill="x", side="bottom")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- Canvas 绘制 ----------------
    def _draw_static(self):
        pass  # 全部在 _tick 中重绘，保持简单

    def _device_positions(self):
        w = max(self.cv.winfo_width(), 600)
        h = max(self.cv.winfo_height(), 360)
        cw, ch = w / 3, h / 2
        names = ["LED补光灯", "蜂鸣器", "继电器", "舵机", "风扇", "水泵"]
        pos = {}
        for i, n in enumerate(names):
            cx = (i % 3) * cw + cw / 2
            cy = (i // 3) * ch + ch / 2
            pos[n] = (cx, cy, min(cw, ch) * 0.32)
        return pos

    def _redraw(self):
        cv = self.cv
        cv.delete("all")
        pos = self._device_positions()
        for name, (cx, cy, r) in pos.items():
            cv.create_rectangle(cx - r * 1.45, cy - r * 1.45, cx + r * 1.45, cy + r * 1.55,
                                outline="#4c3358", fill="#2a1b33", width=1)
            on = self.state.get(name, False)
            title = name
            if name == "舵机":
                title = f"舵机 {self.servo_angle.get()}°"
            cv.create_text(cx, cy - r * 1.2, text=title, fill="#f5b8c4", font=("", 10, "bold"))
            st = "开启" if on else "关闭"
            if name == "舵机":
                st = "角度控制"
            cv.create_text(cx, cy + r * 1.3, text=st,
                           fill="#34d399" if on else "#8d6b7d", font=("", 9))

            if name == "LED补光灯":
                rgb = tuple(v.get() for v in self.led_rgb)
                color = "#%02x%02x%02x" % rgb if on else "#241627"
                if on:
                    cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline=color)
                cv.create_oval(cx - r * .62, cy - r * .62, cx + r * .62, cy + r * .62,
                               fill=color, outline="#c3a8b8", width=2)
                if on:
                    cv.create_text(cx, cy + r * .95, text=f"RGB{rgb}", fill="#c3a8b8", font=("", 8))
            elif name == "蜂鸣器":
                blink = on and self.buzz_blink
                cv.create_oval(cx - r * .6, cy - r * .6, cx + r * .6, cy + r * .6,
                               fill="#3d2848", outline="#fb923c", width=2)
                cv.create_oval(cx - r * .18, cy - r * .18, cx + r * .18, cy + r * .18,
                               fill="#fb923c" if blink else "#5d4468", outline="")
                if blink:
                    for k in (1.0, 1.3):
                        cv.create_arc(cx - r * k, cy - r * k, cx + r * k, cy + r * k,
                                      start=-40, extent=80, style="arc",
                                      outline="#fbbf24", width=2)
            elif name == "继电器":
                x0, y0 = cx - r, cy
                cv.create_line(x0 - r * .4, y0, x0 + r * .3, y0, fill="#c3a8b8", width=3)
                ang = 0 if on else -28
                a = math.radians(ang)
                x1, y1 = x0 + r * .3, y0
                x2 = x1 + r * 1.0 * math.cos(a)
                y2 = y1 + r * 1.0 * math.sin(a)
                cv.create_line(x1, y1, x2, y2, fill="#fbbf24", width=3)
                cv.create_line(x1 + r, y0, cx + r, y0, fill="#c3a8b8", width=3)
                lamp = "#fbbf24" if on else "#2a1b33"
                cv.create_oval(cx + r * .75, y0 - r * .25, cx + r * 1.25, y0 + r * .25,
                               fill=lamp, outline="#c3a8b8")
                cv.create_text(cx, cy + r * .75,
                               text="高电平1·吸合" if on else "低电平0·断开",
                               fill="#c3a8b8", font=("", 8))
            elif name == "舵机":
                cv.create_rectangle(cx - r * .5, cy + r * .1, cx + r * .5, cy + r * .7,
                                    fill="#3d2848", outline="#f43f5e")
                ang = math.radians(180 - self.servo_angle.get())
                x2 = cx + r * 1.05 * math.cos(ang)
                y2 = cy + r * .1 - r * 1.05 * math.sin(ang) + r * .0
                cv.create_line(cx, cy + r * .1, x2, y2, fill="#f43f5e", width=4)
                cv.create_oval(cx - 4, cy + r * .1 - 4, cx + 4, cy + r * .1 + 4, fill="#fb7185", outline="")
            elif name == "风扇":
                for i in range(3):
                    a = math.radians(self.fan_phase + i * 120)
                    x2 = cx + r * .85 * math.cos(a)
                    y2 = cy + r * .85 * math.sin(a)
                    cv.create_line(cx, cy, x2, y2, fill="#fb7185", width=6, capstyle="round")
                cv.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, fill="#f43f5e", outline="")
            elif name == "水泵":
                cv.create_rectangle(cx - r * .55, cy - r * .3, cx + r * .55, cy + r * .45,
                                    fill="#3d2848", outline="#60a5fa", width=2)
                cv.create_text(cx, cy + r * .08, text="泵", fill="#93c5fd", font=("", 10))
                if on:
                    dp = self.drop_phase % 1.0
                    for k in range(3):
                        yy = cy - r * .45 - ((dp + k * 0.33) % 1.0) * r * .8
                        cv.create_oval(cx - 4, yy - 6, cx + 4, yy + 4, fill="#60a5fa", outline="")

    # ---------------- 周期刷新 ----------------
    def _tick(self):
        if self._closing:
            return
        if self.state["风扇"]:
            self.fan_phase = (self.fan_phase + 16) % 360
        if self.state["水泵"]:
            self.drop_phase += 0.06
        self.buzz_blink = (int(time.time() * 4) % 2 == 0)
        self._redraw()
        self.root.after(60, self._tick)

    # ---------------- 设备控制 ----------------
    def set_actuator(self, name, on, reason):
        if name == "舵机":
            return
        if self.state.get(name) == on:
            return
        self.state[name] = on
        self.dev_btns[name].config(text=f"{name} {'关' if on else '开'}")
        self.log(f"{name} {'开启' if on else '关闭'} —— {reason}")
        if name == "蜂鸣器" and on and not self.mute.get() and HAS_WINSOUND:
            try:
                winsound.Beep(880, 200)
            except RuntimeError:
                pass

    def manual_toggle(self, name):
        if self.auto_mode.get():
            self.log(f"手动点击 {name} 无效：当前为自动模式（执行器由规则控制）")
            return
        self.set_actuator(name, not self.state[name], "手动模式下点击开关")

    def on_servo(self, _v):
        self.servo_lab.config(text=f"{self.servo_angle.get()}°")

    def on_sensor(self, name, lab):
        v = self.sensor_vars[name].get()
        lab.config(text=f"{v:.0f}{SENSOR_UNIT[name]}")
        if self.auto_mode.get():
            self.apply_rules(f"拖动{name}滑块")

    def toggle_mode(self):
        auto = not self.auto_mode.get()
        self.auto_mode.set(auto)
        self.mode_btn.config(text=f"当前：{'自动' if auto else '手动'}模式（点击切换）")
        self.log(f"已切换到{'自动' if auto else '手动'}模式")
        self.status.config(text=f"{'自动' if auto else '手动'}模式运行中")
        if auto:
            self.apply_rules("切换到自动模式")

    # ---------------- 规则 ----------------
    def add_rule(self):
        try:
            th = float(self.c_th.get())
        except ValueError:
            messagebox.showwarning("提示", "阈值请填数字，例如 30")
            return
        rule = dict(sensor=self.c_sen.get(), op=self.c_op.get(), th=th,
                    actuator=self.c_act.get(), action=self.c_do.get(), enabled=True)
        self.rules.append(rule)
        self.refresh_tree()
        self.log(f"添加规则：当 {rule['sensor']} {rule['op']} {th:g} 时 {rule['action']} {rule['actuator']}")
        if self.auto_mode.get():
            self.apply_rules("新规则生效")

    def del_rule(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在规则列表中选中一条规则")
            return
        idx = self.tree.index(sel[0])
        r = self.rules.pop(idx)
        self.refresh_tree()
        self.log(f"删除规则：{r['sensor']} {r['op']} {r['th']:g} → {r['action']}{r['actuator']}")

    def toggle_rule(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中一条规则")
            return
        idx = self.tree.index(sel[0])
        self.rules[idx]["enabled"] = not self.rules[idx]["enabled"]
        self.refresh_tree()
        if self.auto_mode.get():
            self.apply_rules("规则启停变化")

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for r in self.rules:
            self.tree.insert("", "end", values=(
                r["sensor"], r["op"], f"{r['th']:g}", r["actuator"],
                r["action"], "✔" if r["enabled"] else "—"))

    @staticmethod
    def _cmp(v, op, th):
        if op == ">":
            return v > th
        if op == "<":
            return v < th
        if op == ">=":
            return v >= th
        if op == "<=":
            return v <= th
        return False

    def apply_rules(self, cause):
        vals = {n: self.sensor_vars[n].get() for n in SENSORS}
        for i, r in enumerate(self.rules):
            if not r["enabled"]:
                continue
            v = vals[r["sensor"]]
            hit = self._cmp(v, r["op"], r["th"])
            unit = SENSOR_UNIT[r["sensor"]]
            if r["action"] == "开启":
                if hit and not self.state[r["actuator"]]:
                    self.set_actuator(r["actuator"], True,
                                      f"规则{i+1}触发：{r['sensor']}={v:.0f}{unit} {r['op']} {r['th']:g}（{cause}）")
                elif not hit and self.state[r["actuator"]]:
                    self.set_actuator(r["actuator"], False,
                                      f"规则{i+1}条件不再满足：{r['sensor']}={v:.0f}{unit}")
            else:  # 关闭
                if hit and self.state[r["actuator"]]:
                    self.set_actuator(r["actuator"], False,
                                      f"规则{i+1}触发关闭：{r['sensor']}={v:.0f}{unit} {r['op']} {r['th']:g}（{cause}）")

    # ---------------- 控制序列 ----------------
    def seq_toggle(self):
        if self.seq_running:
            self.seq_running = False
            if self.seq_after:
                self.root.after_cancel(self.seq_after)
                self.seq_after = None
            self.seq_btn.config(text="▶ 继续播放")
            self.log("控制序列已暂停")
        else:
            self.seq_running = True
            self.seq_btn.config(text="⏸ 暂停")
            self.log("控制序列开始/继续播放")
            self._seq_step()

    def _seq_step(self):
        if not self.seq_running or self._closing:
            return
        if self.seq_index >= len(self.seq_steps):
            self.seq_running = False
            self.seq_btn.config(text="▶ 播放演示序列")
            self.log("控制序列播放完毕")
            self.seq_index = 0
            self.seq_list.selection_clear(0, "end")
            return
        delay, dev, act = self.seq_steps[self.seq_index]
        self.seq_list.selection_clear(0, "end")
        self.seq_list.selection_set(self.seq_index)
        self.seq_list.see(self.seq_index)
        if dev == "舵机":
            self.servo_angle.set(int(act))
            self.servo_lab.config(text=f"{act}°")
            self.log(f"序列第{self.seq_index+1}步：舵机转到 {act}°")
        else:
            self.set_actuator(dev, act == "开启", f"序列第{self.seq_index+1}步")
        self.seq_index += 1
        self.seq_after = self.root.after(int(delay * 1000), self._seq_step)

    def seq_reset(self):
        self.seq_running = False
        if self.seq_after:
            self.root.after_cancel(self.seq_after)
            self.seq_after = None
        self.seq_index = 0
        self.seq_btn.config(text="▶ 播放演示序列")
        self.seq_list.selection_clear(0, "end")
        for a in ACTUATORS:
            self.set_actuator(a, False, "序列重置")
        self.servo_angle.set(0)
        self.servo_lab.config(text="0°")
        self.log("控制序列已重置，全部执行器关闭")

    # ---------------- 日志 / 导入导出 ----------------
    def log(self, msg):
        t = time.strftime("%H:%M:%S")
        self.logs.append((t, msg))
        self.log_box.config(state="normal")
        self.log_box.insert("end", f"[{t}] {msg}\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def clear_logs(self):
        self.logs.clear()
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")

    def export_rules(self, fmt):
        if not self.rules:
            messagebox.showinfo("提示", "还没有规则可导出")
            return
        ext = ".json" if fmt == "json" else ".csv"
        path = filedialog.asksaveasfilename(defaultextension=ext,
                                            initialfile="控制规则" + ext,
                                            filetypes=[(fmt.upper(), "*" + ext)])
        if not path:
            return
        if fmt == "json":
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"lesson": "第1单元第5节 物联网的控制", "rules": self.rules},
                          f, ensure_ascii=False, indent=2)
        else:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["传感器", "比较符", "阈值", "执行器", "动作", "启用"])
                for r in self.rules:
                    w.writerow([r["sensor"], r["op"], r["th"], r["actuator"],
                                r["action"], "是" if r["enabled"] else "否"])
        self.log(f"规则已导出到 {path}")

    def import_rules(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            rules = data["rules"] if isinstance(data, dict) else data
            cnt = 0
            for r in rules:
                if all(k in r for k in ("sensor", "op", "th", "actuator", "action")):
                    r.setdefault("enabled", True)
                    self.rules.append(r)
                    cnt += 1
            self.refresh_tree()
            self.log(f"从 {path} 导入 {cnt} 条规则")
        except (OSError, ValueError, KeyError) as e:
            messagebox.showerror("导入失败", f"文件格式不正确：{e}")

    def export_logs(self, fmt):
        if not self.logs:
            messagebox.showinfo("提示", "日志为空")
            return
        ext = ".json" if fmt == "json" else ".csv"
        path = filedialog.asksaveasfilename(defaultextension=ext,
                                            initialfile="运行日志" + ext,
                                            filetypes=[(fmt.upper(), "*" + ext)])
        if not path:
            return
        if fmt == "json":
            with open(path, "w", encoding="utf-8") as f:
                json.dump([{"time": t, "msg": m} for t, m in self.logs],
                          f, ensure_ascii=False, indent=2)
        else:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["时间", "内容"])
                w.writerows(self.logs)
        self.log(f"日志已导出到 {path}")

    def show_help(self):
        win = tk.Toplevel(self.root)
        win.title("使用帮助")
        win.geometry("560x520")
        txt = tk.Text(win, wrap="word", font=("", 10), padx=10, pady=10)
        txt.insert("1.0", HELP_TEXT)
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True)
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=6)

    def on_close(self):
        self._closing = True
        if self.seq_after:
            self.root.after_cancel(self.seq_after)
        self.root.destroy()


def main():
    root = tk.Tk()
    Console(root)
    root.mainloop()


if __name__ == "__main__":
    main()
