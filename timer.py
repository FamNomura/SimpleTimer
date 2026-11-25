# SimpleTimer.py

import tkinter as tk
from tkinter import ttk
from tkinter import messagebox, simpledialog
import threading
import time
import winsound
import datetime
import re
import sys
import os
import math
import json
import subprocess

# ==========================================
# --- デバッグログ設定ブロック (DEBUG制御) ---
# 完成時は DEBUG = False にするか、このブロックごと無効化可能
# ==========================================
DEBUG = True

if DEBUG:
    import logging
    os.makedirs("log", exist_ok=True)
    log_filename = datetime.datetime.now().strftime("log/debug_log_%Y%m%d_%H%M%S.txt")
    logging.basicConfig(
        filename=log_filename,
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        encoding='utf-8'
    )

def debug_log(msg):
    if DEBUG:
        logging.debug(msg)
        print(f"DEBUG: {msg}")
# ==========================================

# 外部ライブラリのインポートチェック
try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    root = tk.Tk()
    root.withdraw()
    error_msg = f"起動に必要なライブラリが見つかりません。\n仮想環境(.venv)を有効化し、以下のコマンドを実行してください:\n\npip install pystray Pillow\n\nエラー詳細: {e}"
    debug_log(f"ImportError: {e}")
    messagebox.showerror("ライブラリ不足", error_msg)
    sys.exit(1)

MIN_OPACITY = 0.35
MAX_OPACITY = 1.00
OPACITY_STEP = 0.05


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def normalize_zen_digits(text):
    zen_to_han = str.maketrans({chr(0xFF10 + i): chr(0x30 + i) for i in range(10)})
    return text.translate(zen_to_han).replace("：", ":").strip()


def parse_time_str(time_str):
    cleaned = normalize_zen_digits(time_str)
    match_colon = re.match(r"^(\d{1,2}):(\d{1,2})$", cleaned)
    if match_colon:
        h, m = int(match_colon.group(1)), int(match_colon.group(2))
    else:
        match_digits = re.match(r"^(\d{3,4})$", cleaned)
        if match_digits:
            val = int(match_digits.group(1))
            h, m = val // 100, val % 100
        else:
            raise ValueError(f"時刻形式が正しくありません: '{time_str}'")
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"時刻の範囲(00:00〜23:59)を超えています: '{time_str}'")
    return h, m


def parse_before_min(val_str):
    cleaned = normalize_zen_digits(str(val_str))
    if not cleaned:
        return 0
    if not re.match(r"^\d+$", cleaned):
        raise ValueError(f"事前通知(分)は0以上の整数で入力してください: '{val_str}'")
    val = int(cleaned)
    if val > 720:
        raise ValueError(f"事前通知(分)は720分以内で指定してください: '{val_str}'")
    return val


def auto_format_time_entry(entry_widget):
    raw = entry_widget.get().strip()
    if not raw:
        return
    try:
        h, m = parse_time_str(raw)
        formatted = f"{h:02d}:{m:02d}"
        if raw != formatted:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, formatted)
    except ValueError:
        pass


class SimpleTimer:
    def __init__(self, root):
        debug_log("アプリケーション初期化開始")
        self.root = root
        self.root.title("SimpleTimer - スケジュール管理")

        self.icon_file = resource_path("timer.ico")
        if os.path.exists(self.icon_file):
            try:
                self.root.iconbitmap(default=self.icon_file)
            except Exception as e:
                debug_log(f"アイコン設定エラー: {e}")

        # ウィンドウサイズ管理用変数
        self.IDLE_MIN_W, self.IDLE_MIN_H = 420, 400
        self.RUN_MIN_W, self.RUN_MIN_H = 260, 210
        self.saved_idle_size = (470, 480)
        self.in_running_ui = False
        self.settings_dialog = None

        self.root.minsize(self.IDLE_MIN_W, self.IDLE_MIN_H)

        # 状態変数
        self.is_running = False
        self.is_alarming = False
        self.alarm_stop_id = None
        self.countdown_after_id = None
        self.opacity_save_after_id = None
        self.opacity_hud_after_id = None
        self.log_file = "timer_log.txt"

        # スケジュール管理用変数
        self.schedule_rows = []      # 待機画面の入力行ウィジェット群
        self.active_tasks = []       # 実行中のタスク辞書リスト
        self.current_task_idx = -1   # 現在進行中のタスクインデックス
        self.start_datetime = None
        self.target_datetime = None  # アラーム発動時刻
        self.event_datetime = None   # 本来の予定時刻
        self.current_before_min = 0
        self.task_name = ""

        # 設定とテンプレートのロード
        self.settings_file = "settings.json"
        self.templates_file = "templates.json"
        self.templates = {}

        self.settings = {
            "topmost": True,
            "theme": "Light",
            "sound_enabled": True,
            "sound_pattern": "ブザー(標準)",
            "toast_enabled": True,
            "opacity": 1.0,
            "pomo_work_min": 25,
            "pomo_break_min": 5,
            "default_before_min": 0,
            "last_template": ""
        }
        self._load_settings()
        self._load_templates()

        # ポモドーロ関連変数
        self.pomodoro_enabled = tk.BooleanVar(value=False)
        self.is_pomodoro = False
        self.pomo_phase = "IDLE"
        self.pomodoro_count = 0
        self.pomo_target_datetime = None

        # カラー定義
        self.COLOR_NORMAL = "#f0f0f0"
        self.COLOR_FG = "#000000"
        self.COLOR_WARN = "#FF6347"
        self.COLOR_SAFE_ICON = "#228B22"
        self.COLOR_WARN_ICON = "#DC143C"
        self.COLOR_IDLE_ICON = "#808080"

        self.tray_icon = None
        self.icon_thread = None
        self.is_quitting = False

        self._apply_base_settings()
        self._setup_structure()
        self._update_template_combo()
        self._load_initial_schedule()
        self._switch_ui_to_idle()
        self._center_window_initial()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close_window)
        self._init_tray_icon()
        self._apply_theme()
        debug_log("アプリケーション初期化完了")

    # --- データ保存・読み込み ---
    def _load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    self.settings.update(loaded)
                debug_log("設定ファイル読み込み完了")
            except Exception as e:
                debug_log(f"設定読み込みエラー: {e}")
        # 安全な範囲にクランプ
        try:
            op = float(self.settings.get("opacity", 1.0))
            self.settings["opacity"] = round(max(MIN_OPACITY, min(MAX_OPACITY, op)), 2)
        except Exception:
            self.settings["opacity"] = 1.0
        try:
            bm = int(self.settings.get("default_before_min", 0))
            self.settings["default_before_min"] = max(0, min(720, bm))
        except Exception:
            self.settings["default_before_min"] = 0

    def _write_settings_file(self):
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
            debug_log("設定ファイル保存完了")
        except Exception as e:
            debug_log(f"設定保存エラー: {e}")

    def save_settings(self):
        self._write_settings_file()
        self._apply_base_settings()
        self._apply_theme()

    def _load_templates(self):
        if os.path.exists(self.templates_file):
            try:
                with open(self.templates_file, "r", encoding="utf-8") as f:
                    self.templates = json.load(f)
                debug_log(f"テンプレート読み込み完了 ({len(self.templates)}件)")
            except Exception as e:
                debug_log(f"テンプレート読み込みエラー: {e}")
                self.templates = {}

        # 初回起動時用のサンプルテンプレート
        if not self.templates:
            self.templates = {
                "サンプル（通常日課）": [
                    {"time": "10:00", "before_min": 10, "task": "医師会へ外勤"},
                    {"time": "12:15", "before_min": 0, "task": "昼休み"},
                    {"time": "16:25", "before_min": 5, "task": "退勤前チェック開始"}
                ]
            }
            self.save_templates()

    def save_templates(self):
        try:
            with open(self.templates_file, "w", encoding="utf-8") as f:
                json.dump(self.templates, f, ensure_ascii=False, indent=2)
            debug_log("テンプレート保存完了")
        except Exception as e:
            debug_log(f"テンプレート保存エラー: {e}")

    def _load_initial_schedule(self):
        """起動時に選択されているテンプレートを予定欄へ反映する"""
        selected = self.combo_template.get()
        if selected and selected in self.templates:
            self._load_selected_template(save_last=False)
        else:
            self._add_schedule_row("", None, "")
        debug_log(f"初期スケジュール反映完了: テンプレート='{selected}'")

    # --- Windowsトースト通知 ---
    def _send_toast_notification(self, title, message):
        if not self.settings.get("toast_enabled", True):
            return
        debug_log(f"トースト通知送信: {title} - {message}")

        def _run_ps():
            try:
                safe_title = title.replace("'", "''").replace('"', '""')
                safe_msg = message.replace("'", "''").replace('"', '""')
                ps_script = f"""
                [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
                $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
                $textNodes = $template.GetElementsByTagName("text")
                $textNodes.Item(0).AppendChild($template.CreateTextNode('{safe_title}')) > $null
                $textNodes.Item(1).AppendChild($template.CreateTextNode('{safe_msg}')) > $null
                $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
                $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("SimpleTimer")
                $notifier.Show($toast)
                """
                creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], creationflags=creationflags)
            except Exception as e:
                debug_log(f"トースト通知エラー: {e}")

        threading.Thread(target=_run_ps, daemon=True).start()

    # --- UI初期化・テーマ適用 ---
    def _apply_base_settings(self):
        self.root.attributes("-topmost", self.settings["topmost"])
        if not self.is_running or self.is_alarming:
            self.root.attributes("-alpha", 1.0)
        else:
            self.root.attributes("-alpha", self.settings["opacity"])

    def _apply_theme(self):
        is_dark = (self.settings["theme"] == "Dark")
        self.COLOR_NORMAL = "#2b2b2b" if is_dark else "#f0f0f0"
        self.COLOR_FG = "#ffffff" if is_dark else "#000000"
        input_bg = "#3c3f41" if is_dark else "#ffffff"
        btn_bg = "#4a4d50" if is_dark else "#e1e1e1"

        self.root.config(bg=self.COLOR_NORMAL)

        def _apply_recursive(w):
            try:
                if getattr(w, "_keep_custom_color", False):
                    return
                if w in (getattr(self, 'canvas_bar', None), getattr(self, 'canvas_pomo_bar', None)):
                    return

                w_type = w.winfo_class()
                if w_type in ("Frame", "Labelframe", "Toplevel", "Canvas"):
                    w.config(bg=self.COLOR_NORMAL)
                if isinstance(w, (tk.Label, tk.Checkbutton, tk.Radiobutton, tk.LabelFrame)):
                    w.config(bg=self.COLOR_NORMAL, fg=self.COLOR_FG)
                    if isinstance(w, (tk.Checkbutton, tk.Radiobutton)):
                        w.config(selectcolor=input_bg, activebackground=self.COLOR_NORMAL, activeforeground=self.COLOR_FG)
                elif isinstance(w, tk.Entry):
                    w.config(bg=input_bg, fg=self.COLOR_FG, insertbackground=self.COLOR_FG)
                elif isinstance(w, tk.Button):
                    w.config(bg=btn_bg, fg=self.COLOR_FG, activebackground=input_bg, activeforeground=self.COLOR_FG)
            except Exception:
                pass
            for c in w.winfo_children():
                _apply_recursive(c)

        _apply_recursive(self.root)
        if self.is_running:
            self._refresh_running_task_list()

    def _center_window_initial(self):
        self.root.update_idletasks()
        width, height = self.saved_idle_size
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{width}x{height}+{(sw//2)-(width//2)}+{(sh//2)-(height//2)}")

    def _setup_structure(self):
        # 右クリックメニュー
        self.context_menu = tk.Menu(self.root, tearoff=0, font=("Meiryo UI", 9))
        self.context_menu.add_command(label="⚙ 設定を開く", command=self._open_settings)
        self.root.bind("<Button-3>", self._on_right_click)

        # 待機画面用フレーム
        self.idle_frame = tk.Frame(self.root, padx=10, pady=6)

        # ルーティン（テンプレート）操作行
        tpl_frame = tk.LabelFrame(self.idle_frame, text="今日のルーティン（テンプレート）", font=("Meiryo UI", 9), padx=8, pady=5)
        tpl_frame.pack(fill="x", pady=(0, 8))

        self.combo_template = ttk.Combobox(tpl_frame, state="readonly", font=("Meiryo UI", 9))
        self.combo_template.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.combo_template.bind("<<ComboboxSelected>>", self._on_template_selected)

        tk.Button(tpl_frame, text="読込", font=("Meiryo UI", 8), command=self._load_selected_template, width=5).pack(side="left", padx=2)
        tk.Button(tpl_frame, text="現在の予定を保存", font=("Meiryo UI", 8), command=self._save_current_as_template).pack(side="left", padx=2)
        tk.Button(tpl_frame, text="削除", font=("Meiryo UI", 8), command=self._delete_selected_template, width=4).pack(side="left", padx=2)

        # スケジュール入力ヘッダー
        list_header = tk.Frame(self.idle_frame)
        list_header.pack(fill="x", pady=(0, 2))
        tk.Label(list_header, text="予定時刻", font=("Meiryo UI", 9, "bold"), width=9, anchor="w").pack(side="left", padx=(6, 0))
        tk.Label(list_header, text="事前(分)", font=("Meiryo UI", 9, "bold"), width=8, anchor="center").pack(side="left", padx=(2, 4))
        tk.Label(list_header, text="予定・用件", font=("Meiryo UI", 9, "bold"), anchor="w").pack(side="left", padx=2)
        tk.Button(list_header, text="⚙ 設定", font=("Meiryo UI", 8), command=self._open_settings, padx=6).pack(side="right", padx=(4, 0))
        tk.Button(list_header, text="全クリア", font=("Meiryo UI", 8), command=self._clear_all_rows, padx=6).pack(side="right")

        # スクロール可能な予定入力エリア
        list_container = tk.Frame(self.idle_frame, bd=1, relief="sunken")
        list_container.pack(fill="both", expand=True, pady=2)

        self.canvas_sched = tk.Canvas(list_container, highlightthickness=0, height=180)
        self.scrollbar_sched = ttk.Scrollbar(list_container, orient="vertical", command=self.canvas_sched.yview)
        self.rows_frame = tk.Frame(self.canvas_sched)

        self.rows_frame.bind(
            "<Configure>",
            lambda e: self.canvas_sched.configure(scrollregion=self.canvas_sched.bbox("all"))
        )
        self.canvas_window = self.canvas_sched.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.canvas_sched.bind(
            "<Configure>",
            lambda e: self.canvas_sched.itemconfig(self.canvas_window, width=e.width)
        )
        self.canvas_sched.configure(yscrollcommand=self.scrollbar_sched.set)

        self.canvas_sched.pack(side="left", fill="both", expand=True)
        self.scrollbar_sched.pack(side="right", fill="y")

        # マウスホイール対応（リストスクロール＋実行中の透過度変更）
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)

        # 追加ボタン・オプション行
        ctrl_frame = tk.Frame(self.idle_frame)
        ctrl_frame.pack(fill="x", pady=6)

        btn_add = tk.Button(ctrl_frame, text="＋ 予定を追加", command=lambda: self._add_schedule_row(), font=("Meiryo UI", 9, "bold"), padx=10, pady=2)
        btn_add.pack(side="left")

        self.chk_pomodoro = tk.Checkbutton(ctrl_frame, text="ポモドーロ併用", variable=self.pomodoro_enabled, font=("Meiryo UI", 9))
        self.chk_pomodoro.pack(side="right")

        # 開始ボタン
        self.btn_start = tk.Button(
            self.idle_frame, text="スケジュール開始", command=self.start_timer,
            bg="#2E7D32", fg="white", font=("Meiryo UI", 12, "bold"), pady=6
        )
        self.btn_start._keep_custom_color = True
        self.btn_start.pack(fill="x", pady=(4, 5))

        # 実行画面・動的操作用フレーム
        self.dynamic_frame = tk.Frame(self.root, padx=8, pady=6)

    def _on_right_click(self, event):
        if isinstance(event.widget, tk.Entry):
            return
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _is_widget_descendant(self, widget, ancestor):
        if widget is None or ancestor is None:
            return False
        w = widget
        while w is not None:
            if w == ancestor:
                return True
            w = getattr(w, "master", None)
        return False

    def _on_mousewheel(self, event):
        # サブダイアログ（設定・予定編集）が開いている間は無視
        top = event.widget.winfo_toplevel()
        if top != self.root:
            return

        if not self.is_running:
            if hasattr(self, "canvas_sched") and self.canvas_sched.winfo_exists():
                self.canvas_sched.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return

        if self.is_alarming:
            return

        # 実行中：Ctrl+ホイール または 上部の「現在の予定」エリア上でのホイールで透過度変更
        is_ctrl = bool(event.state & 0x0004)
        in_current_box = (
            hasattr(self, "current_box")
            and self.current_box.winfo_exists()
            and self._is_widget_descendant(event.widget, self.current_box)
        )
        if is_ctrl or in_current_box:
            step = OPACITY_STEP if event.delta > 0 else -OPACITY_STEP
            self._adjust_opacity_by_wheel(step)
            return

        # それ以外のエリア（本日の予定一覧）はスクロール
        if hasattr(self, "canvas_run_tasks") and self.canvas_run_tasks.winfo_exists():
            self.canvas_run_tasks.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _adjust_opacity_by_wheel(self, delta):
        cur = float(self.settings.get("opacity", 1.0))
        new_val = round(max(MIN_OPACITY, min(MAX_OPACITY, cur + delta)), 2)
        if new_val != cur:
            self.settings["opacity"] = new_val
            self.root.attributes("-alpha", new_val)
            debug_log(f"ホイールによる透過度変更: {int(round(new_val * 100))}%")
            if self.opacity_save_after_id:
                self.root.after_cancel(self.opacity_save_after_id)
            self.opacity_save_after_id = self.root.after(500, self._write_settings_file)
        self._show_opacity_hud(new_val)

    def _show_opacity_hud(self, val):
        if not hasattr(self, "lbl_opacity_hud") or not self.lbl_opacity_hud.winfo_exists():
            return
        pct = int(round(val * 100))
        limit_note = " (下限)" if val <= MIN_OPACITY else ""
        self.lbl_opacity_hud.config(text=f"透過度: {pct}%{limit_note}")
        self.lbl_opacity_hud.place(relx=1.0, rely=0.0, anchor="ne", x=-2, y=-2)
        if self.opacity_hud_after_id:
            self.root.after_cancel(self.opacity_hud_after_id)
        self.opacity_hud_after_id = self.root.after(1500, self._hide_opacity_hud)

    def _hide_opacity_hud(self):
        self.opacity_hud_after_id = None
        if hasattr(self, "lbl_opacity_hud") and self.lbl_opacity_hud.winfo_exists():
            self.lbl_opacity_hud.place_forget()

    # --- 予定入力行の追加・削除・テンプレート操作 ---
    def _add_schedule_row(self, time_val="", before_min=None, task_val=""):
        row_frame = tk.Frame(self.rows_frame, pady=3, padx=4)
        row_frame.pack(fill="x")

        ent_time = tk.Entry(row_frame, width=8, font=("BIZ UDゴシック", 11), justify="center")
        ent_time.pack(side="left", padx=(0, 4))
        if not time_val:
            default_t = (datetime.datetime.now() + datetime.timedelta(minutes=30)).strftime("%H:%M")
            ent_time.insert(0, default_t)
        else:
            ent_time.insert(0, time_val)
        ent_time.bind("<FocusOut>", lambda e, w=ent_time: auto_format_time_entry(w))

        ent_before = tk.Entry(row_frame, width=4, font=("BIZ UDゴシック", 11), justify="center")
        ent_before.pack(side="left", padx=(2, 1))
        bm_val = self.settings.get("default_before_min", 0) if before_min is None else before_min
        ent_before.insert(0, str(bm_val))

        lbl_min = tk.Label(row_frame, text="分前", font=("Meiryo UI", 8))
        lbl_min.pack(side="left", padx=(0, 6))

        ent_task = tk.Entry(row_frame, font=("Meiryo UI", 10))
        ent_task.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ent_task.insert(0, task_val)

        row_data = {"frame": row_frame, "time": ent_time, "before": ent_before, "task": ent_task}

        btn_del = tk.Button(row_frame, text="✕", font=("Meiryo UI", 8), width=3,
                            command=lambda r=row_data: self._remove_schedule_row(r))
        btn_del.pack(side="right")

        self.schedule_rows.append(row_data)
        self._apply_theme()
        debug_log(f"予定行を追加: time='{time_val}', before={bm_val}, task='{task_val}' (計{len(self.schedule_rows)}行)")

    def _remove_schedule_row(self, row_data):
        if len(self.schedule_rows) <= 1:
            row_data["time"].delete(0, tk.END)
            row_data["before"].delete(0, tk.END)
            row_data["before"].insert(0, str(self.settings.get("default_before_min", 0)))
            row_data["task"].delete(0, tk.END)
            return
        row_data["frame"].destroy()
        self.schedule_rows.remove(row_data)
        debug_log(f"予定行を削除 (残り{len(self.schedule_rows)}行)")

    def _clear_all_rows(self):
        for r in self.schedule_rows:
            r["frame"].destroy()
        self.schedule_rows.clear()
        self._add_schedule_row("", None, "")
        debug_log("すべての予定行をクリア")

    def _sync_idle_rows_from_active_tasks(self):
        """実行中の予定追加・変更内容を待機画面の入力行へ同期する"""
        for r in self.schedule_rows:
            r["frame"].destroy()
        self.schedule_rows.clear()
        for item in self.active_tasks:
            t_str = item["event_dt"].strftime("%H:%M")
            self._add_schedule_row(t_str, item.get("before_min", 0), item["task"])
        if not self.schedule_rows:
            self._add_schedule_row("", None, "")

    def _update_template_combo(self):
        names = list(self.templates.keys())
        self.combo_template["values"] = names
        last_tpl = self.settings.get("last_template", "")
        if last_tpl and last_tpl in names:
            self.combo_template.set(last_tpl)
        elif names:
            self.combo_template.current(0)
        else:
            self.combo_template.set("")

    def _on_template_selected(self, event=None):
        self._load_selected_template(save_last=True)

    def _load_selected_template(self, save_last=True):
        name = self.combo_template.get()
        if not name or name not in self.templates:
            return
        items = self.templates[name]
        for r in self.schedule_rows:
            r["frame"].destroy()
        self.schedule_rows.clear()

        for item in items:
            # 既存テンプレートに before_min がない場合は 0 として互換読み込み
            bm = item.get("before_min", 0)
            self._add_schedule_row(item.get("time", ""), bm, item.get("task", ""))
        if not self.schedule_rows:
            self._add_schedule_row("", None, "")

        if save_last and self.settings.get("last_template") != name:
            self.settings["last_template"] = name
            self.save_settings()
        debug_log(f"テンプレート読込: '{name}' ({len(items)}件)")

    def _save_current_as_template(self):
        items = []
        try:
            for r in self.schedule_rows:
                auto_format_time_entry(r["time"])
                t_str = r["time"].get().strip()
                task_str = r["task"].get().strip()
                if t_str or task_str:
                    bm = parse_before_min(r["before"].get())
                    items.append({"time": t_str, "before_min": bm, "task": task_str or "予定"})
        except ValueError as e:
            messagebox.showerror("入力エラー", str(e), parent=self.root)
            return

        if not items:
            messagebox.showwarning("確認", "保存する予定が入力されていません。", parent=self.root)
            return

        initial_name = self.combo_template.get() or "平日ルーティン"
        name = simpledialog.askstring("テンプレート保存", "ルーティン名を入力してください:", initialvalue=initial_name, parent=self.root)
        if not name or not name.strip():
            return
        name = name.strip()
        self.templates[name] = items
        self.save_templates()
        self.settings["last_template"] = name
        self.save_settings()
        self._update_template_combo()
        self.combo_template.set(name)
        messagebox.showinfo("保存完了", f"ルーティン「{name}」を保存しました。", parent=self.root)

    def _delete_selected_template(self):
        name = self.combo_template.get()
        if not name or name not in self.templates:
            return
        if messagebox.askyesno("確認", f"ルーティン「{name}」を削除しますか？", parent=self.root):
            del self.templates[name]
            self.save_templates()
            self._update_template_combo()
            new_sel = self.combo_template.get()
            self.settings["last_template"] = new_sel
            self.save_settings()
            if new_sel:
                self._load_selected_template(save_last=False)
            else:
                self._clear_all_rows()

    # --- UI画面切り替え ---
    def _clear_dynamic_area(self):
        for widget in self.dynamic_frame.winfo_children():
            widget.destroy()

    def _cancel_countdown_loop(self):
        if self.countdown_after_id:
            try:
                self.root.after_cancel(self.countdown_after_id)
            except Exception:
                pass
            self.countdown_after_id = None

    def _switch_ui_to_idle(self):
        debug_log("UIを待機画面(IDLE)へ切り替え")
        self._cancel_countdown_loop()
        self._clear_dynamic_area()
        self.dynamic_frame.pack_forget()
        self.idle_frame.pack(fill="both", expand=True)

        self.root.minsize(self.IDLE_MIN_W, self.IDLE_MIN_H)
        if self.in_running_ui:
            self.in_running_ui = False
            w, h = self.saved_idle_size
            self.root.geometry(f"{w}x{h}")
            debug_log(f"待機画面サイズへ復元: {w}x{h}")

        if self.tray_icon:
            self.tray_icon.icon = self._get_idle_icon_image()
            self.tray_icon.title = "SimpleTimer - 待機中"
            self._update_tray_menu()

        self._apply_base_settings()
        self._apply_theme()

    def _switch_ui_to_running(self):
        debug_log(f"UIを実行画面(RUNNING)へ切り替え: 現在のタスク='{self.task_name}'")

        if not self.in_running_ui:
            self.root.update_idletasks()
            cur_w = self.root.winfo_width()
            cur_h = self.root.winfo_height()
            if cur_w >= self.IDLE_MIN_W and cur_h >= self.IDLE_MIN_H:
                self.saved_idle_size = (cur_w, cur_h)
            self.in_running_ui = True
            self.root.minsize(self.RUN_MIN_W, self.RUN_MIN_H)
            compact_w = 360
            compact_h = 430 if self.is_pomodoro else 370
            self.root.geometry(f"{compact_w}x{compact_h}")
            debug_log(f"実行画面へ自動コンパクト化: {compact_w}x{compact_h} (最小制限: {self.RUN_MIN_W}x{self.RUN_MIN_H})")

        self._clear_dynamic_area()
        self.idle_frame.pack_forget()
        self.dynamic_frame.pack(fill="both", expand=True)

        # --- 現在進行中のメインタイマー表示エリア ---
        self.current_box = tk.LabelFrame(self.dynamic_frame, text="現在の予定（ホイールで透過度変更）", font=("Meiryo UI", 8, "bold"), padx=8, pady=4)
        self.current_box.pack(fill="x", pady=(0, 6))

        # 透過度変更時のオーバーレイ表示用ラベル
        self.lbl_opacity_hud = tk.Label(
            self.current_box, text="", font=("Meiryo UI", 8, "bold"),
            bg="#263238", fg="#FFFFFF", padx=6, pady=1
        )
        self.lbl_opacity_hud._keep_custom_color = True

        # 用件ラベル
        self.lbl_current_task = tk.Label(self.current_box, text=self.task_name, font=("Meiryo UI", 13, "bold"), wraplength=310)
        self.lbl_current_task.pack(pady=(2, 2))
        self.current_box.bind(
            "<Configure>",
            lambda e: self.lbl_current_task.config(wraplength=max(180, e.width - 24)) if self.lbl_current_task.winfo_exists() else None
        )

        # 予定時刻・アラーム時刻の明示ラベル
        event_str = self.event_datetime.strftime("%H:%M")
        alarm_str = self.target_datetime.strftime("%H:%M")
        if self.current_before_min > 0:
            time_info_text = f"予定時刻: {event_str}（{alarm_str}に通知 / {self.current_before_min}分前）"
        else:
            time_info_text = f"予定時刻: {event_str}"

        is_dark = (self.settings["theme"] == "Dark")
        time_fg = "#64B5F6" if is_dark else "#1565C0"
        self.lbl_end_time = tk.Label(self.current_box, text=time_info_text, font=("BIZ UDゴシック", 10, "bold"), fg=time_fg)
        self.lbl_end_time._keep_custom_color = True
        self.lbl_end_time.pack(pady=1)

        # 残り時間カウントダウン
        self.lbl_countdown = tk.Label(self.current_box, text="--:--", font=("BIZ UDゴシック", 24, "bold"))
        self.lbl_countdown.pack(pady=3)

        # プログレスバー
        self.canvas_bar = tk.Canvas(self.current_box, height=14, highlightthickness=0)
        self.canvas_bar.pack(fill="x", pady=(0, 4))

        # 操作ボタン
        btn_row = tk.Frame(self.current_box)
        btn_row.pack(fill="x", pady=(2, 0))

        if self._has_next_undone_task():
            btn_skip = tk.Button(btn_row, text="⏭ 次の予定へ進む", command=self._skip_to_next_task, font=("Meiryo UI", 9))
            btn_skip.pack(side="left", fill="x", expand=True, padx=(0, 3))

        btn_cancel = tk.Button(btn_row, text="⏹ タイマー停止", command=self.reset_timer, bg="#ffdddd", fg="black", font=("Meiryo UI", 9, "bold"))
        btn_cancel._keep_custom_color = True
        btn_cancel.pack(side="right", fill="x", expand=True)

        # --- ポモドーロ専用UI ---
        if self.is_pomodoro:
            self.pomo_frame_run = tk.LabelFrame(self.dynamic_frame, text="ポモドーロ", font=("Meiryo UI", 8), padx=6, pady=3)
            self.pomo_frame_run.pack(fill="x", pady=(0, 6))

            pomo_top = tk.Frame(self.pomo_frame_run)
            pomo_top.pack(fill="x")
            self.lbl_pomo_status = tk.Label(pomo_top, text="", font=("Meiryo UI", 9, "bold"))
            self.lbl_pomo_status._keep_custom_color = True
            self.lbl_pomo_status.pack(side="left")

            tk.Button(pomo_top, text="リセット", command=self.reset_pomodoro, font=("Meiryo UI", 8)).pack(side="right")

            self.canvas_pomo_bar = tk.Canvas(self.pomo_frame_run, height=8, highlightthickness=0)
            self.canvas_pomo_bar.pack(fill="x", pady=(3, 1))
            self._update_pomo_label(0)

        # --- 本日の予定一覧（途中追加・編集対応） ---
        sched_box = tk.LabelFrame(self.dynamic_frame, text="本日の予定一覧（ダブルクリックで編集）", font=("Meiryo UI", 8, "bold"), padx=4, pady=3)
        sched_box.pack(fill="both", expand=True)

        sched_ctrl = tk.Frame(sched_box)
        sched_ctrl.pack(fill="x", pady=(0, 2))
        tk.Button(
            sched_ctrl, text="＋ 予定を追加", font=("Meiryo UI", 8, "bold"),
            command=self._open_add_task_dialog, padx=6
        ).pack(side="left")

        list_wrap = tk.Frame(sched_box)
        list_wrap.pack(fill="both", expand=True)

        self.canvas_run_tasks = tk.Canvas(list_wrap, highlightthickness=0, height=40)
        self.scrollbar_run_tasks = ttk.Scrollbar(list_wrap, orient="vertical", command=self.canvas_run_tasks.yview)
        self.task_list_frame = tk.Frame(self.canvas_run_tasks)

        self.task_list_frame.bind(
            "<Configure>",
            lambda e: self.canvas_run_tasks.configure(scrollregion=self.canvas_run_tasks.bbox("all"))
        )
        self.run_tasks_window = self.canvas_run_tasks.create_window((0, 0), window=self.task_list_frame, anchor="nw")
        self.canvas_run_tasks.bind(
            "<Configure>",
            lambda e: self.canvas_run_tasks.itemconfig(self.run_tasks_window, width=e.width)
        )
        self.canvas_run_tasks.configure(yscrollcommand=self.scrollbar_run_tasks.set)

        self.canvas_run_tasks.pack(side="left", fill="both", expand=True)
        self.scrollbar_run_tasks.pack(side="right", fill="y")

        self.root.attributes("-alpha", self.settings["opacity"])
        self._apply_theme()
        self._refresh_running_task_list()
        self._update_tray_menu()
        self.root.after(50, self._draw_main_bar)
        if self.is_pomodoro:
            self.root.after(50, self._draw_pomo_bar)

    def _refresh_running_task_list(self):
        if not hasattr(self, "task_list_frame") or not self.task_list_frame.winfo_exists():
            return
        for w in self.task_list_frame.winfo_children():
            w.destroy()

        is_dark = (self.settings["theme"] == "Dark")
        # ラベル色もテーマに合わせて更新
        if hasattr(self, "lbl_end_time") and self.lbl_end_time.winfo_exists():
            self.lbl_end_time.config(
                bg=self.COLOR_NORMAL,
                fg="#64B5F6" if is_dark else "#1565C0"
            )

        # 未完了（進行中含む）を上部に、完了済みを下部にソートして表示
        sorted_tasks = sorted(
            enumerate(self.active_tasks),
            key=lambda x: (1 if x[1].get("done", False) else 0, x[1]["target_dt"], x[0])
        )

        for idx, item in sorted_tasks:
            row = tk.Frame(self.task_list_frame, pady=2, padx=4)
            row.pack(fill="x", pady=1)
            row._keep_custom_color = True

            t_str = item["event_dt"].strftime("%H:%M")
            bm = item.get("before_min", 0)
            bm_tag = f" (-{bm}分)" if bm > 0 else ""
            task_title = item["task"]

            if item.get("done", False):
                bg_col = "#333333" if is_dark else "#e9e9e9"
                fg_col = "#777777" if is_dark else "#888888"
                font_spec = ("Meiryo UI", 9, "overstrike")
                prefix = "✔ "
            elif idx == self.current_task_idx:
                bg_col = "#1E3A5F" if is_dark else "#FFF59D"
                fg_col = "#FFFFFF" if is_dark else "#000000"
                font_spec = ("Meiryo UI", 9, "bold")
                prefix = "▶ "
            else:
                bg_col = self.COLOR_NORMAL
                fg_col = self.COLOR_FG
                font_spec = ("Meiryo UI", 9)
                prefix = "・ "

            row.config(bg=bg_col)
            lbl = tk.Label(row, text=f"{prefix}{t_str}{bm_tag}  {task_title}", font=font_spec, bg=bg_col, fg=fg_col, anchor="w")
            lbl._keep_custom_color = True
            lbl.pack(side="left", fill="x", expand=True)

            if item.get("done", False):
                st_lbl = tk.Label(row, text="完了", font=("Meiryo UI", 8), bg=bg_col, fg=fg_col)
                st_lbl._keep_custom_color = True
                st_lbl.pack(side="right")
            else:
                # 未完了の予定はダブルクリックまたは✎ボタンで編集可能
                btn_edit = tk.Button(
                    row, text="✎", font=("Meiryo UI", 8), bg=bg_col, fg=fg_col,
                    relief="flat", bd=0, padx=3, cursor="hand2",
                    command=lambda i=idx: self._open_edit_task_dialog(i)
                )
                btn_edit._keep_custom_color = True
                btn_edit.pack(side="right", padx=(2, 0))

                if idx == self.current_task_idx:
                    st_lbl = tk.Label(row, text="進行中", font=("Meiryo UI", 8, "bold"), bg=bg_col, fg="#D32F2F" if not is_dark else "#FF8A80")
                    st_lbl._keep_custom_color = True
                    st_lbl.pack(side="right")

                row.bind("<Double-Button-1>", lambda e, i=idx: self._open_edit_task_dialog(i))
                lbl.bind("<Double-Button-1>", lambda e, i=idx: self._open_edit_task_dialog(i))

        if hasattr(self, "canvas_run_tasks") and self.canvas_run_tasks.winfo_exists():
            self.canvas_run_tasks.yview_moveto(0)

    def _update_pomo_label(self, rem_sec):
        if not hasattr(self, 'lbl_pomo_status') or not self.lbl_pomo_status.winfo_exists():
            return
        pm, ps = divmod(int(max(0, rem_sec)), 60)
        phase_str = "作業中" if self.pomo_phase == "WORK" else "休憩中"
        color = "#ff8c00" if self.pomo_phase == "WORK" else "#00bfff"
        self.lbl_pomo_status.config(
            text=f"[Pomo: {self.pomodoro_count}回目] {phase_str} - {pm:02d}:{ps:02d}",
            fg=color, bg=self.COLOR_NORMAL
        )

    def _open_settings(self):
        if self.settings_dialog is not None and self.settings_dialog.winfo_exists():
            self.settings_dialog.lift()
            self.settings_dialog.focus_force()
            return
        self._show_window()
        self.settings_dialog = SettingsDialog(self.root, self)

    # --- 実行中の予定追加・編集・削除 ---
    def _open_add_task_dialog(self):
        if not self.is_running:
            return
        TaskEditDialog(self.root, self, task_idx=None)

    def _open_edit_task_dialog(self, task_idx):
        if not self.is_running:
            return
        if 0 <= task_idx < len(self.active_tasks) and not self.active_tasks[task_idx].get("done", False):
            TaskEditDialog(self.root, self, task_idx=task_idx)

    def apply_runtime_task_change(self, task_idx, new_item=None, delete=False):
        """実行中に追加・変更・削除された予定を反映し、ソートとアクティブ切替を行う"""
        if delete and task_idx is not None:
            removed = self.active_tasks.pop(task_idx)
            debug_log(f"実行中に予定を削除: '{removed['task']}'")
        elif task_idx is None and new_item is not None:
            self.active_tasks.append(new_item)
            debug_log(f"実行中に予定を追加: '{new_item['task']}' (予定={new_item['event_dt'].strftime('%H:%M')}, -{new_item['before_min']}分)")
        elif task_idx is not None and new_item is not None:
            self.active_tasks[task_idx].update(new_item)
            debug_log(f"実行中に予定を更新: '{new_item['task']}' (予定={new_item['event_dt'].strftime('%H:%M')}, -{new_item['before_min']}分)")

        # アラーム時刻順で再ソート
        self.active_tasks.sort(key=lambda x: (x["target_dt"], x["event_dt"]))
        self._sync_idle_rows_from_active_tasks()

        # 未完了の先頭タスクを特定
        next_idx = next((i for i, item in enumerate(self.active_tasks) if not item.get("done", False)), None)
        if next_idx is None:
            messagebox.showinfo("確認", "未完了の予定がなくなったため待機画面に戻ります。", parent=self.root)
            self.reset_timer()
            return

        # アクティブタスクを再設定（割り込みや現在タスクの変更を即時反映）
        self._activate_task_by_index(next_idx)

    # --- タイマー＆スケジュールロジック ---
    def _has_next_undone_task(self):
        return any(
            not item.get("done", False)
            for i, item in enumerate(self.active_tasks)
            if i != self.current_task_idx
        )

    def _find_next_undone_index(self):
        for i, item in enumerate(self.active_tasks):
            if not item.get("done", False):
                return i
        return None

    def start_timer(self):
        debug_log("スケジュール開始要求")
        now = datetime.datetime.now()
        parsed_list = []
        past_events = []
        past_alarms_only = []

        try:
            for idx, r in enumerate(self.schedule_rows):
                auto_format_time_entry(r["time"])
                t_raw = r["time"].get().strip()
                task_str = r["task"].get().strip() or f"予定{idx+1}"
                if not t_raw:
                    continue
                hour, minute = parse_time_str(t_raw)
                before_min = parse_before_min(r["before"].get())

                event_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                alarm_dt = event_dt - datetime.timedelta(minutes=before_min)

                is_event_past = (event_dt <= now)
                is_alarm_only_past = (not is_event_past and alarm_dt <= now)

                if is_event_past:
                    bm_txt = f" (-{before_min}分)" if before_min > 0 else ""
                    past_events.append(f"・{hour:02d}:{minute:02d}{bm_txt} ({task_str})")
                elif is_alarm_only_past:
                    past_alarms_only.append(f"・予定 {hour:02d}:{minute:02d}（通知 {alarm_dt.strftime('%H:%M')} / {before_min}分前: {task_str}）")

                parsed_list.append({
                    "hour": hour,
                    "minute": minute,
                    "event_dt": event_dt,
                    "before_min": before_min,
                    "target_dt": alarm_dt,
                    "task": task_str,
                    "is_event_past": is_event_past,
                    "is_alarm_only_past": is_alarm_only_past,
                    "done": False
                })

            if not parsed_list:
                messagebox.showwarning("入力確認", "予定が1件も入力されていません。", parent=self.root)
                return

            # 1) 本来の予定時刻自体が過去の場合の確認
            if past_events:
                past_str = "\n".join(past_events)
                ans = messagebox.askyesnocancel(
                    "過去時刻の確認",
                    f"現在時刻（{now.strftime('%H:%M')}）を過ぎている予定があります:\n\n{past_str}\n\n"
                    "【はい】翌日の予定として設定する\n"
                    "【いいえ】本日の完了済み予定としてスキップする\n"
                    "【キャンセル】開始せずに入力を修正する",
                    parent=self.root
                )
                if ans is None:
                    debug_log("過去時刻確認でキャンセル選択")
                    return
                elif ans is True:
                    for item in parsed_list:
                        if item["is_event_past"]:
                            item["event_dt"] += datetime.timedelta(days=1)
                            item["target_dt"] = item["event_dt"] - datetime.timedelta(minutes=item["before_min"])
                else:
                    for item in parsed_list:
                        if item["is_event_past"]:
                            item["done"] = True

            # 2) 予定時刻は未来だが、事前アラーム時刻のみ既に過ぎている場合の確認
            if past_alarms_only:
                alarm_past_str = "\n".join(past_alarms_only)
                ans2 = messagebox.askyesnocancel(
                    "事前アラーム時刻の確認",
                    f"予定時刻はこれからですが、事前通知時刻を過ぎている予定があります:\n\n{alarm_past_str}\n\n"
                    "【はい】予定時刻ちょうど（0分前）に再設定して開始する\n"
                    "【いいえ】そのまま開始し、即時アラームを鳴らす\n"
                    "【キャンセル】開始せずに入力を修正する",
                    parent=self.root
                )
                if ans2 is None:
                    debug_log("事前アラーム過去確認でキャンセル選択")
                    return
                elif ans2 is True:
                    for item in parsed_list:
                        if item["is_alarm_only_past"]:
                            item["before_min"] = 0
                            item["target_dt"] = item["event_dt"]

            # アラーム発動時刻順（target_dt昇順）に自動ソート
            parsed_list.sort(key=lambda x: (x["target_dt"], x["event_dt"]))

            self.active_tasks = parsed_list
            self._sync_idle_rows_from_active_tasks()

            first_idx = self._find_next_undone_index()
            if first_idx is None:
                messagebox.showinfo("確認", "実行対象となる未来の予定がありません。", parent=self.root)
                return

            self.is_pomodoro = self.pomodoro_enabled.get()
            if self.is_pomodoro:
                self.pomodoro_count = 1
                self._start_pomodoro_phase("WORK")

            self._activate_task_by_index(first_idx)

        except ValueError as e:
            debug_log(f"入力エラー: {e}")
            messagebox.showerror("入力エラー", f"{e}\n（時刻例: 10:00 または 1000）", parent=self.root)
        except Exception as e:
            debug_log(f"予期せぬ開始エラー: {e}")
            messagebox.showerror("エラー", f"予期せぬエラーが発生しました: {e}", parent=self.root)

    def _activate_task_by_index(self, idx):
        self._cancel_countdown_loop()
        self.current_task_idx = idx
        current = self.active_tasks[idx]
        now = datetime.datetime.now()

        self.event_datetime = current["event_dt"]
        self.current_before_min = current.get("before_min", 0)
        self.start_datetime = now

        if current["target_dt"] <= now:
            debug_log(f"タスク[{idx}] '{current['task']}' は既にアラーム時刻に到達しているため即時アラームへ移行")
            self.target_datetime = now
        else:
            self.target_datetime = current["target_dt"]

        self.task_name = current["task"]
        self.is_running = True

        debug_log(
            f"タスク開始 [{idx+1}/{len(self.active_tasks)}]: '{self.task_name}' "
            f"予定={self.event_datetime.strftime('%H:%M')} / アラーム={self.target_datetime.strftime('%Y-%m-%d %H:%M:%S')} (-{self.current_before_min}分)"
        )
        self._switch_ui_to_running()
        self._update_countdown_loop()

    def _skip_to_next_task(self):
        if not self.is_running:
            return
        debug_log(f"手動スキップ: '{self.task_name}' を完了扱いにして次へ")
        if 0 <= self.current_task_idx < len(self.active_tasks):
            self.active_tasks[self.current_task_idx]["done"] = True
        next_idx = self._find_next_undone_index()
        if next_idx is not None:
            self._activate_task_by_index(next_idx)
        else:
            self.reset_timer()

    def reset_pomodoro(self):
        debug_log("ポモドーロリセット実行")
        self.pomodoro_count = 1
        if self.is_running and self.is_pomodoro:
            self._start_pomodoro_phase("WORK")
            self._draw_pomo_bar()

    def _start_pomodoro_phase(self, phase):
        now = datetime.datetime.now()
        self.pomo_phase = phase
        mins = self.settings["pomo_work_min"] if phase == "WORK" else self.settings["pomo_break_min"]
        self.pomo_target_datetime = now + datetime.timedelta(minutes=mins)

    def _update_countdown_loop(self):
        self.countdown_after_id = None
        if not self.is_running:
            return
        now = datetime.datetime.now()
        overall_remaining = (self.target_datetime - now).total_seconds()

        self._draw_main_bar()

        if self.is_pomodoro and overall_remaining > 0:
            pomo_rem = (self.pomo_target_datetime - now).total_seconds()
            if pomo_rem <= 0:
                next_phase = "BREAK" if self.pomo_phase == "WORK" else "WORK"
                if next_phase == "WORK":
                    self.pomodoro_count += 1
                self._start_pomodoro_phase(next_phase)
                self._play_mini_alert()
                pomo_rem = (self.pomo_target_datetime - now).total_seconds()

            self._update_pomo_label(pomo_rem)
            self._draw_pomo_bar()

        if overall_remaining > 0:
            self._update_tray_status(overall_remaining)
            safe_seconds = int(math.ceil(overall_remaining))
            h, rem = divmod(safe_seconds, 3600)
            m, s = divmod(rem, 60)
            time_str = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

            if hasattr(self, "lbl_countdown") and self.lbl_countdown.winfo_exists():
                self.lbl_countdown.config(text=time_str)
            self.countdown_after_id = self.root.after(500, self._update_countdown_loop)
        else:
            if hasattr(self, "lbl_countdown") and self.lbl_countdown.winfo_exists():
                self.lbl_countdown.config(text="00:00")
            self._update_tray_status(0)
            self._trigger_alarm()

    def _play_mini_alert(self):
        if not self.settings["sound_enabled"]:
            return
        threading.Thread(target=lambda: winsound.Beep(1200, 200), daemon=True).start()

    # --- プログレスバー描画 ---
    def _draw_main_bar(self):
        if not hasattr(self, 'canvas_bar') or not self.canvas_bar.winfo_exists():
            return
        self.canvas_bar.delete("all")
        w = self.canvas_bar.winfo_width()
        h = self.canvas_bar.winfo_height()
        if w <= 1:
            return

        bw = w / 20
        now = datetime.datetime.now()
        total = (self.target_datetime - self.start_datetime).total_seconds()
        rem = (self.target_datetime - now).total_seconds()

        ratio = max(0.0, min(1.0, rem / total)) if total > 0 else 0.0
        visible_blocks = int(math.ceil(ratio * 20))
        bg_col = "#404040" if self.settings["theme"] == "Dark" else "#DDDDDD"

        for i in range(20):
            x1 = i * bw + 1
            x2 = (i + 1) * bw - 1
            if i < 5: color = "#E74C3C"
            elif i < 10: color = "#F39C12"
            elif i < 15: color = "#2ECC71"
            else: color = "#3498DB"

            fill_color = color if i < visible_blocks else bg_col
            self.canvas_bar.create_rectangle(x1, 0, x2, h, fill=fill_color, outline="")

    def _draw_pomo_bar(self):
        if not hasattr(self, 'canvas_pomo_bar') or not self.canvas_pomo_bar.winfo_exists():
            return
        self.canvas_pomo_bar.delete("all")
        w = self.canvas_pomo_bar.winfo_width()
        h = self.canvas_pomo_bar.winfo_height()
        if w <= 1:
            return

        now = datetime.datetime.now()
        mins = self.settings["pomo_work_min"] if self.pomo_phase == "WORK" else self.settings["pomo_break_min"]
        total = mins * 60
        rem = max(0.0, (self.pomo_target_datetime - now).total_seconds())

        ratio = max(0.0, min(1.0, rem / total)) if total > 0 else 0.0
        bw = w / 20
        visible_blocks = int(math.ceil(ratio * 20))
        bg_col = "#404040" if self.settings["theme"] == "Dark" else "#DDDDDD"

        for i in range(20):
            x1 = i * bw + 1
            x2 = (i + 1) * bw - 1
            if i < 5: color = "#E74C3C"
            elif i < 10: color = "#F39C12"
            elif i < 15: color = "#2ECC71"
            else: color = "#3498DB"

            fill_color = color if i < visible_blocks else bg_col
            self.canvas_pomo_bar.create_rectangle(x1, 0, x2, h, fill=fill_color, outline="")

    # --- アラーム＆スヌーズ＆連続移行処理 ---
    def _trigger_alarm(self):
        debug_log(f"アラーム発動: '{self.task_name}' (予定={self.event_datetime.strftime('%H:%M')}, -{self.current_before_min}分)")
        self._cancel_countdown_loop()
        self.is_running = False
        self.is_alarming = True
        self._update_tray_menu()

        self._write_log()

        now = datetime.datetime.now()
        event_str = self.event_datetime.strftime("%H:%M")
        alarm_str = self.target_datetime.strftime("%H:%M")

        # 次の未完了予定を取得
        next_task = None
        for i, item in enumerate(self.active_tasks):
            if i != self.current_task_idx and not item.get("done", False):
                next_task = item
                break

        next_info = ""
        if next_task:
            next_info = f" / 次: {next_task['event_dt'].strftime('%H:%M')} {next_task['task']}"

        if self.current_before_min > 0:
            toast_title = f"⏰ {event_str} の予定まであと{self.current_before_min}分"
            header_text = f"⏰ {event_str} の予定まであと {self.current_before_min}分 です！"
        else:
            toast_title = f"⏰ 時間です ({event_str})"
            header_text = f"⏰ {event_str} になりました！"

        self._send_toast_notification(toast_title, f"【{self.task_name}】{next_info}")

        # ウィンドウを最前面に復帰
        self.root.deiconify()
        try:
            self.root.state("normal")
        except Exception:
            pass
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 1.0)
        self.root.lift()
        self.root.focus_force()

        self.idle_frame.pack_forget()
        self.dynamic_frame.pack_forget()

        self.alarm_frame = tk.Frame(self.root, bg=self.COLOR_WARN, padx=12, pady=10)
        self.alarm_frame.pack(expand=True, fill="both")

        tk.Label(self.alarm_frame, text=header_text, font=("Meiryo UI", 12, "bold"), bg=self.COLOR_WARN, fg="white", wraplength=310).pack(pady=(6, 2))
        if self.current_before_min > 0:
            tk.Label(self.alarm_frame, text=f"（現在 {alarm_str} / 準備・出発アラーム）", font=("Meiryo UI", 9), bg=self.COLOR_WARN, fg="white").pack(pady=(0, 4))

        lbl_alarm_task = tk.Label(self.alarm_frame, text=self.task_name, font=("Meiryo UI", 17, "bold"), bg=self.COLOR_WARN, fg="white", wraplength=300)
        lbl_alarm_task.pack(pady=4)
        self.alarm_frame.bind(
            "<Configure>",
            lambda e: lbl_alarm_task.config(wraplength=max(180, e.width - 24)) if lbl_alarm_task.winfo_exists() else None
        )

        if next_task:
            nxt_bm = next_task.get("before_min", 0)
            nxt_bm_txt = f" (-{nxt_bm}分)" if nxt_bm > 0 else ""
            nxt_text = f"次の予定: {next_task['event_dt'].strftime('%H:%M')}{nxt_bm_txt} 「{next_task['task']}」"
            btn_main_txt = "確認して次の予定へ (Enter)"
        else:
            nxt_text = "（本日の予定はこれで最後です）"
            btn_main_txt = "完了して待機画面へ (Enter)"

        tk.Label(self.alarm_frame, text=nxt_text, font=("Meiryo UI", 9), bg=self.COLOR_WARN, fg="white", wraplength=300).pack(pady=(2, 8))

        btn_stop = tk.Button(
            self.alarm_frame, text=btn_main_txt, font=("Meiryo UI", 10, "bold"),
            command=self.stop_alarm_and_proceed, bg="#ffffff", fg="black", pady=5
        )
        btn_stop.pack(fill="x", pady=3)
        btn_stop.focus_set()

        # 事前アラームかつ本来の予定時刻がまだ未来の場合：「本番時刻にもう一度鳴らす」ボタンを表示
        if self.current_before_min > 0 and self.event_datetime > now:
            btn_at_event = tk.Button(
                self.alarm_frame, text=f"🔔 予定時刻（{event_str}）にもう一度鳴らす",
                font=("Meiryo UI", 10, "bold"),
                command=self.snooze_until_event_time, bg="#BBDEFB", fg="black", pady=4
            )
            btn_at_event.pack(fill="x", pady=3)

        btn_snooze = tk.Button(
            self.alarm_frame, text="💤 5分スヌーズ（延長）", font=("Meiryo UI", 9, "bold"),
            command=lambda: self.snooze_alarm(5), bg="#FFF59D", fg="black", pady=4
        )
        btn_snooze.pack(fill="x", pady=3)

        self.root.bind('<Return>', lambda e: self.stop_alarm_and_proceed())

        self._start_flashing()
        if self.settings["sound_enabled"]:
            threading.Thread(target=self._sound_loop, daemon=True).start()

        self.alarm_stop_id = self.root.after(15000, self._auto_stop_alarm_effects)

    def _auto_stop_alarm_effects(self):
        self.is_alarming = False

    def _cleanup_alarm_ui(self):
        self.is_alarming = False
        if self.alarm_stop_id:
            self.root.after_cancel(self.alarm_stop_id)
            self.alarm_stop_id = None
        self.root.unbind('<Return>')
        if hasattr(self, 'alarm_frame') and self.alarm_frame.winfo_exists():
            self.alarm_frame.destroy()

    def snooze_until_event_time(self):
        """事前通知後、本来の予定時刻ちょうどにもう一度鳴らす"""
        debug_log(f"本番時刻に再通知を設定: 予定時刻={self.event_datetime.strftime('%H:%M')}")
        self._cleanup_alarm_ui()
        cur_item = self.active_tasks[self.current_task_idx]
        cur_item["before_min"] = 0
        cur_item["target_dt"] = cur_item["event_dt"]

        self.active_tasks.sort(key=lambda x: (x["target_dt"], x["event_dt"]))
        next_idx = self._find_next_undone_index()
        self._apply_base_settings()
        if next_idx is not None:
            self._activate_task_by_index(next_idx)
        else:
            self._switch_ui_to_idle()

    def snooze_alarm(self, minutes=5):
        debug_log(f"スヌーズ実行: +{minutes}分延長")
        self._cleanup_alarm_ui()
        now = datetime.datetime.now()
        new_target = now + datetime.timedelta(minutes=minutes)

        cur_item = self.active_tasks[self.current_task_idx]
        cur_item["target_dt"] = new_target
        cur_item["before_min"] = 0
        if new_target > cur_item["event_dt"]:
            cur_item["event_dt"] = new_target
        if not cur_item["task"].endswith("(スヌーズ)"):
            cur_item["task"] += " (スヌーズ)"

        self.active_tasks.sort(key=lambda x: (x["target_dt"], x["event_dt"]))
        next_idx = self._find_next_undone_index()
        self._apply_base_settings()
        if next_idx is not None:
            self._activate_task_by_index(next_idx)
        else:
            self._switch_ui_to_idle()

    def stop_alarm_and_proceed(self):
        debug_log("アラーム停止・次タスク判定")
        self._cleanup_alarm_ui()
        self._apply_base_settings()

        if 0 <= self.current_task_idx < len(self.active_tasks):
            self.active_tasks[self.current_task_idx]["done"] = True

        next_idx = self._find_next_undone_index()
        if next_idx is not None:
            self._activate_task_by_index(next_idx)
        else:
            debug_log("全スケジュール完了")
            self._send_toast_notification("🎉 全スケジュール完了", "登録されたすべての予定が完了しました。")
            self._switch_ui_to_idle()

    def reset_timer(self):
        debug_log("スケジュール手動停止・待機画面へ復帰")
        self._cancel_countdown_loop()
        self._cleanup_alarm_ui()
        self.is_running = False
        self._apply_base_settings()
        self._switch_ui_to_idle()

    def _sound_loop(self):
        pattern = self.settings["sound_pattern"]
        while self.is_alarming:
            if "ブザー" in pattern:
                winsound.Beep(880, 400); self._wait_with_check(0.4)
            elif "低音" in pattern:
                winsound.Beep(440, 300); self._wait_with_check(0.5)
            elif "Windows" in pattern:
                winsound.MessageBeep(winsound.MB_ICONASTERISK); self._wait_with_check(1.0)
            elif "アラーム" in pattern:
                winsound.Beep(1000, 50); self._wait_with_check(0.1)
                if not self.is_alarming: break
                winsound.Beep(1000, 50); self._wait_with_check(0.8)
            else:
                winsound.Beep(880, 400); self._wait_with_check(0.4)

    def _wait_with_check(self, seconds):
        start = time.time()
        while time.time() - start < seconds:
            if not self.is_alarming:
                return
            time.sleep(0.1)

    def _start_flashing(self):
        if not hasattr(self, 'alarm_frame') or not self.alarm_frame.winfo_exists():
            return
        if not self.is_alarming:
            try:
                self.alarm_frame.config(bg=self.COLOR_WARN)
            except Exception:
                pass
            return
        try:
            cur = self.alarm_frame.cget("bg")
            nxt = "#B71C1C" if cur == self.COLOR_WARN else self.COLOR_WARN
            self.alarm_frame.config(bg=nxt)
            for child in self.alarm_frame.winfo_children():
                if isinstance(child, tk.Label):
                    child.config(bg=nxt)
            self.root.after(500, self._start_flashing)
        except Exception:
            return

    def _write_log(self):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        bm_txt = f" ({self.current_before_min}分前通知)" if self.current_before_min > 0 else ""
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{now_str}] 通知: {self.task_name}{bm_txt}\n")
        except Exception as e:
            debug_log(f"完了ログ書き込みエラー: {e}")

    # --- トレイアイコン ---
    def _init_tray_icon(self):
        image = self._get_idle_icon_image()
        menu = pystray.Menu(
            pystray.MenuItem("開く", self._show_window, default=True),
            pystray.MenuItem("⏭ 次の予定へ進む", self._skip_from_tray, enabled=lambda item: self.is_running and self._has_next_undone_task()),
            pystray.MenuItem("⏹ タイマー停止", self._stop_from_tray, enabled=lambda item: self.is_running),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⚙ 設定を開く", self._open_settings_from_tray),
            pystray.MenuItem("終了", self._quit_app)
        )
        self.tray_icon = pystray.Icon("SimpleTimer", image, "SimpleTimer - 待機中", menu)
        self.icon_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.icon_thread.start()

    def _update_tray_menu(self):
        if self.tray_icon:
            try:
                self.tray_icon.update_menu()
            except Exception:
                pass

    def _skip_from_tray(self, icon=None, item=None):
        self.root.after(0, self._skip_to_next_task)

    def _stop_from_tray(self, icon=None, item=None):
        self.root.after(0, self.reset_timer)

    def _open_settings_from_tray(self, icon=None, item=None):
        self.root.after(0, self._open_settings)

    def _get_idle_icon_image(self):
        if os.path.exists(self.icon_file):
            try:
                return Image.open(self.icon_file)
            except Exception:
                pass
        img = Image.new('RGB', (64, 64), color=self.COLOR_IDLE_ICON)
        ImageDraw.Draw(img).ellipse((8, 8, 56, 56), outline="white", width=3)
        return img

    def _create_icon_image(self, text, bg_color):
        img = Image.new('RGB', (64, 64), color=bg_color)
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arialbd.ttf", 36)
        except Exception:
            font = ImageFont.load_default()
        try:
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
            draw.text(((64 - (right - left)) // 2, (64 - (bottom - top)) // 2), text, font=font, fill="white")
        except Exception:
            pass
        return img

    def _update_tray_status(self, rem_sec):
        if self.tray_icon is None or self.is_quitting:
            return
        bg = self.COLOR_WARN_ICON if rem_sec <= 300 else self.COLOR_SAFE_ICON
        event_str = self.event_datetime.strftime("%H:%M")
        bm_tag = f"(-{self.current_before_min}分)" if self.current_before_min > 0 else ""
        label_prefix = "通知まであと" if self.current_before_min > 0 else "あと"

        if rem_sec > 60:
            m = int(rem_sec // 60)
            txt = "99+" if m >= 100 else str(m)
            rem_txt = f"{label_prefix}{m}分"
        else:
            s = int(max(0, rem_sec))
            txt = str(s)
            rem_txt = f"{label_prefix}{s}秒"

        tooltip = f"[{event_str} {self.task_name}{bm_tag}] {rem_txt}"
        if len(tooltip) > 63:
            # Windowsのツールチップ63文字制限に合わせてタスク名を省略
            fixed_len = len(f"[{event_str} …{bm_tag}] {rem_txt}")
            allow_task = max(1, 63 - fixed_len)
            tooltip = f"[{event_str} {self.task_name[:allow_task]}…{bm_tag}] {rem_txt}"

        try:
            self.tray_icon.icon = self._create_icon_image(txt, bg)
            self.tray_icon.title = tooltip[:63]
        except Exception:
            pass

    def _on_close_window(self):
        self.root.withdraw()

    def _show_window_mainthread(self):
        self.root.deiconify()
        try:
            self.root.state("normal")
        except Exception:
            pass
        self.root.lift()
        if not self.settings.get("topmost", True):
            self.root.attributes("-topmost", True)
            self.root.after(50, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()
        debug_log("トレイアイコンからウィンドウを前面復帰")

    def _show_window(self, icon=None, item=None):
        self.root.after(0, self._show_window_mainthread)

    def _quit_app(self, icon=None, item=None):
        debug_log("アプリケーション終了処理")
        self.is_quitting = True
        self.is_running = False
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self.root.destroy)
        self.root.after(0, sys.exit)


class TaskEditDialog(tk.Toplevel):
    """実行中の予定追加・編集用ダイアログ"""
    def __init__(self, parent, app, task_idx=None):
        super().__init__(parent)
        self.app = app
        self.task_idx = task_idx
        self.is_edit = (task_idx is not None)

        self.title("予定の編集" if self.is_edit else "予定の追加")
        self.geometry("360x210")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.grab_set()

        is_dark = (app.settings["theme"] == "Dark")
        bg_col = "#2b2b2b" if is_dark else "#f0f0f0"
        fg_col = "#ffffff" if is_dark else "#000000"
        input_bg = "#3c3f41" if is_dark else "#ffffff"
        self.config(bg=bg_col)

        f = tk.Frame(self, padx=14, pady=12, bg=bg_col)
        f.pack(fill="both", expand=True)

        tk.Label(f, text="予定時刻:", bg=bg_col, fg=fg_col, font=("Meiryo UI", 9)).grid(row=0, column=0, sticky="e", pady=6, padx=(0, 8))
        self.ent_time = tk.Entry(f, width=10, font=("BIZ UDゴシック", 11), justify="center", bg=input_bg, fg=fg_col, insertbackground=fg_col)
        self.ent_time.grid(row=0, column=1, sticky="w")
        self.ent_time.bind("<FocusOut>", lambda e: auto_format_time_entry(self.ent_time))

        tk.Label(f, text="事前アラーム:", bg=bg_col, fg=fg_col, font=("Meiryo UI", 9)).grid(row=1, column=0, sticky="e", pady=6, padx=(0, 8))
        bf = tk.Frame(f, bg=bg_col)
        bf.grid(row=1, column=1, sticky="w")
        self.ent_before = tk.Entry(bf, width=5, font=("BIZ UDゴシック", 11), justify="center", bg=input_bg, fg=fg_col, insertbackground=fg_col)
        self.ent_before.pack(side="left")
        tk.Label(bf, text=" 分前（0で予定時刻どおり）", bg=bg_col, fg=fg_col, font=("Meiryo UI", 8)).pack(side="left")

        tk.Label(f, text="予定・用件:", bg=bg_col, fg=fg_col, font=("Meiryo UI", 9)).grid(row=2, column=0, sticky="e", pady=6, padx=(0, 8))
        self.ent_task = tk.Entry(f, width=28, font=("Meiryo UI", 10), bg=input_bg, fg=fg_col, insertbackground=fg_col)
        self.ent_task.grid(row=2, column=1, sticky="we")

        if self.is_edit:
            item = app.active_tasks[task_idx]
            self.ent_time.insert(0, item["event_dt"].strftime("%H:%M"))
            self.ent_before.insert(0, str(item.get("before_min", 0)))
            self.ent_task.insert(0, item["task"])
        else:
            default_t = (datetime.datetime.now() + datetime.timedelta(minutes=30)).strftime("%H:%M")
            self.ent_time.insert(0, default_t)
            self.ent_before.insert(0, str(app.settings.get("default_before_min", 0)))

        btn_f = tk.Frame(self, pady=8, padx=14, bg=bg_col)
        btn_f.pack(fill="x")

        if self.is_edit:
            tk.Button(btn_f, text="削除", command=self._delete, bg="#ffdddd", fg="black", font=("Meiryo UI", 9), width=8).pack(side="left")

        tk.Button(btn_f, text="キャンセル", command=self.destroy, font=("Meiryo UI", 9), width=10).pack(side="right", padx=(6, 0))
        tk.Button(btn_f, text="保存", command=self._save, bg="#2E7D32", fg="white", font=("Meiryo UI", 9, "bold"), width=10).pack(side="right")

        self.bind("<Return>", lambda e: self._save())
        self.ent_time.focus_set()

    def _save(self):
        auto_format_time_entry(self.ent_time)
        try:
            hour, minute = parse_time_str(self.ent_time.get())
            before_min = parse_before_min(self.ent_before.get())
            task_str = self.ent_task.get().strip() or "予定"
        except ValueError as e:
            messagebox.showerror("入力エラー", str(e), parent=self)
            return

        now = datetime.datetime.now()
        event_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if event_dt <= now:
            if messagebox.askyesno("過去時刻の確認", f"{hour:02d}:{minute:02d} は現在時刻を過ぎています。\n翌日の予定として登録しますか？", parent=self):
                event_dt += datetime.timedelta(days=1)
            else:
                return

        alarm_dt = event_dt - datetime.timedelta(minutes=before_min)
        if alarm_dt <= now and before_min > 0:
            ans = messagebox.askyesnocancel(
                "事前アラーム時刻の確認",
                f"事前通知時刻（{alarm_dt.strftime('%H:%M')}）は既に過ぎています。\n\n"
                "【はい】予定時刻ちょうど（0分前）に変更して保存\n"
                "【いいえ】そのまま保存して即時通知\n"
                "【キャンセル】入力を修正",
                parent=self
            )
            if ans is None:
                return
            elif ans is True:
                before_min = 0
                alarm_dt = event_dt

        new_item = {
            "hour": hour,
            "minute": minute,
            "event_dt": event_dt,
            "before_min": before_min,
            "target_dt": alarm_dt,
            "task": task_str,
            "done": False
        }
        self.destroy()
        self.app.apply_runtime_task_change(self.task_idx, new_item=new_item, delete=False)

    def _delete(self):
        if messagebox.askyesno("削除確認", "この予定を削除しますか？", parent=self):
            self.destroy()
            self.app.apply_runtime_task_change(self.task_idx, delete=True)


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("設定")
        self.geometry("460x380")
        self.minsize(460, 380)
        self.attributes("-topmost", True)
        self.grab_set()

        bg_col = "#2b2b2b" if app.settings["theme"] == "Dark" else "#f0f0f0"
        fg_col = "#ffffff" if app.settings["theme"] == "Dark" else "#000000"
        self.config(bg=bg_col)

        self.var_topmost = tk.BooleanVar(value=app.settings["topmost"])
        self.var_theme = tk.StringVar(value=app.settings["theme"])
        self.var_sound_on = tk.BooleanVar(value=app.settings["sound_enabled"])
        self.var_sound_pat = tk.StringVar(value=app.settings["sound_pattern"])
        self.var_toast_on = tk.BooleanVar(value=app.settings.get("toast_enabled", True))
        self.var_opacity = tk.DoubleVar(value=app.settings["opacity"])
        self.var_pomo_w = tk.IntVar(value=app.settings["pomo_work_min"])
        self.var_pomo_b = tk.IntVar(value=app.settings["pomo_break_min"])
        self.var_default_before = tk.IntVar(value=app.settings.get("default_before_min", 0))

        f = tk.Frame(self, padx=15, pady=12, bg=bg_col)
        f.pack(fill="both", expand=True)

        def _lbl(r, c, txt):
            lbl = tk.Label(f, text=txt, bg=bg_col, fg=fg_col, font=("Meiryo UI", 9))
            lbl.grid(row=r, column=c, sticky="e", pady=6, padx=(0, 8))

        _lbl(0, 0, "最前面表示:")
        tk.Checkbutton(f, text="常に最前面に表示", variable=self.var_topmost, bg=bg_col, fg=fg_col, selectcolor=bg_col).grid(row=0, column=1, sticky="w")

        _lbl(1, 0, "テーマ:")
        ttk.Combobox(f, textvariable=self.var_theme, values=["Light", "Dark"], state="readonly", width=10).grid(row=1, column=1, sticky="w")

        _lbl(2, 0, "タイマー中透過度:")
        tk.Scale(
            f, variable=self.var_opacity, from_=MIN_OPACITY, to=MAX_OPACITY, resolution=OPACITY_STEP,
            orient="horizontal", showvalue=True, bg=bg_col, fg=fg_col, highlightthickness=0, length=160
        ).grid(row=2, column=1, sticky="w")

        _lbl(3, 0, "アラーム音:")
        sf = tk.Frame(f, bg=bg_col)
        sf.grid(row=3, column=1, sticky="w")
        tk.Checkbutton(sf, text="ON", variable=self.var_sound_on, bg=bg_col, fg=fg_col, selectcolor=bg_col).pack(side="left")
        ttk.Combobox(sf, textvariable=self.var_sound_pat, values=["ブザー(標準)", "低音(控えめ)", "Windows通知", "アラーム(ピッピッ)"],
                     state="readonly", width=15).pack(side="left", padx=4)
        tk.Button(sf, text="テスト", command=self._test_sound, font=("Meiryo UI", 8), padx=6).pack(side="left", padx=2)

        _lbl(4, 0, "Windows通知:")
        tf = tk.Frame(f, bg=bg_col)
        tf.grid(row=4, column=1, sticky="w")
        tk.Checkbutton(tf, text="トースト通知を表示", variable=self.var_toast_on, bg=bg_col, fg=fg_col, selectcolor=bg_col).pack(side="left")

        _lbl(5, 0, "既定の事前アラーム:")
        df = tk.Frame(f, bg=bg_col)
        df.grid(row=5, column=1, sticky="w")
        tk.Entry(df, textvariable=self.var_default_before, width=5, justify="center").pack(side="left")
        tk.Label(df, text=" 分前（新規予定の初期値）", bg=bg_col, fg=fg_col, font=("Meiryo UI", 8)).pack(side="left")

        _lbl(6, 0, "Pomo(作業/休憩):")
        pf = tk.Frame(f, bg=bg_col)
        pf.grid(row=6, column=1, sticky="w")
        tk.Entry(pf, textvariable=self.var_pomo_w, width=4).pack(side="left")
        tk.Label(pf, text="分 / ", bg=bg_col, fg=fg_col).pack(side="left")
        tk.Entry(pf, textvariable=self.var_pomo_b, width=4).pack(side="left")
        tk.Label(pf, text="分", bg=bg_col, fg=fg_col).pack(side="left")

        bf = tk.Frame(self, pady=10, bg=bg_col)
        bf.pack(fill="x")
        tk.Button(bf, text="保存して適用", command=self._save, width=16, font=("Meiryo UI", 9, "bold")).pack()

    def _test_sound(self):
        if not self.var_sound_on.get():
            return
        pattern = self.var_sound_pat.get()
        def play():
            if "ブザー" in pattern: winsound.Beep(880, 400)
            elif "低音" in pattern: winsound.Beep(440, 300)
            elif "Windows" in pattern: winsound.MessageBeep(winsound.MB_ICONASTERISK)
            elif "アラーム" in pattern:
                winsound.Beep(1000, 50); time.sleep(0.1); winsound.Beep(1000, 50)
            else: winsound.Beep(880, 400)
        threading.Thread(target=play, daemon=True).start()

    def _save(self):
        s = self.app.settings
        s["topmost"] = self.var_topmost.get()
        s["theme"] = self.var_theme.get()
        s["sound_enabled"] = self.var_sound_on.get()
        s["sound_pattern"] = self.var_sound_pat.get()
        s["toast_enabled"] = self.var_toast_on.get()
        s["opacity"] = round(max(MIN_OPACITY, min(MAX_OPACITY, self.var_opacity.get())), 2)
        try:
            s["default_before_min"] = max(0, min(720, self.var_default_before.get()))
        except Exception:
            s["default_before_min"] = 0
        try:
            s["pomo_work_min"] = max(1, self.var_pomo_w.get())
            s["pomo_break_min"] = max(1, self.var_pomo_b.get())
        except Exception:
            pass

        self.app.save_settings()
        self.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = SimpleTimer(root)
    root.mainloop()
