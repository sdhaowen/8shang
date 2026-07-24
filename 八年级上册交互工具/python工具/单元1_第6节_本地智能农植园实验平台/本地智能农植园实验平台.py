# -*- coding: utf-8 -*-
"""
课时：清华大学出版社《信息科技》八年级上册 第1单元 第6节《物联网系统的搭建》
工具：本地智能农植园实验平台（Tkinter 样板级工具）
七大功能：
  1. 虚拟传感器：温度/空气湿度/光照/土壤湿度，手动滑块 + 自动随机变化，
     合理范围检查，采样间隔可设置，实时数值显示。
  2. 本地消息中转：进程内发布—订阅模拟（queue + threading 实现教学 Broker 类），
     显示 发布者/Topic/消息/订阅者 流转日志，可启动/停止/清空。
     ★ 它对应真实物联网中的 MQTT 服务器（如 SIoT）：发布者把消息交给中转站，
       中转站按 Topic 查订阅表转发，发布者和订阅者不直接见面。
  3. 自动控制：水泵/风扇/补光灯/蜂鸣器四条阈值规则可配置，手动/自动模式，
     记录触发原因和时间，Canvas 绘制执行器状态图标。
  4. 数据存储：SQLite 保存 时间/温度/湿度/光照/土壤湿度/执行器状态，
     Treeview 查看最近记录、按时间筛选、导出 CSV、清空数据（需确认）。
  5. 实时曲线：tkinter.Canvas 自绘 4 条传感器曲线（不同颜色 + 图例 + 网格）。
  6. 系统诊断：一键检查消息服务/Topic匹配/数据范围/规则冲突/数据文件可写。
  7. 项目导出：设备配置、Topic、规则、数据摘要、日志、项目小结 → JSON / TXT。
运行方法：python3 本地智能农植园实验平台.py （全部标准库，无需第三方依赖）
说明：全部设备为虚拟模拟，不连接真实网络与硬件；程序退出时停止全部线程并关闭数据库。
"""

import csv
import json
import os
import queue
import random
import sqlite3
import threading
import time

# ---------------------------------------------------------------------------
# 教学配置（全部为虚构示例）
# ---------------------------------------------------------------------------
SENSORS = ["温度", "空气湿度", "光照", "土壤湿度"]
SENSOR_UNIT = {"温度": "℃", "空气湿度": "%", "光照": "lx", "土壤湿度": "%"}
SLIDER_RANGE = {"温度": (-10, 60), "空气湿度": (0, 100), "光照": (0, 2000), "土壤湿度": (0, 100)}
REASONABLE = {"温度": (0, 45), "空气湿度": (20, 95), "光照": (0, 1500), "土壤湿度": (5, 95)}
TOPIC_OF = {
    "温度": "smartfarm/device01/temperature",
    "空气湿度": "smartfarm/device01/humidity",
    "光照": "smartfarm/device01/light",
    "土壤湿度": "smartfarm/device01/soil",
}
ACTUATORS = ["水泵", "风扇", "补光灯", "蜂鸣器"]
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "农植园数据.db")

DEFAULT_RULES = [
    {"sensor": "土壤湿度", "op": "<", "th": 40.0, "actuator": "水泵", "action": "开启"},
    {"sensor": "温度", "op": ">", "th": 32.0, "actuator": "风扇", "action": "开启"},
    {"sensor": "光照", "op": "<", "th": 300.0, "actuator": "补光灯", "action": "开启"},
    # 蜂鸣器规则特殊：数据超合理范围即报警（在 evaluate_rules 中单独处理）
]


# ---------------------------------------------------------------------------
# 教学版 Broker：进程内发布—订阅消息中转（对应真实的 MQTT 服务器）
# ---------------------------------------------------------------------------
class TeachingBroker:
    """用 queue + threading 模拟 MQTT 服务器的发布—订阅转发。

    与真实 MQTT 的对应关系：
      publish(发布者, Topic, 消息)  ≈ siot.publish(topic, value)
      subscribe(Topic, 订阅者名, 回调) ≈ siot.subscribe(topic, callback)
      内部转发线程                  ≈ 服务器按 Topic 查订阅表并投递
    区别：真实 MQTT 走网络（默认 1883 端口），这里在同一进程内用队列传递，
    不需要网络，方便课堂教学观察消息流转。
    """

    def __init__(self):
        self._q = queue.Queue()
        self._subs = {}           # topic -> [(订阅者名, 回调), ...]
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self.delivered = 0        # 成功送达条数
        self.dropped = 0          # 无人订阅而丢弃的条数
        self.flow_log = []        # (时间, 发布者, topic, 消息, 订阅者串)
        self._log_lock = threading.Lock()

    # ---- 生命周期 ----
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    @property
    def running(self):
        return self._running

    # ---- 发布订阅 ----
    def subscribe(self, topic, name, callback):
        with self._lock:
            self._subs.setdefault(topic, []).append((name, callback))

    def subscribed_topics(self):
        with self._lock:
            return list(self._subs.keys())

    def publish(self, publisher, topic, payload):
        """把消息交给中转站。服务器未启动时消息将无法送达（与真实 MQTT 一致）。"""
        if not self._running:
            self._log(publisher, topic, payload, "✗ 服务器未启动，消息丢失")
            return False
        self._q.put((publisher, topic, payload))
        return True

    # ---- 内部 ----
    def _loop(self):
        while self._running:
            try:
                publisher, topic, payload = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            with self._lock:
                subs = list(self._subs.get(topic, []))
            if subs:
                names = []
                for name, cb in subs:
                    try:
                        cb(topic, payload)
                    except Exception:
                        pass
                    names.append(name)
                self.delivered += 1
                self._log(publisher, topic, payload, "✓ 送达：" + "、".join(names))
            else:
                self.dropped += 1
                self._log(publisher, topic, payload, "✗ 无订阅者，消息被丢弃")

    def _log(self, publisher, topic, payload, result):
        with self._log_lock:
            self.flow_log.append((time.strftime("%H:%M:%S"), publisher, topic, str(payload), result))
            if len(self.flow_log) > 500:
                del self.flow_log[:100]

    def take_log(self, start_index):
        """返回 start_index 之后的新日志（供 GUI 轮询）。"""
        with self._log_lock:
            return list(self.flow_log[start_index:]), len(self.flow_log)

    def clear_log(self):
        with self._log_lock:
            self.flow_log.clear()
        self.delivered = 0
        self.dropped = 0


# ---------------------------------------------------------------------------
# 规则判断（纯函数，便于无 GUI 自测）
# ---------------------------------------------------------------------------
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


def out_of_range(values, reasonable=None):
    """返回超出合理范围的说明列表；空列表表示数据正常。"""
    reasonable = reasonable or REASONABLE
    problems = []
    for name, v in values.items():
        lo, hi = reasonable.get(name, (float("-inf"), float("inf")))
        if v < lo or v > hi:
            problems.append(f"{name}={v:g}{SENSOR_UNIT.get(name, '')} 超出合理范围 {lo}~{hi}")
    return problems


def evaluate_rules(values, rules, buzzer_on_abnormal=True):
    """根据传感器值和规则，计算每个执行器的目标状态。

    返回 dict: 执行器 -> (是否开启, 原因说明)
    """
    result = {a: (False, "无规则触发") for a in ACTUATORS}
    for i, r in enumerate(rules):
        v = values.get(r["sensor"])
        if v is None:
            continue
        if _cmp(v, r["op"], r["th"]):
            on = r.get("action", "开启") == "开启"
            reason = (f"规则{i+1}：{r['sensor']}={v:g}{SENSOR_UNIT.get(r['sensor'], '')} "
                      f"{r['op']} {r['th']:g} → {r.get('action', '开启')}{r['actuator']}")
            result[r["actuator"]] = (on, reason)
    if buzzer_on_abnormal:
        problems = out_of_range(values)
        if problems:
            result["蜂鸣器"] = (True, "数据异常报警：" + "；".join(problems))
    return result


def check_rule_conflicts(rules):
    """检查同一执行器是否存在方向相反、可能同时成立的规则，返回冲突说明列表。"""
    conflicts = []
    n = len(rules)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = rules[i], rules[j]
            if a["actuator"] != b["actuator"]:
                continue
            if a.get("action") == b.get("action"):
                continue
            # 动作相反：判断两个条件是否可能同时为真
            if a["sensor"] != b["sensor"]:
                overlap = True   # 不同传感器的条件完全可能同时满足
            else:
                gt = {">", ">="}
                lt = {"<", "<="}
                if a["op"] in gt and b["op"] in lt:
                    overlap = a["th"] < b["th"]
                elif a["op"] in lt and b["op"] in gt:
                    overlap = b["th"] < a["th"]
                else:
                    overlap = True
            if overlap:
                conflicts.append(
                    f"规则{i+1}与规则{j+1}冲突：都控制「{a['actuator']}」但动作相反，"
                    f"且条件可能同时成立（{a['sensor']}{a['op']}{a['th']:g} 与 "
                    f"{b['sensor']}{b['op']}{b['th']:g}）")
    return conflicts


HELP_TEXT = """【本地智能农植园实验平台 · 使用帮助】

本平台在一台计算机上完整模拟"传感器 → 消息中转 → 自动控制 → 数据存储"
的物联网系统，对应教材第6节的搭建流程。

① 监控与控制页
   左侧是 4 个虚拟传感器滑块，可勾选"自动随机变化"让数据自己波动；
   采样间隔可设 1~10 秒。右侧 Canvas 显示 4 个执行器状态。
   自动模式下按规则控制执行器；手动模式下可点按钮直接开关。

② 消息中转页
   先点"启动消息服务"（相当于运行 SIoT 服务器）。每次采样，
   平台会把 4 个传感器数据"发布"到各自 Topic，控制端"订阅"后收到数据。
   日志显示 发布者/Topic/消息/订阅者 全过程。
   试试：停止消息服务后，观察消息"丢失"——这就是真实系统中
   "MQTT 服务器未启动"故障的样子。

③ 数据记录页
   每次采样自动写入 SQLite 数据库；可按最近N条/时间筛选、导出 CSV、
   清空示例数据（有确认对话框）。

④ 实时曲线页
   Canvas 自绘 4 条彩色曲线，带网格与图例。

⑤ 系统诊断页
   一键检查：消息服务是否启动 / Topic 是否匹配 / 数据是否超范围 /
   规则是否冲突 / 数据文件是否可写，逐项给出 ✔/✖ 与修复建议。

⑥ 项目导出页
   填写项目小结，一键导出 JSON 与 TXT 项目报告。

常见问题
   Q: 曲线不动？ → 请确认已勾选"自动随机变化"或手动拖动滑块。
   Q: 执行器不响应？ → 检查是否在自动模式、消息服务是否已启动。
   Q: 数据库文件在哪里？ → 与程序同目录的 农植园数据.db。
"""


# ---------------------------------------------------------------------------
# GUI（仅在直接运行时构建）
# ---------------------------------------------------------------------------
def run_gui():
    import tkinter as tk
    from tkinter import ttk

    COLORS = {"温度": "#dc2626", "空气湿度": "#2563eb", "光照": "#d97706", "土壤湿度": "#16a34a"}

    class App:
        def __init__(self, root):
            self.root = root
            root.title("本地智能农植园实验平台 —— 八年级上册 第1单元 第6节《物联网系统的搭建》")
            root.geometry("1200x760")
            root.minsize(1020, 660)

            self.broker = TeachingBroker()
            self.log_index = 0
            self.closing = False

            # 数据库
            self.db = sqlite3.connect(DB_FILE)
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS records("
                "ts TEXT, 温度 REAL, 空气湿度 REAL, 光照 REAL, 土壤湿度 REAL,"
                "水泵 TEXT, 风扇 TEXT, 补光灯 TEXT, 蜂鸣器 TEXT)")
            self.db.commit()

            # 状态
            self.sensor_vars = {}
            self.auto_random = tk.BooleanVar(value=True)
            self.auto_mode = tk.BooleanVar(value=True)
            self.interval = tk.IntVar(value=2)
            self.actuator_state = {a: False for a in ACTUATORS}
            self.rules = [dict(r) for r in DEFAULT_RULES]
            self.history = []          # [(t, {sensor: value}), ...] 供曲线
            self.recv_values = {}      # 控制端订阅收到的最新值
            self.recv_lock = threading.Lock()
            self.ctrl_logs = []
            self.sample_count = 0

            self._build_menu()
            self._build_ui()
            self._subscribe_control_end()

            self.log_ctrl("平台启动。请到「消息中转」页启动消息服务，然后观察数据流转。")
            self.root.protocol("WM_DELETE_WINDOW", self.on_close)
            self._sample_job = self.root.after(500, self._sample_tick)
            self._poll_job = self.root.after(400, self._poll_broker_log)

        # ---------------- 界面 ----------------
        def _build_menu(self):
            import tkinter as tk2
            m = tk2.Menu(self.root)
            fm = tk2.Menu(m, tearoff=0)
            fm.add_command(label="导出项目 JSON", command=lambda: self.export_project("json"))
            fm.add_command(label="导出项目 TXT", command=lambda: self.export_project("txt"))
            fm.add_command(label="导出数据 CSV", command=self.export_csv)
            fm.add_separator()
            fm.add_command(label="退出", command=self.on_close)
            m.add_cascade(label="文件", menu=fm)
            hm = tk2.Menu(m, tearoff=0)
            hm.add_command(label="使用帮助", command=self.show_help)
            m.add_cascade(label="帮助", menu=hm)
            self.root.config(menu=m)

        def _build_ui(self):
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except Exception:
                pass
            style.configure("TNotebook.Tab", padding=(14, 6))

            self.nb = ttk.Notebook(self.root)
            self.nb.pack(fill="both", expand=True, padx=4, pady=4)
            self.tab_main = ttk.Frame(self.nb)
            self.tab_broker = ttk.Frame(self.nb)
            self.tab_data = ttk.Frame(self.nb)
            self.tab_curve = ttk.Frame(self.nb)
            self.tab_diag = ttk.Frame(self.nb)
            self.tab_export = ttk.Frame(self.nb)
            self.nb.add(self.tab_main, text=" ① 监控与控制 ")
            self.nb.add(self.tab_broker, text=" ② 消息中转 ")
            self.nb.add(self.tab_data, text=" ③ 数据记录 ")
            self.nb.add(self.tab_curve, text=" ④ 实时曲线 ")
            self.nb.add(self.tab_diag, text=" ⑤ 系统诊断 ")
            self.nb.add(self.tab_export, text=" ⑥ 项目导出 ")

            self._build_tab_main()
            self._build_tab_broker()
            self._build_tab_data()
            self._build_tab_curve()
            self._build_tab_diag()
            self._build_tab_export()

            self.status = ttk.Label(self.root, relief="sunken", anchor="w",
                                    text="就绪 · 全部为虚拟模拟，不连接真实网络与硬件")
            self.status.pack(fill="x", side="bottom")

        def _build_tab_main(self):
            import tkinter as tk2
            f = self.tab_main
            f.columnconfigure(1, weight=1)
            f.rowconfigure(0, weight=1)

            left = ttk.Labelframe(f, text="虚拟传感器（输入区）", padding=8)
            left.grid(row=0, column=0, sticky="ns", padx=6, pady=6)
            init = {"温度": 25, "空气湿度": 60, "光照": 600, "土壤湿度": 55}
            self.sensor_labels = {}
            for name in SENSORS:
                lo, hi = SLIDER_RANGE[name]
                var = tk2.DoubleVar(value=init[name])
                self.sensor_vars[name] = var
                row = ttk.Frame(left)
                row.pack(fill="x", pady=4)
                ttk.Label(row, text=name, width=8).pack(side="left")
                lab = ttk.Label(row, text=f"{init[name]}{SENSOR_UNIT[name]}", width=8)
                lab.pack(side="right")
                self.sensor_labels[name] = lab
                ttk.Scale(row, from_=lo, to=hi, variable=var, length=170,
                          command=lambda v, n=name: self._on_slider(n)).pack(side="left", padx=4)
            ttk.Checkbutton(left, text="自动随机变化（模拟真实环境波动）",
                            variable=self.auto_random).pack(anchor="w", pady=(8, 2))
            r2 = ttk.Frame(left)
            r2.pack(fill="x", pady=2)
            ttk.Label(r2, text="采样间隔(秒)").pack(side="left")
            ttk.Spinbox(r2, from_=1, to=10, textvariable=self.interval, width=4).pack(side="left", padx=4)
            self.range_lab = ttk.Label(left, text="数据范围检查：正常", foreground="#16a34a",
                                       wraplength=210, justify="left")
            self.range_lab.pack(anchor="w", pady=6)

            mode = ttk.Labelframe(left, text="控制模式", padding=6)
            mode.pack(fill="x", pady=4)
            ttk.Radiobutton(mode, text="自动模式（按规则控制）", variable=self.auto_mode,
                            value=True).pack(anchor="w")
            ttk.Radiobutton(mode, text="手动模式（按钮控制）", variable=self.auto_mode,
                            value=False).pack(anchor="w")
            btns = ttk.Frame(mode)
            btns.pack(fill="x", pady=4)
            self.manual_btns = {}
            for a in ACTUATORS:
                b = ttk.Button(btns, text=a + " 开", width=8,
                               command=lambda a=a: self.manual_toggle(a))
                b.pack(side="left", padx=1)
                self.manual_btns[a] = b

            right = ttk.Frame(f)
            right.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
            right.rowconfigure(1, weight=1)
            right.columnconfigure(0, weight=1)

            rules = ttk.Labelframe(right, text="自动控制规则（阈值可配置）", padding=8)
            rules.grid(row=0, column=0, sticky="ew")
            self.th_vars = {}
            texts = [("土壤湿度", "<", "水泵", "%"), ("温度", ">", "风扇", "℃"), ("光照", "<", "补光灯", "lx")]
            rowf = ttk.Frame(rules)
            rowf.pack(fill="x")
            for i, (sen, op, act, unit) in enumerate(texts):
                var = tk2.DoubleVar(value=self.rules[i]["th"])
                self.th_vars[act] = var
                cell = ttk.Frame(rowf)
                cell.pack(side="left", padx=8)
                ttk.Label(cell, text=f"当 {sen} {op}").pack(side="left")
                ttk.Spinbox(cell, from_=0, to=2000, textvariable=var, width=6,
                            command=self._sync_thresholds).pack(side="left", padx=2)
                ttk.Label(cell, text=f"{unit} → 开{act}").pack(side="left")
            ttk.Label(rules, text="蜂鸣器：任一数据超合理范围（温度0~45℃/空气湿度20~95%/光照≤1500lx/土壤5~95%）即报警",
                      foreground="#92400e").pack(anchor="w", pady=(6, 0))

            cvf = ttk.Labelframe(right, text="执行器状态面板（结果区）", padding=4)
            cvf.grid(row=1, column=0, sticky="nsew", pady=6)
            self.cv = tk2.Canvas(cvf, bg="#f0fdf4", highlightthickness=0, height=230)
            self.cv.pack(fill="both", expand=True)

            logf = ttk.Labelframe(right, text="自动控制日志（时间 · 触发原因）", padding=4)
            logf.grid(row=2, column=0, sticky="ew")
            self.ctrl_text = tk2.Text(logf, height=7, font=("", 9), state="disabled",
                                      bg="#14532d", fg="#d7f7e2")
            self.ctrl_text.pack(fill="both", expand=True)

            self.fan_phase = 0.0
            self.drop_phase = 0.0
            self._anim_job = self.root.after(80, self._animate)

        def _build_tab_broker(self):
            f = self.tab_broker
            top = ttk.Frame(f, padding=8)
            top.pack(fill="x")
            self.broker_btn = ttk.Button(top, text="▶ 启动消息服务", command=self.toggle_broker)
            self.broker_btn.pack(side="left")
            ttk.Button(top, text="清空日志", command=self.clear_broker_log).pack(side="left", padx=6)
            self.broker_lab = ttk.Label(top, text="状态：未启动（消息将无法送达）", foreground="#dc2626")
            self.broker_lab.pack(side="left", padx=10)

            note = ttk.Label(f, padding=(10, 0), justify="left", foreground="#4e7a5d", text=(
                "教学说明：本页用 队列(queue)+线程(threading) 在进程内模拟 MQTT 服务器（如教材中的 SIoT）。\n"
                "发布者 publish(Topic, 消息) → 中转站按 Topic 查订阅表 → 转发给所有订阅者。真实系统中它走网络(默认1883端口)，原理相同。"))
            note.pack(fill="x")

            cols = ("t", "pub", "topic", "msg", "sub")
            heads = ["时间", "发布者", "Topic", "消息", "订阅者/结果"]
            widths = [70, 110, 240, 120, 260]
            self.flow_tree = ttk.Treeview(f, columns=cols, show="headings")
            for c, h, w in zip(cols, heads, widths):
                self.flow_tree.heading(c, text=h)
                self.flow_tree.column(c, width=w, anchor="w")
            self.flow_tree.pack(fill="both", expand=True, padx=8, pady=6)
            self.broker_stat = ttk.Label(f, text="送达 0 条 · 丢弃 0 条", padding=(10, 2))
            self.broker_stat.pack(anchor="w")

        def _build_tab_data(self):
            f = self.tab_data
            top = ttk.Frame(f, padding=8)
            top.pack(fill="x")
            ttk.Label(top, text="显示最近").pack(side="left")
            self.limit_var = ttk.Combobox(top, values=["20", "50", "100", "200"], width=5, state="readonly")
            self.limit_var.current(1)
            self.limit_var.pack(side="left", padx=4)
            ttk.Label(top, text="条记录；或筛选时间包含").pack(side="left")
            self.filter_entry = ttk.Entry(top, width=10)
            self.filter_entry.pack(side="left", padx=4)
            ttk.Label(top, text="（如 14: 表示14点）").pack(side="left")
            ttk.Button(top, text="🔍 查询", command=self.refresh_data).pack(side="left", padx=6)
            ttk.Button(top, text="导出 CSV", command=self.export_csv).pack(side="left", padx=4)
            ttk.Button(top, text="清空示例数据", command=self.clear_db).pack(side="left", padx=4)

            cols = ["ts"] + SENSORS + ACTUATORS
            heads = ["时间"] + [s + SENSOR_UNIT[s] for s in SENSORS] + ACTUATORS
            self.data_tree = ttk.Treeview(f, columns=cols, show="headings")
            for c, h in zip(cols, heads):
                self.data_tree.heading(c, text=h)
                self.data_tree.column(c, width=100 if c == "ts" else 78, anchor="center")
            self.data_tree.pack(fill="both", expand=True, padx=8, pady=6)
            self.data_stat = ttk.Label(f, text="", padding=(10, 2))
            self.data_stat.pack(anchor="w")

        def _build_tab_curve(self):
            import tkinter as tk2
            f = self.tab_curve
            self.curve = tk2.Canvas(f, bg="#ffffff", highlightthickness=0)
            self.curve.pack(fill="both", expand=True, padx=8, pady=8)
            ttk.Label(f, text="曲线为最近 120 次采样，按各传感器量程归一化显示。",
                      padding=(10, 0)).pack(anchor="w", pady=(0, 6))

        def _build_tab_diag(self):
            import tkinter as tk2
            f = self.tab_diag
            top = ttk.Frame(f, padding=10)
            top.pack(fill="x")
            ttk.Button(top, text="🩺 一键系统诊断", command=self.run_diag).pack(side="left")
            ttk.Label(top, text="逐项检查系统健康状况，✖ 项会给出修复建议。").pack(side="left", padx=10)
            self.diag_text = tk2.Text(f, font=("", 10), state="disabled", bg="#fbfffc")
            self.diag_text.pack(fill="both", expand=True, padx=10, pady=6)

        def _build_tab_export(self):
            import tkinter as tk2
            f = self.tab_export
            ttk.Label(f, text="项目小结（可编辑，会写入导出的报告）：", padding=(10, 8)).pack(anchor="w")
            self.summary_text = tk2.Text(f, height=7, font=("", 10))
            self.summary_text.pack(fill="x", padx=10)
            self.summary_text.insert("1.0", "我搭建的智能农植园系统：用本地消息中转站（对应 SIoT 服务器）转发 4 个传感器"
                                            "Topic 的数据，控制端订阅数据后按阈值规则自动控制水泵、风扇、补光灯，异常时蜂鸣器报警。")
            row = ttk.Frame(f, padding=10)
            row.pack(anchor="w")
            ttk.Button(row, text="📦 导出项目 JSON", command=lambda: self.export_project("json")).pack(side="left", padx=4)
            ttk.Button(row, text="📄 导出项目 TXT", command=lambda: self.export_project("txt")).pack(side="left", padx=4)
            self.preview = tk2.Text(f, font=("", 9), state="disabled", bg="#14532d", fg="#d7f7e2")
            self.preview.pack(fill="both", expand=True, padx=10, pady=(0, 10))
            ttk.Button(f, text="🔄 刷新预览", command=self.refresh_preview).pack(anchor="w", padx=10, pady=(0, 10))

        # ---------------- 传感器与采样 ----------------
        def _on_slider(self, name):
            v = self.sensor_vars[name].get()
            self.sensor_labels[name].config(text=f"{v:.0f}{SENSOR_UNIT[name]}")

        def sensor_values(self):
            return {n: round(self.sensor_vars[n].get(), 1) for n in SENSORS}

        def _sample_tick(self):
            if self.closing:
                return
            # 自动随机波动
            if self.auto_random.get():
                for n in SENSORS:
                    lo, hi = SLIDER_RANGE[n]
                    step = (hi - lo) * 0.02
                    v = self.sensor_vars[n].get() + random.uniform(-step, step)
                    self.sensor_vars[n].set(max(lo, min(hi, v)))
                    self._on_slider(n)
            values = self.sensor_values()
            self.sample_count += 1
            # 合理范围检查
            problems = out_of_range(values)
            if problems:
                self.range_lab.config(text="数据范围检查：⚠ " + "；".join(problems), foreground="#dc2626")
            else:
                self.range_lab.config(text="数据范围检查：正常", foreground="#16a34a")
            # 发布到消息中转（对应真实系统里终端向 MQTT 服务器发消息）
            for n in SENSORS:
                self.broker.publish("传感终端device01", TOPIC_OF[n], f"{values[n]:g}")
            # 自动控制（以控制端收到的数据为准；若服务未启动则收不到新数据）
            if self.auto_mode.get():
                with self.recv_lock:
                    recv = dict(self.recv_values)
                if recv:
                    target = evaluate_rules(recv, self.rules)
                    for act, (on, reason) in target.items():
                        self.set_actuator(act, on, reason if on else "条件不满足，保持/恢复关闭")
            # 历史与存储
            self.history.append((time.strftime("%H:%M:%S"), values))
            if len(self.history) > 120:
                self.history.pop(0)
            self.db.execute(
                "INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"), values["温度"], values["空气湿度"],
                 values["光照"], values["土壤湿度"],
                 *["开" if self.actuator_state[a] else "关" for a in ACTUATORS]))
            self.db.commit()
            self.draw_curve()
            self.status.config(text=f"采样 #{self.sample_count} · {values} · 消息服务"
                                    f"{'运行中' if self.broker.running else '未启动'}")
            self._sample_job = self.root.after(max(1, self.interval.get()) * 1000, self._sample_tick)

        # ---------------- 消息中转 ----------------
        def _subscribe_control_end(self):
            def make_cb(sensor_name):
                def cb(topic, payload):
                    try:
                        val = float(payload)
                    except ValueError:
                        return
                    with self.recv_lock:
                        self.recv_values[sensor_name] = val
                return cb
            for n in SENSORS:
                self.broker.subscribe(TOPIC_OF[n], "自动控制端", make_cb(n))

        def toggle_broker(self):
            if self.broker.running:
                self.broker.stop()
                self.broker_btn.config(text="▶ 启动消息服务")
                self.broker_lab.config(text="状态：已停止（试试观察消息丢失）", foreground="#dc2626")
                self.log_ctrl("消息服务已停止 —— 之后发布的消息将无法送达（模拟服务器未启动故障）")
            else:
                self.broker.start()
                self.broker_btn.config(text="⏹ 停止消息服务")
                self.broker_lab.config(text="状态：运行中（进程内教学 Broker）", foreground="#16a34a")
                self.log_ctrl("消息服务已启动，开始转发消息")

        def _poll_broker_log(self):
            if self.closing:
                return
            rows, self.log_index = self.broker.take_log(self.log_index)
            for r in rows:
                self.flow_tree.insert("", "end", values=r)
            kids = self.flow_tree.get_children()
            if len(kids) > 300:
                for k in kids[:100]:
                    self.flow_tree.delete(k)
            if rows:
                self.flow_tree.see(self.flow_tree.get_children()[-1])
            self.broker_stat.config(text=f"送达 {self.broker.delivered} 条 · 丢弃 {self.broker.dropped} 条")
            self._poll_job = self.root.after(400, self._poll_broker_log)

        def clear_broker_log(self):
            self.broker.clear_log()
            self.log_index = 0
            self.flow_tree.delete(*self.flow_tree.get_children())

        # ---------------- 执行器 ----------------
        def set_actuator(self, name, on, reason):
            if self.actuator_state[name] == on:
                return
            self.actuator_state[name] = on
            self.manual_btns[name].config(text=f"{name} {'关' if on else '开'}")
            self.log_ctrl(f"{name} {'开启' if on else '关闭'} —— {reason}")

        def manual_toggle(self, name):
            if self.auto_mode.get():
                self.log_ctrl(f"手动点击 {name} 无效：当前为自动模式（执行器由规则控制）")
                return
            self.set_actuator(name, not self.actuator_state[name], "手动模式下点击开关")

        def _sync_thresholds(self):
            try:
                self.rules[0]["th"] = float(self.th_vars["水泵"].get())
                self.rules[1]["th"] = float(self.th_vars["风扇"].get())
                self.rules[2]["th"] = float(self.th_vars["补光灯"].get())
            except (ValueError, KeyError):
                pass

        def _animate(self):
            if self.closing:
                return
            self._sync_thresholds()
            if self.actuator_state["风扇"]:
                self.fan_phase = (self.fan_phase + 20) % 360
            if self.actuator_state["水泵"]:
                self.drop_phase += 0.08
            self._draw_actuators()
            self._anim_job = self.root.after(80, self._animate)

        def _draw_actuators(self):
            import math
            cv = self.cv
            cv.delete("all")
            w = max(cv.winfo_width(), 500)
            h = max(cv.winfo_height(), 180)
            cw = w / 4
            for i, name in enumerate(ACTUATORS):
                cx, cy = cw * i + cw / 2, h / 2
                r = min(cw, h) * 0.26
                on = self.actuator_state[name]
                cv.create_text(cx, cy - r - 22, text=name, font=("", 11, "bold"), fill="#14532d")
                cv.create_text(cx, cy + r + 20, text="开启" if on else "关闭",
                               fill="#16a34a" if on else "#9ca3af", font=("", 10))
                if name == "水泵":
                    cv.create_rectangle(cx - r * .7, cy - r * .3, cx + r * .7, cy + r * .5,
                                        fill="#dbeafe", outline="#2563eb", width=2)
                    if on:
                        dp = self.drop_phase % 1.0
                        for k in range(3):
                            yy = cy - r * .5 - ((dp + k * .33) % 1.0) * r
                            cv.create_oval(cx - 5 + (k - 1) * 10, yy - 6, cx + 5 + (k - 1) * 10, yy + 4,
                                           fill="#3b82f6", outline="")
                elif name == "风扇":
                    for k in range(3):
                        a = math.radians(self.fan_phase + k * 120)
                        cv.create_line(cx, cy, cx + r * math.cos(a), cy + r * math.sin(a),
                                       width=7, capstyle="round",
                                       fill="#16a34a" if on else "#9ca3af")
                    cv.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, fill="#15803d", outline="")
                elif name == "补光灯":
                    color = "#fbbf24" if on else "#e5e7eb"
                    if on:
                        cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#fef3c7", outline="")
                    cv.create_oval(cx - r * .55, cy - r * .55, cx + r * .55, cy + r * .55,
                                   fill=color, outline="#d97706", width=2)
                elif name == "蜂鸣器":
                    blink = on and (int(time.time() * 4) % 2 == 0)
                    cv.create_oval(cx - r * .6, cy - r * .6, cx + r * .6, cy + r * .6,
                                   fill="#fff7ed", outline="#ea580c", width=2)
                    cv.create_oval(cx - r * .2, cy - r * .2, cx + r * .2, cy + r * .2,
                                   fill="#dc2626" if blink else "#9ca3af", outline="")

        def log_ctrl(self, msg):
            t = time.strftime("%H:%M:%S")
            self.ctrl_logs.append((t, msg))
            if len(self.ctrl_logs) > 300:
                del self.ctrl_logs[:100]
            self.ctrl_text.config(state="normal")
            self.ctrl_text.insert("end", f"[{t}] {msg}\n")
            self.ctrl_text.see("end")
            self.ctrl_text.config(state="disabled")

        # ---------------- 数据 ----------------
        def refresh_data(self):
            self.data_tree.delete(*self.data_tree.get_children())
            limit = int(self.limit_var.get())
            flt = self.filter_entry.get().strip()
            if flt:
                cur = self.db.execute(
                    "SELECT * FROM records WHERE ts LIKE ? ORDER BY ts DESC LIMIT ?",
                    (f"%{flt}%", limit))
            else:
                cur = self.db.execute("SELECT * FROM records ORDER BY ts DESC LIMIT ?", (limit,))
            rows = cur.fetchall()
            for r in rows:
                self.data_tree.insert("", "end", values=r)
            total = self.db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            self.data_stat.config(text=f"数据库共 {total} 条记录，当前显示 {len(rows)} 条"
                                       f"（文件：{os.path.basename(DB_FILE)}）")

        def export_csv(self):
            from tkinter import filedialog as fd
            path = fd.asksaveasfilename(defaultextension=".csv", initialfile="农植园数据.csv",
                                        filetypes=[("CSV", "*.csv")])
            if not path:
                return
            cur = self.db.execute("SELECT * FROM records ORDER BY ts")
            with open(path, "w", encoding="utf-8-sig", newline="") as fobj:
                w = csv.writer(fobj)
                w.writerow(["时间"] + SENSORS + ACTUATORS)
                w.writerows(cur.fetchall())
            self.log_ctrl(f"数据已导出 CSV：{path}")

        def clear_db(self):
            from tkinter import messagebox as mb
            if not mb.askyesno("确认", "确定清空数据库中的全部示例数据吗？此操作不可恢复。"):
                return
            self.db.execute("DELETE FROM records")
            self.db.commit()
            self.refresh_data()
            self.log_ctrl("数据库已清空")

        # ---------------- 曲线 ----------------
        def draw_curve(self):
            cv = self.curve
            if not cv.winfo_ismapped() and self.nb.index(self.nb.select()) != 3:
                return
            cv.delete("all")
            w = max(cv.winfo_width(), 400)
            h = max(cv.winfo_height(), 260)
            ml, mr, mt, mb2 = 46, 16, 30, 34
            pw, ph = w - ml - mr, h - mt - mb2
            # 网格
            for i in range(6):
                y = mt + ph * i / 5
                cv.create_line(ml, y, w - mr, y, fill="#e5e7eb")
                cv.create_text(ml - 6, y, text=f"{100 - i * 20}%", anchor="e", fill="#9ca3af", font=("", 8))
            for i in range(7):
                x = ml + pw * i / 6
                cv.create_line(x, mt, x, h - mb2, fill="#f3f4f6")
            data = self.history
            if len(data) >= 2:
                n = len(data)
                for name in SENSORS:
                    lo, hi = SLIDER_RANGE[name]
                    pts = []
                    for i, (_, vals) in enumerate(data):
                        x = ml + pw * i / max(1, n - 1)
                        ratio = (vals[name] - lo) / (hi - lo)
                        y = mt + ph * (1 - max(0, min(1, ratio)))
                        pts.extend([x, y])
                    cv.create_line(*pts, fill=COLORS[name], width=2, smooth=True)
                # x 轴时间标注
                cv.create_text(ml, h - mb2 + 14, text=data[0][0], anchor="w", fill="#9ca3af", font=("", 8))
                cv.create_text(w - mr, h - mb2 + 14, text=data[-1][0], anchor="e", fill="#9ca3af", font=("", 8))
            # 图例
            x = ml
            for name in SENSORS:
                cv.create_rectangle(x, 8, x + 14, 18, fill=COLORS[name], outline="")
                cv.create_text(x + 20, 13, text=f"{name}({SENSOR_UNIT[name]})", anchor="w", font=("", 9),
                               fill="#374151")
                x += 110

        # ---------------- 诊断 ----------------
        def run_diag(self):
            lines = ["===== 系统诊断报告 " + time.strftime("%H:%M:%S") + " =====", ""]

            def item(ok, title, advice):
                lines.append(("✔ " if ok else "✖ ") + title)
                if not ok:
                    lines.append("    建议：" + advice)

            item(self.broker.running, "消息服务（教学 Broker）已启动",
                 "请到「消息中转」页点击「启动消息服务」，否则所有消息无法送达（对应真实故障：MQTT 服务器未启动）")
            pub_topics = set(TOPIC_OF.values())
            sub_topics = set(self.broker.subscribed_topics())
            missing = pub_topics - sub_topics
            item(not missing, "发布 Topic 与订阅 Topic 匹配",
                 "以下 Topic 没有订阅者：" + "、".join(missing) + "（对应真实故障：发布与订阅 Topic 不一致）" if missing else "")
            values = self.sensor_values()
            problems = out_of_range(values)
            item(not problems, "传感器数据在合理范围内",
                 "；".join(problems) + "。请检查传感器（本平台中可把滑块调回正常值）")
            conflicts = check_rule_conflicts(self.rules)
            item(not conflicts, "控制规则无冲突",
                 "；".join(conflicts) if conflicts else "")
            writable = True
            try:
                self.db.execute("SELECT 1")
                test_path = os.path.join(os.path.dirname(DB_FILE), ".write_test")
                with open(test_path, "w", encoding="utf-8") as fobj:
                    fobj.write("ok")
                os.remove(test_path)
            except (OSError, sqlite3.Error):
                writable = False
            item(writable, "数据文件可读写（SQLite 正常）",
                 "请检查程序所在文件夹的写入权限")
            total = self.db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            lines.append("")
            lines.append(f"参考信息：已采样 {self.sample_count} 次；数据库 {total} 条记录；"
                         f"消息送达 {self.broker.delivered} 条、丢弃 {self.broker.dropped} 条。")
            self.diag_text.config(state="normal")
            self.diag_text.delete("1.0", "end")
            self.diag_text.insert("1.0", "\n".join(lines))
            self.diag_text.config(state="disabled")
            self.log_ctrl("已执行一键系统诊断")

        # ---------------- 导出 ----------------
        def project_data(self):
            cur = self.db.execute(
                "SELECT COUNT(*), MIN(温度), MAX(温度), AVG(温度), MIN(土壤湿度), MAX(土壤湿度), AVG(土壤湿度) FROM records")
            cnt, tmin, tmax, tavg, smin, smax, savg = cur.fetchone()
            summary = self.summary_text.get("1.0", "end").strip()
            return {
                "lesson": "第1单元 第6节 物联网系统的搭建",
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "设备配置": ["温度传感器", "空气湿度传感器", "光照传感器", "土壤湿度传感器",
                             "智能终端(虚拟)", "本地消息中转站(教学Broker)", "水泵", "风扇", "补光灯", "蜂鸣器"],
                "Topic清单": list(TOPIC_OF.values()) + ["smartfarm/control/pump(预留)"],
                "控制规则": [
                    f"当 土壤湿度 < {self.rules[0]['th']:g}% 开水泵",
                    f"当 温度 > {self.rules[1]['th']:g}℃ 开风扇",
                    f"当 光照 < {self.rules[2]['th']:g}lx 开补光灯",
                    "数据超合理范围 → 蜂鸣器报警",
                ],
                "数据摘要": {
                    "记录条数": cnt or 0,
                    "温度范围": None if tmin is None else f"{tmin:.1f}~{tmax:.1f}℃(均值{tavg:.1f})",
                    "土壤湿度范围": None if smin is None else f"{smin:.1f}~{smax:.1f}%(均值{savg:.1f})",
                },
                "消息统计": {"送达": self.broker.delivered, "丢弃": self.broker.dropped},
                "测试日志(最近10条)": [f"[{t}] {m}" for t, m in self.ctrl_logs[-10:]],
                "项目小结": summary,
            }

        def project_text(self):
            d = self.project_data()
            L = ["=" * 44, " 智能农植园物联网系统 · 项目报告", " " + d["lesson"], " 生成时间：" + d["time"], "=" * 44, ""]
            L.append("【设备配置】")
            L += ["  · " + x for x in d["设备配置"]]
            L.append("")
            L.append("【Topic 清单】")
            L += ["  · " + x for x in d["Topic清单"]]
            L.append("")
            L.append("【控制规则】")
            L += ["  · " + x for x in d["控制规则"]]
            L.append("")
            L.append("【数据摘要】")
            for k, v in d["数据摘要"].items():
                L.append(f"  {k}：{v if v is not None else '（暂无数据）'}")
            L.append(f"  消息送达 {d['消息统计']['送达']} 条 / 丢弃 {d['消息统计']['丢弃']} 条")
            L.append("")
            L.append("【测试日志（最近10条）】")
            L += ["  " + x for x in d["测试日志(最近10条)"]] or ["  （暂无）"]
            L.append("")
            L.append("【项目小结】")
            L.append("  " + (d["项目小结"] or "（未填写）"))
            return "\n".join(L)

        def refresh_preview(self):
            self.preview.config(state="normal")
            self.preview.delete("1.0", "end")
            self.preview.insert("1.0", self.project_text())
            self.preview.config(state="disabled")

        def export_project(self, fmt):
            from tkinter import filedialog as fd
            ext = ".json" if fmt == "json" else ".txt"
            path = fd.asksaveasfilename(defaultextension=ext,
                                        initialfile="智能农植园项目" + ext,
                                        filetypes=[(fmt.upper(), "*" + ext)])
            if not path:
                return
            with open(path, "w", encoding="utf-8") as fobj:
                if fmt == "json":
                    json.dump(self.project_data(), fobj, ensure_ascii=False, indent=2)
                else:
                    fobj.write(self.project_text())
            self.log_ctrl(f"项目已导出：{path}")

        # ---------------- 其他 ----------------
        def show_help(self):
            import tkinter as tk2
            win = tk2.Toplevel(self.root)
            win.title("使用帮助")
            win.geometry("620x560")
            txt = tk2.Text(win, wrap="word", font=("", 10), padx=10, pady=10)
            txt.insert("1.0", HELP_TEXT)
            txt.config(state="disabled")
            txt.pack(fill="both", expand=True)
            ttk.Button(win, text="关闭", command=win.destroy).pack(pady=6)

        def on_close(self):
            self.closing = True
            for job in ("_sample_job", "_poll_job", "_anim_job"):
                j = getattr(self, job, None)
                if j is not None:
                    try:
                        self.root.after_cancel(j)
                    except Exception:
                        pass
            self.broker.stop()
            try:
                self.db.commit()
                self.db.close()
            except sqlite3.Error:
                pass
            self.root.destroy()

    root = tk.Tk()
    app = App(root)
    # 初次填充数据页
    root.after(1200, app.refresh_data)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
