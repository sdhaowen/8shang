# -*- coding: utf-8 -*-
"""
虚拟智能终端与GPIO实验器（第1单元 第2节《物联网的终端设备》配套工具）
======================================================================
功能简介：
  1. tkinter.Canvas 绘制一块虚拟开发板：OLED 显示区、按钮 A/B、LED×2、
     蜂鸣器图标、P0~P16 引脚条；
  2. 左侧“指令区”提供受限指令模板（按钮点击或手动输入）：
       oled.show("文字") / oled.clear() / led.on(1) / led.off(2) /
       buzzer.beep() / pin.mode("P0","IN") / pin.write("P8",1) / pin.read("P5")
     解析后驱动虚拟硬件状态变化；
  3. 引脚模式配置表、操作日志（带时间戳）；
  4. 实验记录可导出 CSV / JSON；可导入示例指令脚本（.txt）逐条执行；
  5. 帮助窗口内含完整指令手册。
运行方法：
  python3 虚拟智能终端与GPIO实验器.py
说明：
  全部使用 Python 标准库；蜂鸣器发声优先使用 winsound（仅 Windows），
  其他系统自动降级为状态栏提示 + 图标闪烁。不连接任何真实设备。
"""

import csv
import json
import re
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import winsound  # 仅 Windows 可用
    HAS_SOUND = True
except ImportError:
    HAS_SOUND = False

APP_TITLE = "虚拟智能终端与GPIO实验器 · 第1单元第2节《物联网的终端设备》"
PIN_NAMES = ["P%d" % i for i in range(17)]
ANALOG_PINS = {"P0", "P1", "P2"}          # 支持模拟输入的教学引脚
VALID_MODES = ["IN", "OUT", "ANALOG", "PWM"]


class GPIOLab:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("1200x780")
        root.minsize(1020, 660)

        # 虚拟硬件状态
        self.oled_text = ""
        self.led_state = {1: False, 2: False}
        self.pin_mode = {}                # {"P0": "IN", ...}
        self.pin_value = {p: 1 for p in PIN_NAMES}   # 数字默认高电平 1
        self.button_state = {"A": 1, "B": 1}         # 弹起=1 按下=0（对应 P5/P11）
        self.records = []                 # [(时间, 指令, 结果)]
        self.buzz_flash = 0

        self._build_ui()
        self._draw_board()
        self._log("虚拟开发板 vBoard-8 已就绪。点击左侧指令按钮，或输入指令后回车。")
        self._log("提示：先用 pin.mode() 设置引脚模式，再进行读写（教材表1.2.3/1.2.4）。")

    # ---------------- 界面 ----------------
    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TLabelframe.Label", font=("Microsoft YaHei", 10, "bold"))

        # 顶部操作条
        ops = ttk.Frame(self.root, padding=(10, 6))
        ops.pack(fill="x")
        ttk.Button(ops, text="↺ 重置开发板", command=self.reset).pack(side="left", padx=3)
        ttk.Button(ops, text="导入指令脚本", command=self.import_script).pack(side="left", padx=3)
        ttk.Button(ops, text="导出记录CSV", command=self.export_csv).pack(side="left", padx=3)
        ttk.Button(ops, text="导出记录JSON", command=self.export_json).pack(side="left", padx=3)
        ttk.Button(ops, text="帮助 / 指令手册", command=self.show_help).pack(side="left", padx=3)

        main = ttk.Frame(self.root, padding=(10, 2))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=0)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        # ---- 左侧：指令区 ----
        left = ttk.Frame(main)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 8))

        cmd_box = ttk.Labelframe(left, text="指令区（点击即执行）", padding=8)
        cmd_box.pack(fill="x")
        cmds = [
            ('oled.show("你好，物联网")', "OLED 显示文字"),
            ('oled.clear()', "清空 OLED"),
            ('led.on(1)', "点亮 LED1"),
            ('led.off(1)', "熄灭 LED1"),
            ('led.on(2)', "点亮 LED2"),
            ('led.off(2)', "熄灭 LED2"),
            ('buzzer.beep()', "蜂鸣器响一声"),
            ('pin.mode("P5","IN")', "P5 设为数字输入"),
            ('pin.mode("P8","OUT")', "P8 设为数字输出"),
            ('pin.mode("P0","ANALOG")', "P0 设为模拟输入"),
            ('pin.write("P8",1)', "P8 输出高电平"),
            ('pin.read("P5")', "读取 P5（按钮A）"),
            ('pin.read("P0")', "读取 P0 模拟值"),
        ]
        for c, tip in cmds:
            b = ttk.Button(cmd_box, text="%s   ← %s" % (c, tip), width=38,
                           command=lambda cc=c: self.run_command(cc))
            b.pack(fill="x", pady=1)

        entry_box = ttk.Labelframe(left, text="手动输入指令（回车执行）", padding=8)
        entry_box.pack(fill="x", pady=(8, 0))
        self.entry = ttk.Entry(entry_box, font=("Consolas", 11), width=36)
        self.entry.pack(fill="x")
        self.entry.bind("<Return>", lambda _e: self.run_command(self.entry.get()))
        ttk.Button(entry_box, text="▶ 执行", command=lambda: self.run_command(self.entry.get())).pack(pady=4)

        # 引脚模式配置表
        pin_box = ttk.Labelframe(left, text="引脚模式配置表", padding=4)
        pin_box.pack(fill="both", expand=True, pady=(8, 0))
        self.tree = ttk.Treeview(pin_box, columns=("mode", "val"), show="headings", height=8)
        self.tree.heading("mode", text="模式")
        self.tree.heading("val", text="当前值")
        self.tree.column("mode", width=130)
        self.tree.column("val", width=80, anchor="center")
        self.tree.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(pin_box, command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.config(yscrollcommand=sb.set)
        self._refresh_tree()

        # ---- 右侧：开发板 + 日志 ----
        right = ttk.Frame(main)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=3)
        right.rowconfigure(1, weight=2)
        right.columnconfigure(0, weight=1)

        board_box = ttk.Labelframe(right, text="虚拟开发板（按钮 A/B 可用鼠标按住模拟按下）", padding=4)
        board_box.grid(row=0, column=0, sticky="nsew")
        self.cv = tk.Canvas(board_box, bg="#0f172a", highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<Configure>", lambda _e: self._draw_board())
        self.cv.bind("<ButtonPress-1>", self._on_press)
        self.cv.bind("<ButtonRelease-1>", self._on_release)

        log_box = ttk.Labelframe(right, text="操作日志（实验记录）", padding=4)
        log_box.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.log = tk.Listbox(log_box, font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, side="left")
        sb2 = ttk.Scrollbar(log_box, command=self.log.yview)
        sb2.pack(side="right", fill="y")
        self.log.config(yscrollcommand=sb2.set)

        self.status = tk.Label(self.root, text="就绪。", anchor="w", bg="#dcfce7",
                               fg="#14532d", font=("Microsoft YaHei", 10), padx=10, pady=4)
        self.status.pack(fill="x", side="bottom")

    # ---------------- 画板 ----------------
    def _draw_board(self):
        cv = self.cv
        cv.delete("all")
        w = max(cv.winfo_width(), 640)
        h = max(cv.winfo_height(), 330)
        bx, by, bw, bh = 30, 16, w - 60, h - 60
        cv.create_rectangle(bx, by, bx + bw, by + bh, fill="#134e4a",
                            outline="#0f766e", width=3)
        cv.create_text(bx + bw / 2, by + 16, text="虚拟教学开发板 vBoard-8（教学示意，非真实产品）",
                       fill="#5eead4", font=("Microsoft YaHei", 10, "bold"))
        # OLED
        ox, oy, ow, oh = bx + bw * 0.28, by + 40, bw * 0.44, bh * 0.4
        cv.create_rectangle(ox, oy, ox + ow, oy + oh, fill="#020617", outline="#475569", width=3)
        cv.create_text(ox + ow / 2, oy + oh / 2,
                       text=self.oled_text if self.oled_text else "OLED 128×64",
                       fill="#4ade80" if self.oled_text else "#1e3a3a",
                       font=("Microsoft YaHei", 13, "bold"), width=ow - 16)
        # 按钮 A / B
        self._btnA = (bx + bw * 0.12, by + 40 + bh * 0.2, 26)
        self._btnB = (bx + bw * 0.88, by + 40 + bh * 0.2, 26)
        for name, (cxx, cyy, r) in (("A", self._btnA), ("B", self._btnB)):
            pressed = self.button_state[name] == 0
            cv.create_oval(cxx - r, cyy - r, cxx + r, cyy + r,
                           fill="#052e16" if pressed else "#1e293b",
                           outline="#22c55e" if pressed else "#64748b", width=3,
                           tags=("btn" + name,))
            cv.create_text(cxx, cyy, text=name, fill="#e2e8f0",
                           font=("Microsoft YaHei", 12, "bold"), tags=("btn" + name,))
            cv.create_text(cxx, cyy + r + 12, fill="#94a3b8", font=("Microsoft YaHei", 8),
                           text="按钮%s(P%s)=%d" % (name, "5" if name == "A" else "11",
                                                    self.button_state[name]))
        # LED ×2
        ly = by + bh * 0.66
        for i, lx in ((1, bx + bw * 0.32), (2, bx + bw * 0.44)):
            on = self.led_state[i]
            cv.create_oval(lx - 14, ly - 14, lx + 14, ly + 14,
                           fill="#facc15" if on else "#27272a",
                           outline="#fde047" if on else "#3f3f46", width=3)
            cv.create_text(lx, ly + 26, text="LED%d %s" % (i, "亮" if on else "灭"),
                           fill="#fde68a" if on else "#94a3b8", font=("Microsoft YaHei", 8))
        # 蜂鸣器
        bzx, bzy = bx + bw * 0.62, by + bh * 0.66
        color = "#f59e0b" if self.buzz_flash > 0 else "#111827"
        cv.create_oval(bzx - 18, bzy - 18, bzx + 18, bzy + 18, fill=color,
                       outline="#64748b", width=2)
        cv.create_oval(bzx - 5, bzy - 5, bzx + 5, bzy + 5, fill="#334155")
        cv.create_text(bzx, bzy + 30, text="蜂鸣器(P6)" + ("♪" if self.buzz_flash else ""),
                       fill="#fbbf24" if self.buzz_flash else "#94a3b8",
                       font=("Microsoft YaHei", 8))
        # 引脚条
        py0 = by + bh - 34
        cv.create_rectangle(bx + 20, py0, bx + bw - 20, py0 + 22, fill="#78350f",
                            outline="#b45309")
        n = len(PIN_NAMES)
        for i, p in enumerate(PIN_NAMES):
            px = bx + 32 + (bw - 64) * i / (n - 1)
            mode = self.pin_mode.get(p)
            fill = {"IN": "#22c55e", "OUT": "#facc15",
                    "ANALOG": "#38bdf8", "PWM": "#c084fc"}.get(mode, "#fbbf24")
            cv.create_rectangle(px - 5, py0 + 2, px + 5, py0 + 20, fill=fill, outline="")
            cv.create_text(px, py0 + 32, text=p, fill="#a16207", font=("Consolas", 7))
        cv.create_text(bx + bw / 2, py0 + 46,
                       text="引脚颜色：绿=IN 黄底=未配置 金黄=OUT 蓝=ANALOG 紫=PWM　（P0/P1/P2 支持模拟输入）",
                       fill="#475569", font=("Microsoft YaHei", 8))

    def _on_press(self, ev):
        for name, (cxx, cyy, r) in (("A", self._btnA), ("B", self._btnB)):
            if (ev.x - cxx) ** 2 + (ev.y - cyy) ** 2 <= (r + 4) ** 2:
                self.button_state[name] = 0
                self.pin_value["P5" if name == "A" else "P11"] = 0
                self._log("硬件事件：按钮%s 按下（数字输入变为 0）" % name)
                self._set_status("按钮%s 按下 → 对应引脚读数 0（低电平）" % name, True)
                self._draw_board()
                self._refresh_tree()

    def _on_release(self, _ev):
        changed = False
        for name in ("A", "B"):
            if self.button_state[name] == 0:
                self.button_state[name] = 1
                self.pin_value["P5" if name == "A" else "P11"] = 1
                self._log("硬件事件：按钮%s 弹起（数字输入恢复 1）" % name)
                changed = True
        if changed:
            self._set_status("按钮弹起 → 对应引脚读数恢复 1（高电平）", True)
            self._draw_board()
            self._refresh_tree()

    # ---------------- 指令解析 ----------------
    def run_command(self, cmd):
        cmd = (cmd or "").strip()
        if not cmd:
            self._set_status("指令为空：请输入或点击一条指令。", False)
            return
        result = self._execute(cmd)
        self.records.append((time.strftime("%Y-%m-%d %H:%M:%S"), cmd, result))
        self._draw_board()
        self._refresh_tree()

    def _execute(self, cmd):
        # oled.show("文字")
        m = re.fullmatch(r'oled\.show\(\s*"(.*)"\s*\)', cmd)
        if m:
            text = m.group(1)
            if len(text) > 24:
                return self._fail(cmd, "文字过长（%d 字符）。虚拟 OLED 最多显示 24 字符，请精简。" % len(text))
            self.oled_text = text
            return self._okay(cmd, "OLED 显示：%s" % text)
        if re.fullmatch(r'oled\.clear\(\s*\)', cmd):
            self.oled_text = ""
            return self._okay(cmd, "OLED 已清空")
        # led.on(n) / led.off(n)
        m = re.fullmatch(r'led\.(on|off)\(\s*(\d+)\s*\)', cmd)
        if m:
            act, num = m.group(1), int(m.group(2))
            if num not in (1, 2):
                return self._fail(cmd, "LED 编号 %d 不存在，本板只有 LED1 和 LED2。" % num)
            self.led_state[num] = (act == "on")
            return self._okay(cmd, "LED%d %s" % (num, "点亮" if act == "on" else "熄灭"))
        # buzzer.beep()
        if re.fullmatch(r'buzzer\.beep\(\s*\)', cmd):
            self._beep()
            return self._okay(cmd, "蜂鸣器发声一次" + ("" if HAS_SOUND else "（本系统无 winsound，以图标闪烁+状态提示代替）"))
        # pin.mode("P0","IN")
        m = re.fullmatch(r'pin\.mode\(\s*"(\w+)"\s*,\s*"(\w+)"\s*\)', cmd)
        if m:
            p, mode = m.group(1).upper(), m.group(2).upper()
            if p not in PIN_NAMES:
                return self._fail(cmd, "引脚 %s 不存在，本板引脚为 P0~P16。" % p)
            if mode not in VALID_MODES:
                return self._fail(cmd, "模式 %s 无效。四种模式：IN（数字输入）/OUT（数字输出）/ANALOG（模拟输入）/PWM（模拟输出）。" % mode)
            if mode == "ANALOG" and p not in ANALOG_PINS:
                return self._fail(cmd, "%s 不支持模拟输入，请改用 P0/P1/P2（不同引脚功能不同，要参照引脚说明）。" % p)
            self.pin_mode[p] = mode
            return self._okay(cmd, "%s 已设为 %s 模式" % (p, mode))
        # pin.write("P8",1)
        m = re.fullmatch(r'pin\.write\(\s*"(\w+)"\s*,\s*(\d+)\s*\)', cmd)
        if m:
            p, val = m.group(1).upper(), int(m.group(2))
            if p not in PIN_NAMES:
                return self._fail(cmd, "引脚 %s 不存在。" % p)
            mode = self.pin_mode.get(p)
            if mode is None:
                return self._fail(cmd, "%s 还未设置模式。先执行 pin.mode(\"%s\",\"OUT\") 再写入。" % (p, p))
            if mode == "IN":
                return self._fail(cmd, "%s 是输入模式，只能读不能写。接执行器要用 OUT（数字输出）模式。" % p)
            if mode == "ANALOG":
                return self._fail(cmd, "%s 是模拟输入模式，用于读取传感器数值，不能写入。" % p)
            if mode == "OUT" and val not in (0, 1):
                return self._fail(cmd, "数字输出只能写 0（低电平）或 1（高电平），%d 无效。想要中间值请用 PWM 模式。" % val)
            if mode == "PWM" and not (0 <= val <= 1023):
                return self._fail(cmd, "PWM 模拟输出范围 0~1023，%d 超出范围。" % val)
            self.pin_value[p] = val
            return self._okay(cmd, "%s（%s）写入 %d" % (p, mode, val))
        # pin.read("P5")
        m = re.fullmatch(r'pin\.read\(\s*"(\w+)"\s*\)', cmd)
        if m:
            p = m.group(1).upper()
            if p not in PIN_NAMES:
                return self._fail(cmd, "引脚 %s 不存在。" % p)
            mode = self.pin_mode.get(p)
            if mode is None:
                return self._fail(cmd, "%s 还未设置模式。先执行 pin.mode(\"%s\",\"IN\")（按钮）或 pin.mode(\"%s\",\"ANALOG\")（光敏）等。" % (p, p, p))
            if mode == "ANALOG":
                import random
                val = random.randint(0, 4095)
                self.pin_value[p] = val
                return self._okay(cmd, "%s 模拟读数 = %d（12 位精度 0~4095，模拟环境光变化）" % (p, val))
            if mode == "IN":
                val = self.pin_value.get(p, 1)
                extra = ""
                if p == "P5":
                    extra = "（按钮A：弹起=1，按下=0，可按住画板上的按钮再读）"
                elif p == "P11":
                    extra = "（按钮B：弹起=1，按下=0）"
                return self._okay(cmd, "%s 数字读数 = %d %s" % (p, val, extra))
            return self._fail(cmd, "%s 是 %s（输出）模式，不能读取。要读数据请设为 IN 或 ANALOG。" % (p, mode))
        return self._fail(cmd, "无法识别的指令。点「帮助 / 指令手册」查看全部合法指令格式。")

    def _okay(self, cmd, msg):
        self._log("执行 %s → %s" % (cmd, msg))
        self._set_status("✔ " + msg, True)
        self.entry.delete(0, "end")
        return "成功：" + msg

    def _fail(self, cmd, msg):
        self._log("错误 %s → %s" % (cmd, msg))
        self._set_status("✘ " + msg, False)
        return "失败：" + msg

    def _beep(self):
        self.buzz_flash = 3
        self._flash_buzzer()
        if HAS_SOUND:
            try:
                winsound.Beep(880, 180)
            except RuntimeError:
                pass

    def _flash_buzzer(self):
        if self.buzz_flash > 0:
            self.buzz_flash -= 1
            self._draw_board()
            self.root.after(160, self._flash_buzzer)
        else:
            self._draw_board()

    # ---------------- 表 / 日志 / 状态 ----------------
    def _refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for p in PIN_NAMES:
            mode = self.pin_mode.get(p, "未配置")
            val = self.pin_value.get(p, "-") if p in self.pin_mode else "-"
            self.tree.insert("", "end", text=p, values=(mode, val))
        # Treeview 用第一列显示引脚名
        self.tree.configure(show="tree headings")
        self.tree.heading("#0", text="引脚")
        self.tree.column("#0", width=60)

    def _log(self, msg):
        self.log.insert("end", "[%s] %s" % (time.strftime("%H:%M:%S"), msg))
        self.log.see("end")
        if self.log.size() > 500:
            self.log.delete(0, 100)

    def _set_status(self, text, ok=True):
        self.status.config(text=text, bg="#dcfce7" if ok else "#fee2e2",
                           fg="#14532d" if ok else "#991b1b")

    # ---------------- 导入 / 导出 / 重置 / 帮助 ----------------
    def import_script(self):
        path = filedialog.askopenfilename(
            title="导入指令脚本（每行一条指令，# 开头为注释）",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f
                         if ln.strip() and not ln.strip().startswith("#")]
        except (OSError, UnicodeDecodeError) as e:
            messagebox.showerror("导入失败", "无法读取脚本文件：%s" % e)
            return
        if not lines:
            messagebox.showinfo("导入脚本", "脚本中没有可执行指令。")
            return
        self._log("—— 开始执行脚本 %s（共 %d 条指令）——" % (path, len(lines)))
        self._run_script_step(lines, 0)

    def _run_script_step(self, lines, i):
        if i >= len(lines):
            self._log("—— 脚本执行完毕 ——")
            self._set_status("脚本执行完毕，共 %d 条指令。" % len(lines), True)
            return
        self.run_command(lines[i])
        self.root.after(700, lambda: self._run_script_step(lines, i + 1))

    def export_csv(self):
        if not self.records:
            messagebox.showinfo("导出", "还没有实验记录，先执行几条指令吧。")
            return
        path = filedialog.asksaveasfilename(
            title="导出实验记录", defaultextension=".csv",
            initialfile="GPIO实验记录.csv", filetypes=[("CSV 文件", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f)
            wr.writerow(["时间", "指令", "执行结果"])
            wr.writerows(self.records)
        messagebox.showinfo("导出", "成功导出 %d 条记录。" % len(self.records))

    def export_json(self):
        if not self.records:
            messagebox.showinfo("导出", "还没有实验记录，先执行几条指令吧。")
            return
        path = filedialog.asksaveasfilename(
            title="导出实验记录", defaultextension=".json",
            initialfile="GPIO实验记录.json", filetypes=[("JSON 文件", "*.json")])
        if not path:
            return
        data = {
            "工具": "虚拟智能终端与GPIO实验器",
            "导出时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "引脚模式": self.pin_mode,
            "记录": [{"时间": t, "指令": c, "结果": r} for t, c, r in self.records],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        messagebox.showinfo("导出", "成功导出 %d 条记录。" % len(self.records))

    def reset(self):
        self.oled_text = ""
        self.led_state = {1: False, 2: False}
        self.pin_mode.clear()
        self.pin_value = {p: 1 for p in PIN_NAMES}
        self.button_state = {"A": 1, "B": 1}
        self.records.clear()
        self.log.delete(0, "end")
        self._draw_board()
        self._refresh_tree()
        self._log("开发板已重置：OLED 清空、LED 熄灭、引脚模式清除、记录清零。")
        self._set_status("已重置。", True)

    def show_help(self):
        win = tk.Toplevel(self.root)
        win.title("帮助 · 指令手册")
        win.geometry("640x520")
        txt = tk.Text(win, wrap="char", font=("Microsoft YaHei", 10), padx=10, pady=8)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0",
                   "【指令手册】（对应教材第2节：智能终端的编程 / I/O 引脚）\n\n"
                   "一、OLED 显示屏\n"
                   '  oled.show("文字")     在虚拟 OLED 上显示文字（≤24 字符）\n'
                   "  oled.clear()          清空屏幕\n\n"
                   "二、LED 灯（执行器 · 输出设备）\n"
                   "  led.on(1) / led.on(2)   点亮 LED1 / LED2\n"
                   "  led.off(1) / led.off(2) 熄灭 LED1 / LED2\n\n"
                   "三、蜂鸣器（执行器）\n"
                   "  buzzer.beep()          发声一次（Windows 有蜂鸣声，其他系统图标闪烁）\n\n"
                   "四、I/O 引脚（核心！先设模式，再读写）\n"
                   '  pin.mode("P0","IN")      设置引脚模式，四种模式：\n'
                   "        IN=数字输入（接按钮等） OUT=数字输出（接LED等）\n"
                   "        ANALOG=模拟输入（接光敏等，仅 P0/P1/P2） PWM=模拟输出\n"
                   '  pin.write("P8",1)        向输出引脚写值：OUT 写 0/1，PWM 写 0~1023\n'
                   '  pin.read("P5")           读输入引脚：IN 返回 0/1，ANALOG 返回 0~4095\n\n'
                   "五、和真实开发板的对应关系\n"
                   "  本工具指令是 pinpong 库语法的教学简化版。真实代码如：\n"
                   "    button_a = Pin(Pin.P5, Pin.IN)\n"
                   "    val = button_a.read_digital()\n"
                   "  按钮 A 对应 P5、按钮 B 对应 P11、蜂鸣器对应 P6（与教材一致）。\n"
                   "  按钮默认读数 1（高电平），鼠标按住画板上的按钮时读数为 0。\n\n"
                   "六、建议实验\n"
                   "  1. 依次执行 pin.mode(\"P5\",\"IN\") → pin.read(\"P5\")，再按住按钮A重读一次，\n"
                   "     对比两次读数（完成教材表 1.2.5 数字输入实验）；\n"
                   "  2. 故意犯错：不设模式直接 pin.write(\"P8\",1)，观察错误提示；\n"
                   "  3. 把 P5 设为 OUT 再试 pin.read(\"P5\")，理解“输入/输出”的区别；\n"
                   "  4. 用「导入指令脚本」运行 示例指令脚本.txt，观察自动演示。\n")
        txt.config(state="disabled")
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=6)


def main():
    root = tk.Tk()
    GPIOLab(root)
    root.mainloop()


if __name__ == "__main__":
    main()
