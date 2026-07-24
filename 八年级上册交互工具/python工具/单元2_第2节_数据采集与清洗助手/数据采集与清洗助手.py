# -*- coding: utf-8 -*-
"""
课时：清华大学出版社《信息科技》八年级上册 第2单元 第2节《数据的采集和整理》
工具：数据采集与清洗助手（Tkinter GUI，仅使用 Python 标准库 csv/json/statistics）
功能：
  1. 导入 CSV / JSON（文件对话框，自动检测 UTF-8 / GBK 编码并提示）；内置示例脏数据一键载入。
  2. ttk.Treeview 表格展示数据。
  3. 一键体检报告：每列缺失数、重复行数、可疑异常值（常识范围优先，
     无常识范围的数值列用四分位 IQR 法）、类型不一致（数值列里混入
     文字/单位）；问题行高亮标记并列出清单。
  4. 清洗操作：删除所选行、删除全部重复行、缺失值填充（平均值/中位数/固定值）、
     列重命名、类型转换（文本→数值，自动剥离“度/℃/%”等单位）。
  5. 每一步操作写入清洗日志（可导出 txt）。
  6. 处理前自动备份原始数据（内存副本，可另存原件，绝不覆盖原文件）。
  7. 导出清洗后的 CSV 与 JSON。
运行方法：python3 数据采集与清洗助手.py
说明：文件下半部分为 GUI；上半部分的检测/清洗核心函数不依赖 GUI，可被单独导入测试。
"""

import csv
import json
import statistics
from datetime import datetime

APP_TITLE = "数据采集与清洗助手 · 第2单元第2节《数据的采集和整理》"

# 常识合理范围（列名包含关键字时启用，配合 IQR 使用）
KNOWN_RANGES = {
    "气温": (-30.0, 50.0),
    "温度": (-30.0, 50.0),
    "湿度": (0.0, 100.0),
}

# 内置示例脏数据（与配套 HTML《校园气象观测》主题一致）
SAMPLE_HEADER = ["日期", "时间", "气温(℃)", "湿度(%)", "天气"]
SAMPLE_ROWS = [
    ["10-01", "08:00", "18.5", "62", "晴"],
    ["10-01", "14:00", "25度", "55", "晴"],
    ["10-01", "20:00", "16.0", "70", "多云"],
    ["10-02", "08:00", "", "68", "阴"],
    ["10-02", "14:00", "88", "40", "晴"],
    ["10-02", "20:00", "15.8", "72", "多云"],
    ["10-03", "08:00", "17.2", "65", "晴"],
    ["10-03", "08:00", "17.2", "65", "晴"],
    ["10-03", "14:00", "26.5℃", "52", "晴"],
    ["10-03", "20:00", "16.4", "", "多云"],
    ["10-04", "08:00", "12.1", "80", "小雨"],
    ["10-04", "14:00", "19.0", "75", "小雨"],
    ["10-04", "20:00", "-35", "82", "小雨"],
    ["10-05", "08:00", "14.6", "76", "阴"],
    ["10-05", "14:00", "21.3", "66", "多云"],
    ["10-05", "20:00", "15.0", "71", "多云"],
    ["10-06", "08:00", "13.9", "78", "阴"],
    ["10-06", "14:00", "20.8", "999", "阴"],
    ["10-06", "20:00", "14.7", "74", "阴"],
    ["10-04", "14:00", "19.0", "75", "小雨"],
    ["10-07", "08:00", "15.5度", "69", "晴"],
]


# ===================== 检测 / 清洗核心函数（无 GUI，可单独测试） =====================

def to_number(value):
    """尽量把单元格转成数字：剥离常见单位符号；失败返回 None。"""
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    for ch in ("℃", "度", "%", " "):
        s = s.replace(ch, "")
    try:
        return float(s)
    except ValueError:
        return None


def is_pure_number(value):
    """是否本来就是规范的纯数字文本（不含单位等杂质）。"""
    s = str(value).strip()
    if s == "":
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def column_is_numeric(rows, col, threshold=0.6):
    """若该列可转成数字的非空值比例超过阈值，视为数值列。"""
    ok = bad = 0
    for r in rows:
        if col >= len(r):
            continue
        s = str(r[col]).strip()
        if s == "":
            continue
        if to_number(s) is not None:
            ok += 1
        else:
            bad += 1
    total = ok + bad
    return total > 0 and ok / total >= threshold


def find_missing(rows, ncols):
    """返回 {列号: [行号,...]} 的缺失分布。"""
    miss = {}
    for ri, r in enumerate(rows):
        for ci in range(ncols):
            v = r[ci] if ci < len(r) else ""
            if str(v).strip() == "":
                miss.setdefault(ci, []).append(ri)
    return miss


def find_duplicates(rows):
    """返回重复行（与前面某行完全相同）的行号列表。"""
    seen = {}
    dups = []
    for ri, r in enumerate(rows):
        key = "\u0001".join(str(x).strip() for x in r)
        if key in seen:
            dups.append(ri)
        else:
            seen[key] = ri
    return dups


def known_range_for(col_name):
    for key, rng in KNOWN_RANGES.items():
        if key in str(col_name):
            return rng
    return None


def find_outliers(header, rows, col):
    """对数值列找可疑异常值，返回 [(行号, 数值), ...]。
    判定规则：列名有常识范围（气温/温度/湿度）时以常识范围为准；
    没有常识范围的数值列改用 IQR 四分位法（小样本时 IQR 容易误判，
    因此有权威范围时优先用范围）。"""
    known = known_range_for(header[col] if col < len(header) else "")
    lo_hi = None
    if known:
        lo_hi = known
    else:
        vals = []
        for r in rows:
            if col < len(r):
                n = to_number(r[col])
                if n is not None:
                    vals.append(n)
        if len(vals) >= 4:
            try:
                q1, _q2, q3 = statistics.quantiles(vals, n=4)
                iqr = q3 - q1
                lo_hi = (q1 - 1.5 * iqr, q3 + 1.5 * iqr)
            except statistics.StatisticsError:
                lo_hi = None
    if lo_hi is None:
        return []
    out = []
    for ri, r in enumerate(rows):
        if col >= len(r):
            continue
        n = to_number(r[col])
        if n is not None and (n < lo_hi[0] or n > lo_hi[1]):
            out.append((ri, n))
    return out


def find_type_issues(rows, col):
    """数值列中非空、可转数字但写法不规范（混单位）或完全转不成数字的格子。
    返回 [(行号, 原值, 说明), ...]。"""
    issues = []
    for ri, r in enumerate(rows):
        if col >= len(r):
            continue
        s = str(r[col]).strip()
        if s == "":
            continue
        if is_pure_number(s):
            continue
        n = to_number(s)
        if n is not None:
            issues.append((ri, s, "混入单位/符号，应写成 %s" % ("%g" % n)))
        else:
            issues.append((ri, s, "无法转换为数字"))
    return issues


def health_report(header, rows):
    """一键体检：返回结构化报告字典。"""
    ncols = len(header)
    miss = find_missing(rows, ncols)
    dups = find_duplicates(rows)
    numeric_cols = [c for c in range(ncols) if column_is_numeric(rows, c)]
    outliers = {c: find_outliers(header, rows, c) for c in numeric_cols}
    outliers = {c: v for c, v in outliers.items() if v}
    type_issues = {c: find_type_issues(rows, c) for c in numeric_cols}
    type_issues = {c: v for c, v in type_issues.items() if v}
    problem_rows = set()
    for lst in miss.values():
        problem_rows.update(lst)
    problem_rows.update(dups)
    for lst in outliers.values():
        problem_rows.update(ri for ri, _n in lst)
    for lst in type_issues.values():
        problem_rows.update(ri for ri, _s, _w in lst)
    total = (sum(len(v) for v in miss.values()) + len(dups)
             + sum(len(v) for v in outliers.values())
             + sum(len(v) for v in type_issues.values()))
    return {
        "missing": miss,             # {col: [row,...]}
        "duplicates": dups,          # [row,...]
        "outliers": outliers,        # {col: [(row, val),...]}
        "type_issues": type_issues,  # {col: [(row, raw, why),...]}
        "numeric_cols": numeric_cols,
        "problem_rows": sorted(problem_rows),
        "total_problems": total,
    }


def remove_duplicate_rows(rows):
    """返回 (新行列表, 删除数量)。保留第一份，删除后续重复。"""
    dups = set(find_duplicates(rows))
    kept = [r for ri, r in enumerate(rows) if ri not in dups]
    return kept, len(dups)


def fill_missing(rows, col, method="mean", fixed_value=""):
    """填充某列缺失值。method: mean / median / fixed。返回 (新行列表, 填充数量, 使用的值)。"""
    vals = [to_number(r[col]) for r in rows if col < len(r)]
    vals = [v for v in vals if v is not None]
    if method == "mean":
        use = round(statistics.fmean(vals), 2) if vals else 0
    elif method == "median":
        use = statistics.median(vals) if vals else 0
    else:
        use = fixed_value
    new_rows = []
    n = 0
    for r in rows:
        r2 = list(r)
        while len(r2) <= col:
            r2.append("")
        if str(r2[col]).strip() == "":
            r2[col] = str(use)
            n += 1
        new_rows.append(r2)
    return new_rows, n, use


def convert_column_numeric(rows, col):
    """文本→数值转换：剥离单位，规范为纯数字文本。返回 (新行列表, 成功数, 失败行号列表)。"""
    new_rows = []
    ok = 0
    failed = []
    for ri, r in enumerate(rows):
        r2 = list(r)
        if col < len(r2):
            s = str(r2[col]).strip()
            if s != "" and not is_pure_number(s):
                n = to_number(s)
                if n is not None:
                    r2[col] = ("%g" % n)
                    ok += 1
                else:
                    failed.append(ri)
        new_rows.append(r2)
    return new_rows, ok, failed


def read_table_auto(path):
    """读入 CSV 或 JSON，自动检测 UTF-8/GBK。返回 (header, rows, encoding, kind)。"""
    last_err = None
    for enc in ("utf-8-sig", "gbk"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                text = f.read()
            break
        except UnicodeDecodeError as e:
            last_err = e
            text = None
    if text is None:
        raise ValueError("无法识别文件编码（尝试了 UTF-8 与 GBK）：%s" % last_err)
    if path.lower().endswith(".json"):
        data = json.loads(text)
        if isinstance(data, dict):  # 兼容 {"header": [...], "rows": [...]}
            header = [str(x) for x in data.get("header", [])]
            rows = [[str(x) for x in r] for r in data.get("rows", [])]
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            header = list(data[0].keys())
            rows = [[str(item.get(k, "")) for k in header] for item in data]
        else:
            raise ValueError("JSON 结构不支持：需要对象列表或 {header, rows} 结构")
        return header, rows, enc, "json"
    reader = csv.reader(text.splitlines())
    all_rows = [row for row in reader if any(str(c).strip() for c in row)]
    if not all_rows:
        raise ValueError("文件为空")
    return all_rows[0], all_rows[1:], enc, "csv"


# ===================== GUI 部分 =====================

HELP_TEXT = """【数据采集与清洗助手 · 使用帮助】

推荐操作流程（对应教材"数据整理"环节）：
  1. 点"载入示例脏数据"（或 文件→导入 CSV/JSON，自动识别 UTF-8/GBK）。
     导入的同时程序会在内存中自动备份原始数据，绝不改动你的原文件；
     也可用"文件→另存原始数据副本"再存一份原件。
  2. 点"一键体检"：右侧生成体检报告——
     每列缺失数、重复行数、可疑异常值（常识范围优先，无范围列用
     四分位 IQR 法）、类型不一致（数值列里混入"度/℃"等单位）；
     问题行在表格中以颜色标记：
     黄=有缺失，紫=重复行，红=有异常值，橙=格式/类型问题。
  3. 逐类处理：
     · 删除所选行：先在表格中单击选中行（可多选），再点按钮；
     · 删除全部重复行：一键去重（保留第一份）；
     · 缺失值填充：选择列与方法（平均值/中位数/固定值）；
     · 类型转换：把"25度/26.5℃"等统一成纯数字；
     · 列重命名：让列名规范（如 " 气温 " → "气温(℃)"）。
  4. 每一步都写入下方"清洗日志"，可导出 txt 留作实验记录。
  5. 处理满意后：文件→导出清洗后 CSV / JSON。
  6. "恢复备份"可随时回到导入时的原始数据重新练习。

判断异常值的两把尺子：
  · 常识范围优先：列名含"气温/温度"按 -30~50℃，含"湿度"按 0~100%；
  · 没有常识范围的数值列用 IQR 四分位法：低于 Q1-1.5×IQR 或
    高于 Q3+1.5×IQR 的值可疑（小样本时可能误判，需人工复核）。
  异常值不一定是错的，但一定值得检查！

常见问题：
  Q: 导入提示编码无法识别？ A: 请把文件另存为 UTF-8 或 GBK 编码后重试。
  Q: 体检报告说某列不是数值列？ A: 该列多数值无法转成数字时按文本列处理，
     不参与异常值与类型检查。
"""


def now_str():
    return datetime.now().strftime("%H:%M:%S")


def main():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    class App:
        def __init__(self, root):
            self.root = root
            root.title(APP_TITLE)
            root.geometry("1080x700")
            root.minsize(900, 580)
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass
            style.configure("Treeview", rowheight=24)
            style.configure("TLabelframe.Label", font=("Microsoft YaHei", 10, "bold"))

            self.header = []
            self.rows = []
            self.backup = None      # (header, rows) 导入时的原始备份
            self.src_path = ""
            self.log_lines = []
            self.report = None

            self._build_menu()
            self._build_body()
            self.set_status("请先“载入示例脏数据”，或从菜单导入 CSV/JSON。")

        # ---------- 界面 ----------
        def _build_menu(self):
            m = tk.Menu(self.root)
            fm = tk.Menu(m, tearoff=0)
            fm.add_command(label="导入 CSV/JSON…", command=self.import_file)
            fm.add_command(label="载入示例脏数据", command=self.load_sample)
            fm.add_separator()
            fm.add_command(label="另存原始数据副本…", command=self.save_backup_copy)
            fm.add_command(label="导出清洗后 CSV…", command=self.export_csv)
            fm.add_command(label="导出清洗后 JSON…", command=self.export_json)
            fm.add_command(label="导出清洗日志…", command=self.export_log)
            fm.add_separator()
            fm.add_command(label="退出", command=self.root.destroy)
            m.add_cascade(label="文件", menu=fm)
            om = tk.Menu(m, tearoff=0)
            om.add_command(label="恢复备份（回到导入时）", command=self.restore_backup)
            m.add_cascade(label="操作", menu=om)
            hm = tk.Menu(m, tearoff=0)
            hm.add_command(label="使用帮助", command=self.show_help)
            m.add_cascade(label="帮助", menu=hm)
            self.root.config(menu=m)

        def _build_body(self):
            top = ttk.Frame(self.root)
            top.pack(fill="x", padx=8, pady=6)
            ttk.Button(top, text="载入示例脏数据", command=self.load_sample).pack(side="left")
            ttk.Button(top, text="导入 CSV/JSON…", command=self.import_file).pack(side="left", padx=4)
            ttk.Button(top, text="一键体检", command=self.do_report).pack(side="left", padx=(14, 4))
            ttk.Button(top, text="删除所选行", command=self.del_selected).pack(side="left", padx=4)
            ttk.Button(top, text="删除全部重复行", command=self.dedup).pack(side="left", padx=4)
            ttk.Button(top, text="恢复备份", command=self.restore_backup).pack(side="left", padx=(14, 4))
            ttk.Button(top, text="帮助", command=self.show_help).pack(side="right")

            ops = ttk.LabelFrame(self.root, text="清洗操作")
            ops.pack(fill="x", padx=8, pady=(0, 4))
            r1 = ttk.Frame(ops)
            r1.pack(fill="x", padx=6, pady=4)
            ttk.Label(r1, text="目标列:").pack(side="left")
            self.col_var = tk.StringVar()
            self.col_box = ttk.Combobox(r1, textvariable=self.col_var, width=12, state="readonly")
            self.col_box.pack(side="left", padx=4)
            ttk.Label(r1, text="缺失填充:").pack(side="left", padx=(12, 2))
            self.fill_var = tk.StringVar(value="平均值")
            ttk.Combobox(r1, textvariable=self.fill_var, width=8, state="readonly",
                         values=["平均值", "中位数", "固定值"]).pack(side="left")
            self.fixed_var = tk.StringVar()
            ttk.Entry(r1, textvariable=self.fixed_var, width=8).pack(side="left", padx=2)
            ttk.Button(r1, text="执行填充", command=self.do_fill).pack(side="left", padx=4)
            ttk.Button(r1, text="类型转换(文本→数值)", command=self.do_convert).pack(side="left", padx=(14, 4))
            ttk.Label(r1, text="列重命名为:").pack(side="left", padx=(14, 2))
            self.rename_var = tk.StringVar()
            ttk.Entry(r1, textvariable=self.rename_var, width=12).pack(side="left")
            ttk.Button(r1, text="重命名", command=self.do_rename).pack(side="left", padx=4)

            mid = ttk.Panedwindow(self.root, orient="horizontal")
            mid.pack(fill="both", expand=True, padx=8, pady=4)
            lf = ttk.LabelFrame(mid, text="数据表（问题行着色：黄=缺失 紫=重复 红=异常 橙=类型/格式）")
            self.tree = ttk.Treeview(lf, show="headings", selectmode="extended")
            ysb = ttk.Scrollbar(lf, orient="vertical", command=self.tree.yview)
            xsb = ttk.Scrollbar(lf, orient="horizontal", command=self.tree.xview)
            self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
            self.tree.grid(row=0, column=0, sticky="nsew")
            ysb.grid(row=0, column=1, sticky="ns")
            xsb.grid(row=1, column=0, sticky="ew")
            lf.rowconfigure(0, weight=1)
            lf.columnconfigure(0, weight=1)
            self.tree.tag_configure("miss", background="#fef08a")
            self.tree.tag_configure("dup", background="#ddd6fe")
            self.tree.tag_configure("out", background="#fecaca")
            self.tree.tag_configure("fmt", background="#fed7aa")
            mid.add(lf, weight=3)

            rf = ttk.LabelFrame(mid, text="体检报告")
            self.report_text = tk.Text(rf, width=42, font=("Microsoft YaHei", 9),
                                       state="disabled", bg="#eff6ff", wrap="word")
            self.report_text.pack(fill="both", expand=True, padx=4, pady=4)
            mid.add(rf, weight=2)

            bot = ttk.LabelFrame(self.root, text="清洗日志")
            bot.pack(fill="x", padx=8, pady=(0, 4))
            self.log_text = tk.Text(bot, height=6, font=("Consolas", 9), state="disabled", bg="#0f172a", fg="#93c5fd")
            self.log_text.pack(fill="x", padx=4, pady=4)

            self.status = tk.StringVar(value="就绪")
            ttk.Label(self.root, textvariable=self.status, relief="sunken", anchor="w",
                      padding=(8, 3)).pack(fill="x", side="bottom")

        def set_status(self, text):
            self.status.set(text)

        def log(self, text):
            line = "[%s] %s" % (now_str(), text)
            self.log_lines.append(line)
            self.log_text.config(state="normal")
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")

        # ---------- 数据载入 ----------
        def _after_load(self, source_desc):
            self.backup = ([*self.header], [list(r) for r in self.rows])
            self.report = None
            self.refresh_table()
            self.col_box["values"] = self.header
            if self.header:
                self.col_var.set(self.header[0])
            self.log("载入数据：%s（%d 行 × %d 列），已自动备份原始数据" %
                     (source_desc, len(self.rows), len(self.header)))
            self.set_status("数据已载入并自动备份。下一步：点击“一键体检”。")
            self._show_report_text("尚未体检。\n\n点击上方“一键体检”按钮，\n程序将检查：\n · 每列缺失值数量\n · 重复行\n · 可疑异常值（IQR 四分位法 + 常识范围）\n · 类型不一致（数值列里混入文字/单位）")

        def load_sample(self):
            self.header = [*SAMPLE_HEADER]
            self.rows = [list(r) for r in SAMPLE_ROWS]
            self.src_path = ""
            self._after_load("内置示例脏数据（校园气象观测）")

        def import_file(self):
            from tkinter import filedialog, messagebox
            path = filedialog.askopenfilename(
                title="导入 CSV/JSON",
                filetypes=[("CSV / JSON", "*.csv *.json"), ("所有文件", "*.*")])
            if not path:
                return
            try:
                header, rows, enc, kind = read_table_auto(path)
            except (ValueError, OSError, json.JSONDecodeError) as e:
                messagebox.showerror("导入失败", "无法读取文件：\n%s" % e)
                return
            self.header, self.rows = header, rows
            self.src_path = path
            self._after_load("%s（%s，编码 %s）" % (path.split("/")[-1], kind.upper(), enc.upper()))
            messagebox.showinfo("导入成功", "已导入 %d 行数据。\n检测到文件编码：%s\n"
                                "原始数据已在内存中自动备份，处理不会改动原文件。" % (len(rows), enc.upper()))

        # ---------- 表格显示 ----------
        def refresh_table(self):
            self.tree.delete(*self.tree.get_children())
            cols = ["#"] + self.header
            self.tree["columns"] = cols
            for c in cols:
                self.tree.heading(c, text=c)
                self.tree.column(c, width=60 if c == "#" else 110, anchor="center")
            tags_map = self._row_tags()
            for ri, r in enumerate(self.rows):
                vals = [ri + 1] + [("（空）" if str(v).strip() == "" else v) for v in r]
                self.tree.insert("", "end", iid=str(ri), values=vals, tags=tags_map.get(ri, ()))

        def _row_tags(self):
            tags = {}
            if not self.report:
                return tags
            rep = self.report
            for lst in rep["missing"].values():
                for ri in lst:
                    tags.setdefault(ri, []).append("miss")
            for ri in rep["duplicates"]:
                tags.setdefault(ri, []).append("dup")
            for lst in rep["outliers"].values():
                for ri, _v in lst:
                    tags.setdefault(ri, []).append("out")
            for lst in rep["type_issues"].values():
                for ri, _s, _w in lst:
                    tags.setdefault(ri, []).append("fmt")
            # Treeview 多 tag 时以第一个为准，问题按 异常>缺失>类型>重复 排优先级
            prio = {"out": 0, "miss": 1, "fmt": 2, "dup": 3}
            return {ri: (sorted(set(ts), key=lambda t: prio[t])[0],) for ri, ts in tags.items()}

        # ---------- 体检 ----------
        def do_report(self):
            from tkinter import messagebox
            if not self.rows:
                messagebox.showinfo("暂无数据", "请先载入示例数据或导入文件。")
                return
            rep = health_report(self.header, self.rows)
            self.report = rep
            self.refresh_table()
            lines = ["数据体检报告  %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     "共 %d 行 × %d 列" % (len(self.rows), len(self.header)), ""]
            lines.append("① 缺失值：共 %d 处" % sum(len(v) for v in rep["missing"].values()))
            for c, lst in sorted(rep["missing"].items()):
                lines.append("   · %s：%d 处（行 %s）" %
                             (self.header[c], len(lst), ", ".join(str(i + 1) for i in lst)))
            lines.append("② 重复行：%d 行" % len(rep["duplicates"]))
            if rep["duplicates"]:
                lines.append("   · 行 " + ", ".join(str(i + 1) for i in rep["duplicates"]) + "（与前面某行完全相同）")
            lines.append("③ 可疑异常值：共 %d 处（常识范围/IQR 法）" %
                         sum(len(v) for v in rep["outliers"].values()))
            for c, lst in sorted(rep["outliers"].items()):
                for ri, v in lst:
                    lines.append("   · 行 %d %s = %g（超出合理范围）" % (ri + 1, self.header[c], v))
            lines.append("④ 类型不一致：共 %d 处" % sum(len(v) for v in rep["type_issues"].values()))
            for c, lst in sorted(rep["type_issues"].items()):
                for ri, raw, why in lst:
                    lines.append("   · 行 %d %s =「%s」：%s" % (ri + 1, self.header[c], raw, why))
            lines.append("")
            n = rep["total_problems"]
            if n == 0:
                lines.append("★ 未发现问题：数据满足完整性、统一性、准确性，可以导出使用！")
            else:
                lines.append("共 %d 处问题，涉及 %d 行（表中已着色）。" % (n, len(rep["problem_rows"])))
                lines.append("建议顺序：类型转换 → 删除重复 → 处理异常 → 填充缺失。")
            self._show_report_text("\n".join(lines))
            self.log("一键体检：发现 %d 处问题" % n)
            self.set_status("体检完成：%d 处问题。%s" % (n, "干净数据，可导出！" if n == 0 else "请按报告逐类处理。"))

        def _show_report_text(self, text):
            self.report_text.config(state="normal")
            self.report_text.delete("1.0", "end")
            self.report_text.insert("1.0", text)
            self.report_text.config(state="disabled")

        # ---------- 清洗操作 ----------
        def _col_index(self):
            from tkinter import messagebox
            name = self.col_var.get()
            if name in self.header:
                return self.header.index(name)
            messagebox.showinfo("请选择列", "请先在“目标列”下拉框选择要处理的列。")
            return None

        def del_selected(self):
            from tkinter import messagebox
            sel = self.tree.selection()
            if not sel:
                messagebox.showinfo("未选中", "请先在表格中单击选中要删除的行（按住 Ctrl 可多选）。")
                return
            idxs = sorted((int(i) for i in sel), reverse=True)
            for i in idxs:
                if 0 <= i < len(self.rows):
                    self.rows.pop(i)
            self.report = None
            self.refresh_table()
            self.log("删除所选行：%s（共 %d 行）" % (", ".join(str(i + 1) for i in sorted(idxs)), len(idxs)))
            self.set_status("已删除 %d 行。建议重新“一键体检”查看效果。" % len(idxs))

        def dedup(self):
            new_rows, n = remove_duplicate_rows(self.rows)
            self.rows = new_rows
            self.report = None
            self.refresh_table()
            self.log("删除全部重复行：去掉 %d 行（保留第一份）" % n)
            self.set_status("去重完成，删除 %d 行。" % n if n else "没有发现重复行。")

        def do_fill(self):
            col = self._col_index()
            if col is None:
                return
            method_map = {"平均值": "mean", "中位数": "median", "固定值": "fixed"}
            method = method_map[self.fill_var.get()]
            self.rows, n, use = fill_missing(self.rows, col, method, self.fixed_var.get())
            self.report = None
            self.refresh_table()
            self.log("缺失填充：%s 列用%s（%s）填充 %d 处" % (self.header[col], self.fill_var.get(), use, n))
            self.set_status(("已填充 %d 处缺失。" % n) if n else "该列没有缺失值。")

        def do_convert(self):
            from tkinter import messagebox
            col = self._col_index()
            if col is None:
                return
            self.rows, ok, failed = convert_column_numeric(self.rows, col)
            self.report = None
            self.refresh_table()
            self.log("类型转换：%s 列 文本→数值，成功 %d 处，失败 %d 处" % (self.header[col], ok, len(failed)))
            if failed:
                messagebox.showwarning("部分无法转换",
                                       "行 %s 的值无法自动转换为数字，请手工检查（可删除该行或改用其他处理）。"
                                       % ", ".join(str(i + 1) for i in failed))
            self.set_status("类型转换完成：成功 %d 处。" % ok)

        def do_rename(self):
            from tkinter import messagebox
            col = self._col_index()
            if col is None:
                return
            new = self.rename_var.get().strip()
            if not new:
                messagebox.showinfo("请输入新列名", "请在输入框填写规范的新列名，如“气温(℃)”。")
                return
            old = self.header[col]
            self.header[col] = new
            self.col_box["values"] = self.header
            self.col_var.set(new)
            self.report = None
            self.refresh_table()
            self.log("列重命名：「%s」→「%s」" % (old, new))
            self.set_status("列已重命名。规范列名是数据“统一性”的一部分。")

        def restore_backup(self):
            from tkinter import messagebox
            if not self.backup:
                messagebox.showinfo("没有备份", "请先载入数据（载入时会自动备份）。")
                return
            self.header = [*self.backup[0]]
            self.rows = [list(r) for r in self.backup[1]]
            self.report = None
            self.refresh_table()
            self.col_box["values"] = self.header
            self.log("恢复备份：回到导入时的原始数据（%d 行）" % len(self.rows))
            self.set_status("已恢复原始数据，可重新练习清洗流程。")

        # ---------- 导出 ----------
        def save_backup_copy(self):
            from tkinter import filedialog, messagebox
            if not self.backup:
                messagebox.showinfo("没有备份", "请先载入数据。")
                return
            path = filedialog.asksaveasfilename(title="另存原始数据副本", defaultextension=".csv",
                                                initialfile="原始数据备份.csv",
                                                filetypes=[("CSV 文件", "*.csv")])
            if not path:
                return
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(self.backup[0])
                w.writerows(self.backup[1])
            self.log("另存原始数据副本：%s" % path)
            self.set_status("原始数据副本已保存（原文件不受影响）。")

        def export_csv(self):
            from tkinter import filedialog, messagebox
            if not self.rows:
                messagebox.showinfo("暂无数据", "请先载入并处理数据。")
                return
            path = filedialog.asksaveasfilename(title="导出清洗后 CSV", defaultextension=".csv",
                                                initialfile="清洗后数据.csv",
                                                filetypes=[("CSV 文件", "*.csv")])
            if not path:
                return
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(self.header)
                w.writerows(self.rows)
            self.log("导出清洗后 CSV：%s（%d 行）" % (path, len(self.rows)))
            self.set_status("CSV 已导出：%s" % path)

        def export_json(self):
            from tkinter import filedialog, messagebox
            if not self.rows:
                messagebox.showinfo("暂无数据", "请先载入并处理数据。")
                return
            path = filedialog.asksaveasfilename(title="导出清洗后 JSON", defaultextension=".json",
                                                initialfile="清洗后数据.json",
                                                filetypes=[("JSON 文件", "*.json")])
            if not path:
                return
            data = [dict(zip(self.header, r)) for r in self.rows]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.log("导出清洗后 JSON：%s（%d 条）" % (path, len(data)))
            self.set_status("JSON 已导出：%s" % path)

        def export_log(self):
            from tkinter import filedialog, messagebox
            if not self.log_lines:
                messagebox.showinfo("暂无日志", "还没有任何操作记录。")
                return
            path = filedialog.asksaveasfilename(title="导出清洗日志", defaultextension=".txt",
                                                initialfile="清洗日志.txt",
                                                filetypes=[("文本文件", "*.txt")])
            if not path:
                return
            with open(path, "w", encoding="utf-8") as f:
                f.write("数据采集与清洗助手 · 清洗日志\n")
                f.write("导出时间：%s\n\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                f.write("\n".join(self.log_lines))
            self.set_status("清洗日志已导出：%s" % path)

        def show_help(self):
            win = tk.Toplevel(self.root)
            win.title("使用帮助")
            win.geometry("660x600")
            t = tk.Text(win, font=("Microsoft YaHei", 10), wrap="word")
            t.pack(fill="both", expand=True, padx=8, pady=8)
            t.insert("1.0", HELP_TEXT)
            t.config(state="disabled")
            ttk.Button(win, text="关闭", command=win.destroy).pack(pady=(0, 8))

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
