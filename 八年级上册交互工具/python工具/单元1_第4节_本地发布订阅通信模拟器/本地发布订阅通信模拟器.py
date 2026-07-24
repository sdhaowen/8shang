# -*- coding: utf-8 -*-
"""
本地发布订阅通信模拟器（教学版，非真实 MQTT）
配套课时：清华大学出版社《信息科技》八年级上册 第1单元 第4节《物联网的通信》
功能：
  用标准库 socket + threading 在 127.0.0.1 上实现一个极简教学"消息中转站"，
  模拟 MQTT 的发布/订阅通信机制：
    · 中转站面板：启动/停止按钮，连接与转发日志；
    · 发布者面板：Topic 输入、消息输入、发布按钮、自动周期发布虚拟温湿度数据；
    · 订阅者面板：可添加多个订阅者，各自订阅 Topic（支持 + 与 # 通配符教学实现），
      收到的消息滚动显示。
  消息日志可导出 JSON / CSV；帮助窗口说明协议格式。
自定义文本协议（UTF-8，每行一条命令，用 | 分隔）：
    NAME|昵称                 —— 客户端报到，登记显示名
    SUB|topic模式             —— 订阅（模式可含 + 和 #）
    UNSUB|topic模式           —— 退订
    PUB|topic|消息内容        —— 发布；中转站转发给所有匹配的订阅者
    中转站 → 订阅者：MSG|topic|消息内容
运行方法：
    python3 本地发布订阅通信模拟器.py            # 打开图形界面
    python3 本地发布订阅通信模拟器.py --selftest # 无界面逻辑自测（不弹窗）
说明：仅绑定 127.0.0.1，完全离线；退出时优雅关闭所有 socket 与线程；
      全部使用标准库，无需安装任何第三方库（也不需要 paho-mqtt）。
"""

import csv
import json
import queue
import random
import socket
import sys
import threading
import time

APP_TITLE = "本地发布订阅通信模拟器（教学版） · 八年级上册 第1单元 第4节 物联网的通信"
DEFAULT_PORT = 18830

# ======================================================================
#  第一部分：可独立测试的核心逻辑（不依赖 GUI，也不依赖 socket）
# ======================================================================

def topic_matches(pattern, topic):
    """判断订阅模式 pattern 是否匹配主题 topic。
    规则（与 MQTT 一致的教学实现）：
      · 层级用 / 分隔；
      · '+' 匹配恰好一层；
      · '#' 匹配其后所有层级，只能出现在模式末尾；
      · 其余层必须逐字相等。
    """
    if not pattern or not topic:
        return False
    p_parts = pattern.split("/")
    t_parts = topic.split("/")
    for i, seg in enumerate(p_parts):
        if seg == "#":
            # '#' 必须是最后一层才有效
            return i == len(p_parts) - 1
        if i >= len(t_parts):
            return False
        if seg == "+":
            continue
        if seg != t_parts[i]:
            return False
    return len(p_parts) == len(t_parts)


class BrokerCore:
    """中转站的订阅登记与消息路由逻辑（纯逻辑，可独立测试）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._subs = {}   # client_id -> set(订阅模式)

    def subscribe(self, client_id, pattern):
        with self._lock:
            self._subs.setdefault(client_id, set()).add(pattern)

    def unsubscribe(self, client_id, pattern):
        with self._lock:
            if client_id in self._subs:
                self._subs[client_id].discard(pattern)

    def remove_client(self, client_id):
        with self._lock:
            self._subs.pop(client_id, None)

    def subscriptions_of(self, client_id):
        with self._lock:
            return sorted(self._subs.get(client_id, set()))

    def route(self, topic):
        """返回应收到该 topic 消息的 client_id 列表（去重、稳定排序）。"""
        with self._lock:
            hit = []
            for cid, patterns in self._subs.items():
                if any(topic_matches(p, topic) for p in patterns):
                    hit.append(cid)
            return sorted(hit)


# ======================================================================
#  第二部分：基于 socket 的中转站服务器（仅绑定 127.0.0.1）
# ======================================================================

class BrokerServer:
    """极简教学消息中转站。event_cb(kind, text) 用于向界面上报日志。"""

    def __init__(self, port, event_cb=None):
        self.port = port
        self.event_cb = event_cb or (lambda kind, text: None)
        self.core = BrokerCore()
        self._srv = None
        self._threads = []
        self._clients = {}          # client_id -> (conn, 显示名)
        self._clients_lock = threading.Lock()
        self._next_id = 0
        self._running = threading.Event()

    # ---------- 生命周期 ----------
    def start(self):
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", self.port))
        self._srv.listen(16)
        self._running.set()
        t = threading.Thread(target=self._accept_loop, daemon=True,
                             name="broker-accept")
        t.start()
        self._threads.append(t)
        self._emit("sys", "中转站已启动，监听 127.0.0.1:%d" % self.port)

    def stop(self):
        if not self._running.is_set():
            return
        self._running.clear()
        try:
            self._srv.close()
        except OSError:
            pass
        with self._clients_lock:
            conns = [c for c, _n in self._clients.values()]
            self._clients.clear()
        for c in conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                c.close()
            except OSError:
                pass
        self._emit("sys", "中转站已停止，所有连接已关闭。")

    @property
    def running(self):
        return self._running.is_set()

    # ---------- 内部 ----------
    def _emit(self, kind, text):
        try:
            self.event_cb(kind, text)
        except Exception:
            pass

    def _accept_loop(self):
        while self._running.is_set():
            try:
                conn, _addr = self._srv.accept()
            except OSError:
                break
            with self._clients_lock:
                self._next_id += 1
                cid = self._next_id
                self._clients[cid] = (conn, "客户端%d" % cid)
            t = threading.Thread(target=self._client_loop, args=(cid, conn),
                                 daemon=True, name="broker-client-%d" % cid)
            t.start()
            self._threads.append(t)
            self._emit("conn", "新连接接入（编号%d）" % cid)

    def _name_of(self, cid):
        with self._clients_lock:
            item = self._clients.get(cid)
            return item[1] if item else ("客户端%d" % cid)

    def _client_loop(self, cid, conn):
        buf = b""
        try:
            while self._running.is_set():
                try:
                    data = conn.recv(4096)
                except OSError:
                    break
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._handle_line(cid, conn, line.decode("utf-8", "replace").strip())
        finally:
            self.core.remove_client(cid)
            name = self._name_of(cid)
            with self._clients_lock:
                self._clients.pop(cid, None)
            try:
                conn.close()
            except OSError:
                pass
            if self._running.is_set():
                self._emit("conn", "%s 断开连接" % name)

    def _handle_line(self, cid, conn, line):
        if not line:
            return
        parts = line.split("|", 2)
        cmd = parts[0].upper()
        if cmd == "NAME" and len(parts) >= 2:
            with self._clients_lock:
                if cid in self._clients:
                    self._clients[cid] = (conn, parts[1])
            self._emit("conn", "编号%d 报到，名称：%s" % (cid, parts[1]))
        elif cmd == "SUB" and len(parts) >= 2:
            self.core.subscribe(cid, parts[1])
            self._emit("sub", "%s 订阅了 %s" % (self._name_of(cid), parts[1]))
        elif cmd == "UNSUB" and len(parts) >= 2:
            self.core.unsubscribe(cid, parts[1])
            self._emit("sub", "%s 退订了 %s" % (self._name_of(cid), parts[1]))
        elif cmd == "PUB" and len(parts) >= 3:
            topic, payload = parts[1], parts[2]
            targets = self.core.route(topic)
            self._emit("pub", "%s 发布 [%s]「%s」→ 匹配 %d 个订阅者"
                       % (self._name_of(cid), topic, payload, len(targets)))
            msg = ("MSG|%s|%s\n" % (topic, payload)).encode("utf-8")
            for tid in targets:
                with self._clients_lock:
                    item = self._clients.get(tid)
                if item is None:
                    continue
                try:
                    item[0].sendall(msg)
                    self._emit("fwd", "  ↳ 转发给 %s" % self._name_of(tid))
                except OSError:
                    self._emit("err", "  ↳ 转发给 %s 失败（连接已断）" % self._name_of(tid))
            if not targets:
                self._emit("fwd", "  ↳ 无人订阅该主题，消息未转发")
        else:
            self._emit("err", "无法识别的命令：%s" % line)


# ======================================================================
#  第三部分：GUI（Tkinter）
# ======================================================================

HELP_TEXT = """【这是什么】
本工具在你的电脑内部（127.0.0.1 本机回环地址）搭建一个极简
"消息中转站"，模拟教材中 MQTT 协议的发布/订阅通信机制：
  发布者 --PUB--> 中转站(代理broker) --按Topic匹配--> 订阅者

【为什么说它是"模拟"而不是真实 MQTT】
1. 真实 MQTT 是国际标准二进制协议（报文头最小仅2字节），本工具
   为了让同学们"看得懂每一个字节"，改用了简单的文本协议；
2. 真实 MQTT 还有 QoS 服务质量、遗嘱消息、保留消息、心跳等机制，
   本工具只保留了最核心的"发布/订阅/按主题转发"；
3. 但"客户端只连服务器、双方靠同一个 Topic 沟通"的思想完全一致。

【协议格式】（每行一条命令，UTF-8 编码，字段用 | 分隔）
  NAME|昵称              客户端报到
  SUB|farm/sensor/temp   订阅主题（支持 + 匹配一层、# 匹配多层）
  UNSUB|主题             退订
  PUB|主题|内容          发布消息
  服务器发给订阅者：MSG|主题|内容

【操作步骤】
1. 点【启动中转站】；
2. 在"订阅者"面板输入名称和要订阅的 Topic，点【添加订阅者】，
   可添加多个（试试 farm/+/temp 或 farm/# 通配订阅）；
3. 在"发布者"面板填 Topic 与内容点【发布】，或勾选【自动发布】
   让虚拟传感器每2秒发一条温/湿度数据；
4. 观察中转站日志与各订阅者收到的消息：Topic 匹配的才收得到！
5. 点【导出日志】保存为 JSON 或 CSV。

【故障排查】
· 端口被占用：换一个端口号（1024~65535）再启动；
· 添加订阅者失败：请先启动中转站；
· 收不到消息：检查发布 Topic 与订阅模式是否匹配（注意 + 只顶一层）；
· 本工具不连接互联网、不连接真实设备，仅在本机进程内通信。
"""


def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    class SubscriberClient:
        """GUI 中的一个订阅者：独立 socket 连接 + 接收线程。"""

        def __init__(self, name, pattern, port, gui_queue):
            self.name = name
            self.pattern = pattern
            self.gui_queue = gui_queue
            self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
            self.sock.sendall(("NAME|%s\nSUB|%s\n" % (name, pattern)).encode("utf-8"))
            self.alive = True
            self.thread = threading.Thread(target=self._recv_loop, daemon=True,
                                           name="sub-" + name)
            self.thread.start()

        def _recv_loop(self):
            buf = b""
            try:
                while self.alive:
                    try:
                        data = self.sock.recv(4096)
                    except OSError:
                        break
                    if not data:
                        break
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        parts = line.decode("utf-8", "replace").split("|", 2)
                        if len(parts) == 3 and parts[0] == "MSG":
                            self.gui_queue.put(("submsg", self.name, parts[1], parts[2]))
            finally:
                self.gui_queue.put(("subdead", self.name, "", ""))

        def close(self):
            self.alive = False
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass

    class App:
        def __init__(self, root):
            self.root = root
            root.title(APP_TITLE)
            root.geometry("1200x760")
            root.minsize(1000, 640)
            self.broker = None
            self.pub_sock = None
            self.subs = {}          # 名称 -> (SubscriberClient, Text控件, frame)
            self.records = []       # 导出用日志
            self.gui_queue = queue.Queue()
            self.auto_pub = tk.BooleanVar(value=False)
            self._build()
            self._poll_queue()
            root.protocol("WM_DELETE_WINDOW", self.on_close)

        # ---------------- 界面 ----------------
        def _build(self):
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except Exception:
                pass
            style.configure("TLabelframe.Label",
                            font=("Microsoft YaHei", 10, "bold"))

            top = ttk.Frame(self.root, padding=(10, 8))
            top.pack(fill="x")
            ttk.Label(top, text="端口：").pack(side="left")
            self.var_port = tk.IntVar(value=DEFAULT_PORT)
            self.sp_port = ttk.Spinbox(top, from_=1024, to=65535,
                                       textvariable=self.var_port, width=7)
            self.sp_port.pack(side="left", padx=(0, 10))
            self.btn_start = ttk.Button(top, text="▶ 启动中转站", command=self.start_broker)
            self.btn_start.pack(side="left", padx=3)
            self.btn_stop = ttk.Button(top, text="■ 停止中转站", command=self.stop_broker,
                                       state="disabled")
            self.btn_stop.pack(side="left", padx=3)
            ttk.Button(top, text="导出日志JSON", command=self.export_json).pack(side="left", padx=3)
            ttk.Button(top, text="导出日志CSV", command=self.export_csv).pack(side="left", padx=3)
            ttk.Button(top, text="清空日志", command=self.clear_log).pack(side="left", padx=3)
            ttk.Button(top, text="帮助", command=self.show_help).pack(side="right", padx=3)

            body = ttk.Frame(self.root, padding=(10, 0, 10, 4))
            body.pack(fill="both", expand=True)
            body.columnconfigure(0, weight=5)
            body.columnconfigure(1, weight=4)
            body.rowconfigure(0, weight=1)
            body.rowconfigure(1, weight=1)

            # 中转站面板
            bk = ttk.LabelFrame(body, text="① 中转站（消息代理 broker）——连接与转发日志", padding=6)
            bk.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=4)
            self.txt_log = tk.Text(bk, state="disabled", bg="#1e1b2e", fg="#c4b5fd",
                                   font=("Consolas", 10), wrap="none")
            lsb = ttk.Scrollbar(bk, orient="vertical", command=self.txt_log.yview)
            self.txt_log.configure(yscrollcommand=lsb.set)
            self.txt_log.pack(side="left", fill="both", expand=True)
            lsb.pack(side="right", fill="y")
            for tag, color in (("sys", "#facc15"), ("conn", "#818cf8"),
                               ("sub", "#7dd3fc"), ("pub", "#f9a8d4"),
                               ("fwd", "#86efac"), ("err", "#fca5a5")):
                self.txt_log.tag_configure(tag, foreground=color)

            # 发布者面板
            pb = ttk.LabelFrame(body, text="② 发布者面板", padding=8)
            pb.grid(row=1, column=0, sticky="nsew", padx=(0, 6), pady=4)
            r1 = ttk.Frame(pb); r1.pack(fill="x", pady=2)
            ttk.Label(r1, text="Topic：").pack(side="left")
            self.var_pub_topic = tk.StringVar(value="farm/sensor/temp")
            ttk.Entry(r1, textvariable=self.var_pub_topic, width=32,
                      font=("Consolas", 10)).pack(side="left", padx=4)
            r2 = ttk.Frame(pb); r2.pack(fill="x", pady=2)
            ttk.Label(r2, text="内容：").pack(side="left")
            self.var_pub_payload = tk.StringVar(value="温度 25.0℃")
            ttk.Entry(r2, textvariable=self.var_pub_payload, width=40).pack(
                side="left", padx=4, fill="x", expand=True)
            r3 = ttk.Frame(pb); r3.pack(fill="x", pady=4)
            ttk.Button(r3, text="📤 发布这条消息", command=self.publish_once).pack(side="left")
            ttk.Checkbutton(r3, text="自动发布：每2秒发一条虚拟温/湿度数据",
                            variable=self.auto_pub,
                            command=self.toggle_auto).pack(side="left", padx=10)
            ttk.Label(pb, foreground="#666", text=(
                "提示：自动发布轮流向 farm/sensor/temp 和 farm/sensor/humi 发送随机数据，\n"
                "可用它测试订阅者的通配符（如订阅 farm/+/temp 或 farm/#）。")).pack(
                anchor="w", pady=(4, 0))

            # 订阅者面板
            sb = ttk.LabelFrame(body, text="③ 订阅者面板（可添加多个）", padding=8)
            sb.grid(row=0, column=1, rowspan=2, sticky="nsew", pady=4)
            ra = ttk.Frame(sb); ra.pack(fill="x", pady=2)
            ttk.Label(ra, text="名称：").pack(side="left")
            self.var_sub_name = tk.StringVar(value="手机端")
            ttk.Entry(ra, textvariable=self.var_sub_name, width=10).pack(side="left", padx=3)
            ttk.Label(ra, text="订阅Topic：").pack(side="left")
            self.var_sub_topic = tk.StringVar(value="farm/+/temp")
            ttk.Entry(ra, textvariable=self.var_sub_topic, width=20,
                      font=("Consolas", 10)).pack(side="left", padx=3)
            ttk.Button(ra, text="➕ 添加订阅者", command=self.add_subscriber).pack(
                side="left", padx=4)
            self.sub_area = ttk.Frame(sb)
            self.sub_area.pack(fill="both", expand=True, pady=(6, 0))

            self.var_status = tk.StringVar(value=" 就绪：请先启动中转站。")
            ttk.Label(self.root, textvariable=self.var_status, relief="sunken",
                      anchor="w", padding=(8, 3)).pack(fill="x", side="bottom")

        # ---------------- 日志 ----------------
        def log(self, kind, text):
            ts = time.strftime("%H:%M:%S")
            self.records.append({"时间": ts, "类别": kind, "内容": text})
            self.txt_log.configure(state="normal")
            self.txt_log.insert("end", "[%s] %s\n" % (ts, text), kind)
            self.txt_log.see("end")
            self.txt_log.configure(state="disabled")

        # ---------------- 中转站 ----------------
        def start_broker(self):
            if self.broker and self.broker.running:
                return
            try:
                port = int(self.var_port.get())
            except (tk.TclError, ValueError):
                messagebox.showwarning("提示", "端口请输入 1024~65535 的整数。")
                return
            broker = BrokerServer(port, event_cb=self._broker_event)
            try:
                broker.start()
            except OSError as e:
                messagebox.showerror("启动失败",
                                     "端口 %d 无法使用（%s）。\n请换一个端口再试。" % (port, e))
                return
            self.broker = broker
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.sp_port.configure(state="disabled")
            self.var_status.set(" 中转站运行中：127.0.0.1:%d" % port)

        def stop_broker(self):
            self.auto_pub.set(False)
            for name in list(self.subs):
                self._remove_subscriber(name, quiet=True)
            self._close_pub_sock()
            if self.broker:
                self.broker.stop()
                self.broker = None
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self.sp_port.configure(state="normal")
            self.var_status.set(" 中转站已停止。")

        def _broker_event(self, kind, text):
            # 由 broker 线程调用，转入队列由主线程刷新界面
            self.gui_queue.put(("log", kind, text, ""))

        # ---------------- 发布者 ----------------
        def _ensure_pub_sock(self):
            if not (self.broker and self.broker.running):
                messagebox.showinfo("提示", "请先启动中转站。")
                return None
            if self.pub_sock is None:
                try:
                    self.pub_sock = socket.create_connection(
                        ("127.0.0.1", self.broker.port), timeout=3)
                    self.pub_sock.sendall("NAME|发布者\n".encode("utf-8"))
                except OSError as e:
                    messagebox.showerror("连接失败", "发布者无法连接中转站：%s" % e)
                    self.pub_sock = None
            return self.pub_sock

        def _close_pub_sock(self):
            if self.pub_sock is not None:
                try:
                    self.pub_sock.close()
                except OSError:
                    pass
                self.pub_sock = None

        def publish_once(self):
            topic = self.var_pub_topic.get().strip()
            payload = self.var_pub_payload.get().strip()
            if not topic or not payload:
                messagebox.showinfo("提示", "Topic 和内容都不能为空。")
                return
            if "|" in topic or "|" in payload:
                messagebox.showinfo("提示", "本教学协议用 | 作分隔符，Topic 与内容中请不要使用 | 字符。")
                return
            self._send_pub(topic, payload)

        def _send_pub(self, topic, payload):
            s = self._ensure_pub_sock()
            if s is None:
                return
            try:
                s.sendall(("PUB|%s|%s\n" % (topic, payload)).encode("utf-8"))
            except OSError:
                self._close_pub_sock()
                self.log("err", "发布失败：与中转站的连接已断开，请重试。")

        def toggle_auto(self):
            if self.auto_pub.get():
                if not (self.broker and self.broker.running):
                    messagebox.showinfo("提示", "请先启动中转站，再开启自动发布。")
                    self.auto_pub.set(False)
                    return
                self._auto_flip = False
                self._auto_tick()
                self.var_status.set(" 自动发布已开启：每2秒一条虚拟数据。")
            else:
                self.var_status.set(" 自动发布已关闭。")

        def _auto_tick(self):
            if not self.auto_pub.get():
                return
            if not (self.broker and self.broker.running):
                self.auto_pub.set(False)
                return
            self._auto_flip = not self._auto_flip
            if self._auto_flip:
                self._send_pub("farm/sensor/temp", "温度 %.1f℃" % random.uniform(18, 32))
            else:
                self._send_pub("farm/sensor/humi", "土壤湿度 %d%%" % random.randint(30, 75))
            self.root.after(2000, self._auto_tick)

        # ---------------- 订阅者 ----------------
        def add_subscriber(self):
            if not (self.broker and self.broker.running):
                messagebox.showinfo("提示", "请先启动中转站。")
                return
            name = self.var_sub_name.get().strip()
            pattern = self.var_sub_topic.get().strip()
            if not name or not pattern:
                messagebox.showinfo("提示", "名称与订阅 Topic 都不能为空。")
                return
            if name in self.subs:
                messagebox.showinfo("提示", "已存在同名订阅者「%s」，请换个名称。" % name)
                return
            if "|" in pattern or " " in pattern:
                messagebox.showinfo("提示", "Topic 模式中不要包含空格或 | 字符。")
                return
            try:
                client = SubscriberClient(name, pattern, self.broker.port, self.gui_queue)
            except OSError as e:
                messagebox.showerror("失败", "订阅者连接中转站失败：%s" % e)
                return
            frame = ttk.LabelFrame(self.sub_area,
                                   text="📥 %s   订阅：%s" % (name, pattern), padding=4)
            frame.pack(fill="both", expand=True, pady=3)
            txt = tk.Text(frame, height=5, state="disabled", bg="#f5f3ff",
                          font=("Microsoft YaHei", 9), wrap="word")
            txt.pack(side="left", fill="both", expand=True)
            btn = ttk.Button(frame, text="移除", width=5,
                             command=lambda n=name: self._remove_subscriber(n))
            btn.pack(side="right", padx=3)
            self.subs[name] = (client, txt, frame)
            self.var_status.set(" 已添加订阅者「%s」，订阅 %s" % (name, pattern))
            # 给下一个订阅者起个不重名的默认名字
            self.var_sub_name.set("订阅者%d" % (len(self.subs) + 1))

        def _remove_subscriber(self, name, quiet=False):
            item = self.subs.pop(name, None)
            if not item:
                return
            client, _txt, frame = item
            client.close()
            frame.destroy()
            if not quiet:
                self.var_status.set(" 已移除订阅者「%s」。" % name)

        # ---------------- 队列轮询（线程 → 主线程） ----------------
        def _poll_queue(self):
            try:
                while True:
                    kind, a, b, c = self.gui_queue.get_nowait()
                    if kind == "log":
                        self.log(a, b)
                    elif kind == "submsg":
                        item = self.subs.get(a)
                        if item:
                            _cl, txt, _fr = item
                            txt.configure(state="normal")
                            txt.insert("end", "[%s] %s ← %s\n"
                                       % (time.strftime("%H:%M:%S"), b, c))
                            txt.see("end")
                            txt.configure(state="disabled")
                            self.records.append({"时间": time.strftime("%H:%M:%S"),
                                                 "类别": "recv",
                                                 "内容": "%s 收到 [%s]「%s」" % (a, b, c)})
                    elif kind == "subdead":
                        pass  # 连接结束（停止中转站或移除时正常发生）
            except queue.Empty:
                pass
            self.root.after(80, self._poll_queue)

        # ---------------- 导出 / 其他 ----------------
        def export_json(self):
            if not self.records:
                messagebox.showinfo("提示", "日志为空，先做几次发布/订阅实验吧。")
                return
            path = filedialog.asksaveasfilename(
                title="导出日志", defaultextension=".json",
                initialfile="发布订阅实验日志.json",
                filetypes=[("JSON 文件", "*.json")])
            if not path:
                return
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"工具": "本地发布订阅通信模拟器",
                           "导出时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "日志": self.records}, f, ensure_ascii=False, indent=2)
            self.var_status.set(" 已导出 %d 条日志到 %s" % (len(self.records), path))

        def export_csv(self):
            if not self.records:
                messagebox.showinfo("提示", "日志为空，先做几次发布/订阅实验吧。")
                return
            path = filedialog.asksaveasfilename(
                title="导出日志", defaultextension=".csv",
                initialfile="发布订阅实验日志.csv",
                filetypes=[("CSV 文件", "*.csv")])
            if not path:
                return
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                wr = csv.DictWriter(f, fieldnames=["时间", "类别", "内容"])
                wr.writeheader()
                wr.writerows(self.records)
            self.var_status.set(" 已导出 %d 条日志到 %s" % (len(self.records), path))

        def clear_log(self):
            self.records.clear()
            self.txt_log.configure(state="normal")
            self.txt_log.delete("1.0", "end")
            self.txt_log.configure(state="disabled")
            self.var_status.set(" 日志已清空。")

        def show_help(self):
            win = tk.Toplevel(self.root)
            win.title("帮助 · 本地发布订阅通信模拟器")
            win.geometry("620x560")
            win.transient(self.root)
            txt = tk.Text(win, wrap="word", font=("Microsoft YaHei", 10),
                          padx=12, pady=10)
            txt.insert("1.0", HELP_TEXT)
            txt.configure(state="disabled")
            vsb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
            txt.configure(yscrollcommand=vsb.set)
            txt.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")

        def on_close(self):
            self.stop_broker()
            self.root.destroy()

    root = tk.Tk()
    App(root)
    root.mainloop()


# ======================================================================
#  第四部分：无 GUI 自测（python3 本程序.py --selftest）
# ======================================================================

def self_test():
    """验证 Topic 匹配与中转路由逻辑，全部通过返回 0，否则返回 1。不弹窗。"""
    failures = []

    def check(desc, cond):
        status = "通过" if cond else "失败"
        print("  [%s] %s" % (status, desc))
        if not cond:
            failures.append(desc)

    print("== 1. topic_matches 通配符匹配测试 ==")
    cases = [
        ("farm/sensor/temp", "farm/sensor/temp", True),
        ("farm/sensor/temp", "farm/sensor/humi", False),
        ("farm/+/temp",      "farm/green1/temp", True),
        ("farm/+/temp",      "farm/temp", False),                 # 少一层
        ("farm/+/temp",      "farm/green1/soil/temp", False),     # 多一层
        ("farm/#",           "farm/green1/sensor/temp", True),
        ("farm/#",           "home/room1/temp", False),
        ("#",                "任意/主题", True),
        ("+/+/sensor/humi",  "farm/green1/sensor/humi", True),
        ("+/+/sensor/humi",  "farm/green1/sensor/temp", False),
        ("farm/#/temp",      "farm/green1/temp", False),          # '#'不在末尾无效
        ("", "farm/temp", False),
        ("farm/sensor/temp", "", False),
    ]
    for pat, top, expect in cases:
        got = topic_matches(pat, top)
        check("匹配(%r, %r) 应为 %s，实际 %s" % (pat, top, expect, got), got == expect)

    print("== 2. BrokerCore 订阅登记与路由测试 ==")
    core = BrokerCore()
    core.subscribe(1, "farm/sensor/temp")       # 客户端1：精确订阅温度
    core.subscribe(2, "farm/+/humi")            # 客户端2：任意一层的湿度
    core.subscribe(3, "farm/#")                 # 客户端3：农植园全部
    core.subscribe(3, "home/room1/temp")        # 客户端3再订一个家里的
    check("temp 消息应送达客户端 1 和 3",
          core.route("farm/sensor/temp") == [1, 3])
    check("humi 消息应送达客户端 2 和 3",
          core.route("farm/sensor/humi") == [2, 3])
    check("home/room1/temp 只送达客户端 3",
          core.route("home/room1/temp") == [3])
    check("无人订阅的主题路由为空",
          core.route("school/gate/state") == [])
    core.unsubscribe(3, "farm/#")
    check("客户端3退订 farm/# 后，temp 消息只送达客户端 1",
          core.route("farm/sensor/temp") == [1])
    core.remove_client(1)
    check("移除客户端1后，temp 消息无人接收",
          core.route("farm/sensor/temp") == [])

    print("== 3. BrokerServer 端到端 socket 转发测试（127.0.0.1）==")
    events = []
    srv = BrokerServer(0, event_cb=lambda k, t: events.append((k, t)))
    # 端口 0 让系统自动分配空闲端口
    srv._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv._srv.bind(("127.0.0.1", 0))
    srv.port = srv._srv.getsockname()[1]
    srv._srv.listen(16)
    srv._running.set()
    t = threading.Thread(target=srv._accept_loop, daemon=True)
    t.start()
    try:
        sub = socket.create_connection(("127.0.0.1", srv.port), timeout=3)
        sub.sendall(b"NAME|test-sub\nSUB|farm/+/temp\n")
        time.sleep(0.3)
        pub = socket.create_connection(("127.0.0.1", srv.port), timeout=3)
        pub.sendall("NAME|test-pub\nPUB|farm/green1/temp|25.5\n".encode("utf-8"))
        sub.settimeout(3)
        data = sub.recv(4096).decode("utf-8")
        check("订阅者应收到 MSG|farm/green1/temp|25.5，实际收到 %r" % data,
              data.strip() == "MSG|farm/green1/temp|25.5")
        pub.sendall("PUB|farm/green1/soil/temp|no\n".encode("utf-8"))
        sub.settimeout(0.8)
        got_extra = None
        try:
            got_extra = sub.recv(4096)
        except socket.timeout:
            pass
        check("不匹配的主题（层数多一层）不应被转发", not got_extra)
        sub.close()
        pub.close()
    finally:
        srv.stop()
    print()
    if failures:
        print("自测结果：共 %d 项失败！" % len(failures))
        return 1
    print("自测结果：全部通过 ✓（Topic 匹配与转发逻辑正确）")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(self_test())
    run_gui()
