# SimpleTimer.py

import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import threading
import time
import winsound
import datetime
import re
import sys
import os
import math
import json
import logging

# --- デバッグログ設定 ---
os.makedirs("log", exist_ok=True)
log_filename = datetime.datetime.now().strftime("log/debug_log_%Y%m%d_%H%M%S.txt")
logging.basicConfig(filename=log_filename, level=logging.DEBUG, 
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    encoding='utf-8')

def debug_log(msg):
    logging.debug(msg)
    print(f"DEBUG: {msg}")

# 外部ライブラリのインポートチェック
try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    root = tk.Tk()
    root.withdraw()
    error_msg = f"起動に必要なライブラリが見つかりません。\n以下のコマンドを実行してください:\n\npip install pystray Pillow\n\nエラー詳細: {e}"
    debug_log(f"ImportError: {e}")
    messagebox.showerror("ライブラリ不足", error_msg)
    sys.exit(1)

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class SimpleTimer:
    def __init__(self, root):
        debug_log("アプリケーション初期化開始")
        self.root = root
        self.root.title("SimpleTimer")
        
        self.icon_file = resource_path("timer.ico")
        if os.path.exists(self.icon_file):
            try:
                self.root.iconbitmap(default=self.icon_file)
            except: pass

        self.root.minsize(350, 280)
        
        # 状態変数
        self.is_running = False
        self.start_datetime = None
        self.target_datetime = None
        self.task_name = ""
        self.is_alarming = False
        self.log_file = "timer_log.txt"
        self.milestone_done = False
        self.alarm_stop_id = None
        self.is_dragging_marker = False
        
        # 設定のロード
        self.settings_file = "settings.json"
        self.presets_file = "presets.json"
        self.presets = []
        self.main_time_type = "end_time"
        
        self.settings = {
            "topmost": True,
            "theme": "Light",
            "sound_enabled": True,
            "sound_pattern": "ブザー(標準)",
            "opacity": 1.0,
            "pomo_work_min": 25,
            "pomo_break_min": 5,
            "auto_milestone_enabled": False, 
            "auto_milestone_percent": 50
        }
        self._load_settings()
        self._load_presets()
        
        # ポモドーロ関連変数
        self.pomodoro_enabled = tk.BooleanVar(value=False)
        self.is_pomodoro = False
        self.pomo_phase = "IDLE"
        self.pomodoro_count = 0
        self.pomo_target_datetime = None

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
        self._switch_ui_to_idle()
        self._center_window_initial()
        self._update_preset_combo()

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
            except Exception as e:
                debug_log(f"設定読み込みエラー: {e}")

    def save_settings(self):
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
            self._apply_base_settings()
            self._apply_theme()
        except Exception as e:
            debug_log(f"設定保存エラー: {e}")

    def _load_presets(self):
        if os.path.exists(self.presets_file):
            try:
                with open(self.presets_file, "r", encoding="utf-8") as f:
                    self.presets = json.load(f)
            except Exception:
                self.presets = []

    def save_presets(self):
        try:
            with open(self.presets_file, "w", encoding="utf-8") as f:
                json.dump(self.presets, f, ensure_ascii=False, indent=2)
        except Exception: pass

    # --- UI初期化 ---
    def _apply_base_settings(self):
        self.root.attributes("-topmost", self.settings["topmost"])
        if not self.is_running:
            self.root.attributes("-alpha", 1.0)
        else:
            self.root.attributes("-alpha", self.settings["opacity"])

    def _apply_theme(self):
        if self.settings["theme"] == "Dark":
            self.COLOR_NORMAL = "#2b2b2b"
            self.COLOR_FG = "#ffffff"
            input_bg = "#404040"
        else:
            self.COLOR_NORMAL = "#f0f0f0"
            self.COLOR_FG = "#000000"
            input_bg = "#ffffff"

        self.root.config(bg=self.COLOR_NORMAL)
        
        def _apply_recursive(w):
            try:
                if w not in (getattr(self, 'canvas_bar', None), getattr(self, 'canvas_pomo_bar', None)):
                    w.config(bg=self.COLOR_NORMAL)
                if isinstance(w, (tk.Label, tk.Checkbutton, tk.Radiobutton, tk.LabelFrame)):
                    w.config(fg=self.COLOR_FG)
                    if isinstance(w, (tk.Checkbutton, tk.Radiobutton)):
                        w.config(selectcolor=input_bg)
                elif isinstance(w, tk.Entry):
                    w.config(bg=input_bg, fg=self.COLOR_FG, insertbackground=self.COLOR_FG)
                elif isinstance(w, tk.Button):
                    w.config(fg=self.COLOR_FG)
            except: pass
            for c in w.winfo_children():
                _apply_recursive(c)
                
        _apply_recursive(self.root)

    def _center_window_initial(self):
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        height = self.root.winfo_reqheight()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"+{(sw//2)-(width//2)}+{(sh//2)-(height//2)}")

    def _setup_structure(self):
        self.top_frame = tk.Frame(self.root)
        self.top_frame.pack(fill="x", padx=5, pady=5)
        
        # ヘッダーコントロール
        tk.Button(self.top_frame, text="⚙ 設定", command=self._open_settings, font=("Meiryo UI", 8)).pack(side="right")

        self.static_frame = tk.Frame(self.root, padx=10, pady=5)
        self.static_frame.pack(fill="x")

        # プリセット行
        row0 = tk.Frame(self.static_frame)
        row0.pack(fill="x", pady=(0, 5))
        tk.Label(row0, text="プリセット:", font=("Meiryo UI", 9)).pack(side="left")
        self.combo_preset = ttk.Combobox(row0, state="readonly", font=("Meiryo UI", 9))
        self.combo_preset.pack(side="left", padx=5, fill="x", expand=True)
        self.combo_preset.bind("<<ComboboxSelected>>", self._on_preset_selected)
        tk.Button(row0, text="管理", font=("Meiryo UI", 9), command=self._open_preset_manager).pack(side="right")

        # 用件行
        row1 = tk.Frame(self.static_frame)
        row1.pack(fill="x", pady=(0, 5))
        tk.Label(row1, text="用件:", font=("Meiryo UI", 10)).pack(side="left")
        self.entry_task = tk.Entry(row1, font=("Meiryo UI", 10))
        self.entry_task.insert(0, "作業")
        self.entry_task.pack(side="left", padx=5, fill="x", expand=True)

        # ポモドーロ行
        pomo_frame = tk.Frame(self.static_frame)
        pomo_frame.pack(fill="x", pady=(0, 5))
        self.chk_pomodoro = tk.Checkbutton(pomo_frame, text="ポモドーロ併用", variable=self.pomodoro_enabled, font=("Meiryo UI", 9))
        self.chk_pomodoro.pack(side="left")

        # 時間行
        row2 = tk.Frame(self.static_frame)
        row2.pack(fill="x", pady=(0, 5))
        self.lbl_time_mode = tk.Label(row2, text="終了時刻:", font=("Meiryo UI", 10))
        self.lbl_time_mode.pack(side="left")
        self.entry_time = tk.Entry(row2, width=8, font=("Meiryo UI", 14))
        self.entry_time.insert(0, datetime.datetime.now().strftime("%H:%M"))
        self.entry_time.pack(side="left", padx=5)

        self.dynamic_frame = tk.Frame(self.root, padx=10) 
        self.dynamic_frame.pack(fill="both", expand=True, pady=(0, 10))
        self.canvas_bar = tk.Canvas(self.dynamic_frame, height=20, bg="#f0f0f0", highlightthickness=0)

    # --- UI制御 ---
    def _update_preset_combo(self):
        values = ["手動入力"] + [p.get("name", "名称未設定") for p in self.presets]
        self.combo_preset["values"] = values
        self.combo_preset.current(0)
        self._on_preset_selected()

    def _on_preset_selected(self, event=None):
        idx = self.combo_preset.current()
        if idx == 0:
            self.lbl_time_mode.config(text="終了時刻:")
            self.main_time_type = "end_time"
        else:
            p = self.presets[idx - 1]
            self.entry_task.delete(0, tk.END)
            self.entry_task.insert(0, p.get("task", ""))
            self.main_time_type = p.get("time_type", "end_time")
            self.lbl_time_mode.config(text="所要時間(分):" if self.main_time_type == "duration" else "終了時刻:")
            self.entry_time.delete(0, tk.END)
            self.entry_time.insert(0, str(p.get("time_val", "")))
            self.pomodoro_enabled.set(p.get("pomodoro", False))

    def _clear_dynamic_area(self):
        for widget in self.dynamic_frame.winfo_children(): widget.destroy()

    def _switch_ui_to_idle(self):
        self._clear_dynamic_area()
        self.static_frame.pack(fill="x", after=self.top_frame) 
        
        self.combo_preset.config(state="readonly")
        self.entry_task.config(state="normal")
        self.entry_time.config(state="normal")
        self.chk_pomodoro.config(state="normal")
        
        btn = tk.Button(self.dynamic_frame, text="タイマー開始", command=self.start_timer, 
                        bg="#4CAF50", fg="white", font=("Meiryo UI", 12, "bold"), pady=5)
        btn.pack(fill="x", pady=10)
        
        if self.tray_icon:
            self.tray_icon.icon = self._get_idle_icon_image()
            self.tray_icon.title = "待機中"
        
        self.root.geometry("") 
        self._apply_theme()

    def _switch_ui_to_running(self):
        self._clear_dynamic_area()
        self.static_frame.pack_forget() 
        
        self.combo_preset.config(state="disabled")
        self.entry_task.config(state="disabled")
        self.entry_time.config(state="disabled")
        self.chk_pomodoro.config(state="disabled")
        
        # --- メインタイマーUI ---
        lbl_info = tk.Label(self.dynamic_frame, text=f"予定: {self.task_name}", font=("Meiryo UI", 11))
        lbl_info.pack(pady=2)

        if self.settings["auto_milestone_enabled"]:
            self.lbl_notice = tk.Label(self.dynamic_frame, text="", font=("Meiryo UI", 9))
            self.lbl_notice.pack()
            self._update_notice_label()
        
        self.lbl_countdown = tk.Label(self.dynamic_frame, text="--:--:--", font=("Meiryo UI", 24, "bold"))
        self.lbl_countdown.pack(pady=5)

        self.canvas_bar = tk.Canvas(self.dynamic_frame, height=20, highlightthickness=0)
        self.canvas_bar.pack(fill="x", pady=(0, 5))
        
        # ドラッグ用バインド
        self.canvas_bar.bind("<ButtonPress-1>", self._on_bar_press)
        self.canvas_bar.bind("<B1-Motion>", self._on_bar_drag)
        self.canvas_bar.bind("<ButtonRelease-1>", self._on_bar_release)
        
        btn_cancel = tk.Button(self.dynamic_frame, text="停止・解除", command=self.reset_timer, bg="#ffdddd", fg="black", font=("Meiryo UI", 10))
        btn_cancel.pack(fill="x", pady=5)
        
        # --- ポモドーロ専用UI ---
        if self.is_pomodoro:
            self.pomo_frame_run = tk.Frame(self.dynamic_frame)
            self.pomo_frame_run.pack(fill="x", pady=(10, 0))
            
            self.lbl_pomo_status = tk.Label(self.pomo_frame_run, text="", font=("Meiryo UI", 10, "bold"))
            self.lbl_pomo_status.pack(pady=(0, 2))
            
            self.canvas_pomo_bar = tk.Canvas(self.pomo_frame_run, height=12, highlightthickness=0)
            self.canvas_pomo_bar.pack(fill="x", pady=(0, 5))
            
            btn_pomo_reset = tk.Button(self.pomo_frame_run, text="ポモドーロリセット", command=self.reset_pomodoro, font=("Meiryo UI", 9))
            btn_pomo_reset.pack(fill="x", pady=(2, 0))
            
            self._update_pomo_label(0)
        
        self.root.attributes("-alpha", self.settings["opacity"])
        self.root.geometry("") 
        self._apply_theme()
        self._draw_main_bar()
        if self.is_pomodoro:
            self._draw_pomo_bar()

    def _update_notice_label(self):
        if not hasattr(self, 'lbl_notice') or not self.lbl_notice.winfo_exists(): return
        if not self.settings["auto_milestone_enabled"]: return
        
        if self.milestone_done:
            self.lbl_notice.config(text="※お知らせの時間を通過しました")
        else:
            total_sec = (self.target_datetime - self.start_datetime).total_seconds()
            rem_percent = 100 - self.settings["auto_milestone_percent"]
            rem_min = int((total_sec * (rem_percent / 100.0)) / 60)
            self.lbl_notice.config(text=f"※残り時間が{rem_min}分になったら一度お知らせします")

    def _update_pomo_label(self, rem_sec):
        if not hasattr(self, 'lbl_pomo_status') or not self.lbl_pomo_status.winfo_exists(): return
        pm, ps = divmod(int(max(0, rem_sec)), 60)
        phase_str = "作業中" if self.pomo_phase == "WORK" else "休憩中"
        color = "#ff8c00" if self.pomo_phase == "WORK" else "#00bfff"
        self.lbl_pomo_status.config(text=f"[Pomo: {self.pomodoro_count}回目] {phase_str} - {pm:02d}:{ps:02d}", fg=color)

    def _open_settings(self):
        SettingsDialog(self.root, self)

    def _open_preset_manager(self):
        PresetManagerDialog(self.root, self)

    # --- タイマーロジック ---
    def _parse_time_input(self, time_str):
        time_str = time_str.translate(str.maketrans({chr(0xFF10 + i): chr(0x30 + i) for i in range(10)}))
        time_str = time_str.strip()
        match_colon = re.match(r"^(\d{1,2})[:：](\d{1,2})$", time_str)
        if match_colon: return int(match_colon.group(1)), int(match_colon.group(2))
        match_digits = re.match(r"^(\d{3,4})$", time_str)
        if match_digits:
            val = int(match_digits.group(1))
            return val // 100, val % 100
        raise ValueError("時刻形式不明")

    def reset_pomodoro(self):
        debug_log("ポモドーロリセット実行")
        self.pomodoro_count = 1
        if self.is_running and self.is_pomodoro:
            self._start_pomodoro_phase("WORK")
            self._draw_pomo_bar()

    def start_timer(self):
        debug_log("タイマー開始要求")
        self.milestone_done = False
        try:
            now = datetime.datetime.now()
            self.task_name = self.entry_task.get()
            
            if self.main_time_type == "duration":
                try:
                    mins = int(self.entry_time.get().strip())
                    if mins <= 0: raise ValueError
                except:
                    raise ValueError("所要時間は正の整数で入力してください")
                target = now + datetime.timedelta(minutes=mins)
            else:
                hour, minute = self._parse_time_input(self.entry_time.get())
                if not (0 <= hour <= 23 and 0 <= minute <= 59): raise ValueError("時刻範囲外")
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now: target += datetime.timedelta(days=1)

            self.start_datetime = now
            self.target_datetime = target
            self.is_running = True
            self.is_pomodoro = self.pomodoro_enabled.get()

            if self.is_pomodoro:
                self.pomodoro_count = 1
                self._start_pomodoro_phase("WORK")

            debug_log(f"開始: 目標={target.strftime('%Y-%m-%d %H:%M:%S')}")
            self._switch_ui_to_running()
            self._update_countdown_loop()
        except ValueError as e: 
            msg = str(e) if str(e) != "時刻形式不明" else "時刻を正しく入力してください（例: 1430）"
            messagebox.showerror("入力エラー", msg)
        except Exception as e: 
            messagebox.showerror("エラー", f"予期せぬエラー: {e}")

    def _start_pomodoro_phase(self, phase):
        now = datetime.datetime.now()
        self.pomo_phase = phase
        mins = self.settings["pomo_work_min"] if phase == "WORK" else self.settings["pomo_break_min"]
        self.pomo_target_datetime = now + datetime.timedelta(minutes=mins)

    def _update_countdown_loop(self):
        if not self.is_running: return
        now = datetime.datetime.now()
        overall_remaining = (self.target_datetime - now).total_seconds()
        
        self._draw_main_bar()

        # マイルストーン（途中お知らせ）チェック
        if self.settings["auto_milestone_enabled"] and not self.milestone_done:
            total = (self.target_datetime - self.start_datetime).total_seconds()
            elapsed = (now - self.start_datetime).total_seconds()
            if total > 0 and (elapsed / total) >= (self.settings["auto_milestone_percent"] / 100.0):
                self.milestone_done = True
                self._update_notice_label()
                self._trigger_milestone_flash()

        # ポモドーロの更新・フェーズ切り替えチェック
        if self.is_pomodoro and overall_remaining > 0:
            pomo_rem = (self.pomo_target_datetime - now).total_seconds()
            if pomo_rem <= 0:
                next_phase = "BREAK" if self.pomo_phase == "WORK" else "WORK"
                if next_phase == "WORK": self.pomodoro_count += 1
                self._start_pomodoro_phase(next_phase)
                self._play_mini_alert()
                pomo_rem = (self.pomo_target_datetime - now).total_seconds()
                
            self._update_pomo_label(pomo_rem)
            self._draw_pomo_bar()

        if overall_remaining > 0:
            self._update_tray_status(overall_remaining)
            safe_seconds = int(max(0, overall_remaining))
            h, rem = divmod(safe_seconds, 3600)
            m, s = divmod(rem, 60)
            time_str = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
            
            self.lbl_countdown.config(text=time_str)
            self.root.after(1000, self._update_countdown_loop)
        else:
            self.lbl_countdown.config(text="00:00:00")
            self._update_tray_status(0)
            self._trigger_alarm()

    def _trigger_milestone_flash(self):
        debug_log("途中お知らせ発動")
        
        if self.settings["sound_enabled"]:
            winsound.MessageBeep(winsound.MB_OK)
            
        def _flash(count=0):
            if count >= 4:
                self._apply_theme()
                return
            bg = "#ffff99" if count % 2 == 0 else self.COLOR_NORMAL
            self.root.config(bg=bg)
            self.dynamic_frame.config(bg=bg)
            self.root.after(200, lambda: _flash(count + 1))
        _flash()

    def _play_mini_alert(self):
        if not self.settings["sound_enabled"]: return
        threading.Thread(target=lambda: winsound.Beep(1200, 200), daemon=True).start()

    # --- プログレスバー描画・操作 ---
    def _on_bar_press(self, event):
        if not self.settings["auto_milestone_enabled"]: return
        w = self.canvas_bar.winfo_width()
        rem_percent = 100 - self.settings["auto_milestone_percent"]
        mx = (rem_percent / 100.0) * w
        # マーカー付近(±15px)をクリックしたらドラッグ開始
        if abs(event.x - mx) <= 15:
            self.is_dragging_marker = True

    def _on_bar_drag(self, event):
        if getattr(self, 'is_dragging_marker', False):
            w = self.canvas_bar.winfo_width()
            if w <= 0: return
            
            # X座標を「残り時間の割合」として計算
            rem_percent = int(max(0, min(100, (event.x / w) * 100)))
            # 内部の「経過割合(%)」に変換して保存
            self.settings["auto_milestone_percent"] = 100 - rem_percent
            
            total = (self.target_datetime - self.start_datetime).total_seconds()
            elapsed = (datetime.datetime.now() - self.start_datetime).total_seconds()
            current_percent = (elapsed / total) * 100 if total > 0 else 0
            
            # マーカーを現在時刻より未来（右側）に動かした場合は、発動フラグをリセット
            if self.settings["auto_milestone_percent"] > current_percent:
                self.milestone_done = False
                
            self._update_notice_label()
            self._draw_main_bar()

    def _on_bar_release(self, event):
        if getattr(self, 'is_dragging_marker', False):
            self.is_dragging_marker = False
            self.save_settings()

    def _draw_main_bar(self):
        if not hasattr(self, 'canvas_bar') or not self.canvas_bar.winfo_exists(): return
        self.canvas_bar.delete("all")
        w = self.canvas_bar.winfo_width()
        h = self.canvas_bar.winfo_height()
        if w <= 1: return 
            
        bw = w / 20
        now = datetime.datetime.now()
        total = (self.target_datetime - self.start_datetime).total_seconds()
        rem = (self.target_datetime - now).total_seconds()
        
        ratio = max(0, min(1, rem / total)) if total > 0 else 0
        visible_blocks = int(math.ceil(ratio * 20))
        bg_col = "#404040" if self.settings["theme"]=="Dark" else "#DDDDDD"
        
        for i in range(20):
            x1 = i * bw + 1
            x2 = (i + 1) * bw - 1
            y1 = 0
            y2 = h
            
            if i < 5: color = "#E74C3C" 
            elif i < 10: color = "#F39C12" 
            elif i < 15: color = "#2ECC71" 
            else: color = "#3498DB" 
            
            fill_color = color if i < visible_blocks else bg_col
            self.canvas_bar.create_rectangle(x1, y1, x2, y2, fill=fill_color, outline="")

        if self.settings["auto_milestone_enabled"]:
            # マーカーのX座標を「残り時間の割合」として配置する
            rem_percent = 100 - self.settings["auto_milestone_percent"]
            mx = (rem_percent / 100.0) * w
            marker_col = "#ffffff" if self.settings["theme"]=="Dark" else "#333333"
            self.canvas_bar.create_polygon(mx, h/2 + 2, mx-6, 0, mx+6, 0, fill=marker_col)

    def _draw_pomo_bar(self):
        if not hasattr(self, 'canvas_pomo_bar') or not self.canvas_pomo_bar.winfo_exists(): return
        self.canvas_pomo_bar.delete("all")
        w = self.canvas_pomo_bar.winfo_width()
        h = self.canvas_pomo_bar.winfo_height()
        if w <= 1: return 
        
        now = datetime.datetime.now()
        mins = self.settings["pomo_work_min"] if self.pomo_phase == "WORK" else self.settings["pomo_break_min"]
        total = mins * 60
        rem = max(0, (self.pomo_target_datetime - now).total_seconds())
        
        ratio = max(0, min(1, rem / total)) if total > 0 else 0
        bw = w / 20
        visible_blocks = int(math.ceil(ratio * 20))
        bg_col = "#404040" if self.settings["theme"]=="Dark" else "#DDDDDD"

        for i in range(20):
            x1 = i * bw + 1
            x2 = (i + 1) * bw - 1
            
            # 通常タイマーと同じ色分け
            if i < 5: color = "#E74C3C" 
            elif i < 10: color = "#F39C12" 
            elif i < 15: color = "#2ECC71" 
            else: color = "#3498DB" 
            
            fill_color = color if i < visible_blocks else bg_col
            self.canvas_pomo_bar.create_rectangle(x1, 0, x2, h, fill=fill_color, outline="")

    # --- アラーム処理 ---
    def _trigger_alarm(self):
        debug_log("終了アラーム発動")
        self.is_running = False
        self.is_alarming = True
            
        self._write_log()
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 1.0)
        self.root.focus_force()

        self.static_frame.pack_forget()
        self.dynamic_frame.pack_forget()
        self.top_frame.pack_forget()
        
        self.alarm_frame = tk.Frame(self.root, bg=self.COLOR_WARN)
        self.alarm_frame.pack(expand=True, fill="both")

        tk.Label(self.alarm_frame, text="Time's Up!", font=("Meiryo UI", 16), bg=self.COLOR_WARN, fg="white").pack(pady=(20, 5))
        tk.Label(self.alarm_frame, text=self.task_name, font=("Meiryo UI", 24, "bold"), bg=self.COLOR_WARN, fg="white", wraplength=300).pack(pady=5)

        btn_stop = tk.Button(self.alarm_frame, text="停止 (Enter)", font=("Meiryo UI", 14, "bold"), command=self.stop_alarm, width=15, bg="#ffffff", fg="black")
        btn_stop.pack(pady=20)
        btn_stop.focus_set()
        self.root.bind('<Return>', lambda e: self.stop_alarm())

        self.root.geometry("")
        self._start_flashing()
        if self.settings["sound_enabled"]: 
            threading.Thread(target=self._sound_loop, daemon=True).start()
        
        self.alarm_stop_id = self.root.after(10000, self._auto_stop_alarm_effects)

    def _auto_stop_alarm_effects(self):
        self.is_alarming = False

    def stop_alarm(self):
        self.is_alarming = False
        if self.alarm_stop_id:
            self.root.after_cancel(self.alarm_stop_id)
            self.alarm_stop_id = None
        self.root.unbind('<Return>')
        if hasattr(self, 'alarm_frame') and self.alarm_frame.winfo_exists():
            self.alarm_frame.destroy()
        
        self.top_frame.pack(fill="x", padx=5, pady=5)
        self.dynamic_frame.pack(fill="both", expand=True, pady=(0, 10))
        self._apply_base_settings()
        self._switch_ui_to_idle()

    def reset_timer(self):
        self.is_running = False
        self._apply_base_settings()
        self._switch_ui_to_idle()

    def _sound_loop(self):
        pattern = self.settings["sound_pattern"]
        while self.is_alarming:
            if "ブザー" in pattern: winsound.Beep(880, 400); self._wait_with_check(0.4)
            elif "低音" in pattern: winsound.Beep(440, 300); self._wait_with_check(0.5)
            elif "Windows" in pattern: winsound.MessageBeep(winsound.MB_ICONASTERISK); self._wait_with_check(1.0)
            elif "アラーム" in pattern:
                winsound.Beep(1000, 50); self._wait_with_check(0.1)
                if not self.is_alarming: break
                winsound.Beep(1000, 50); self._wait_with_check(0.8)
            else: winsound.Beep(880, 400); self._wait_with_check(0.4)

    def _wait_with_check(self, seconds):
        start = time.time()
        while time.time() - start < seconds:
            if not self.is_alarming: return
            time.sleep(0.1)

    def _start_flashing(self):
        if not hasattr(self, 'alarm_frame') or not self.alarm_frame.winfo_exists(): return
        if not self.is_alarming:
            try: self.alarm_frame.config(bg=self.COLOR_NORMAL)
            except: pass
            return
        try:
            cur = self.alarm_frame.cget("bg")
            nxt = self.COLOR_NORMAL if cur == self.COLOR_WARN else self.COLOR_WARN
            self.alarm_frame.config(bg=nxt)
            for child in self.alarm_frame.winfo_children():
                if isinstance(child, tk.Label): child.config(bg=nxt)
            self.root.after(500, self._start_flashing)
        except: return

    def _write_log(self):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{now_str}] 完了: {self.task_name}\n")
        except: pass

    # --- トレイアイコン ---
    def _init_tray_icon(self):
        image = self._get_idle_icon_image()
        menu = pystray.Menu(pystray.MenuItem("開く", self._show_window), pystray.MenuItem("終了", self._quit_app))
        self.tray_icon = pystray.Icon("SimpleTimer", image, "待機中", menu)
        self.icon_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.icon_thread.start()

    def _get_idle_icon_image(self):
        if os.path.exists(self.icon_file):
            try: return Image.open(self.icon_file)
            except: pass
        img = Image.new('RGB', (64, 64), color=self.COLOR_IDLE_ICON)
        ImageDraw.Draw(img).ellipse((8, 8, 56, 56), outline="white", width=3)
        return img

    def _create_icon_image(self, text, bg_color):
        img = Image.new('RGB', (64, 64), color=bg_color)
        draw = ImageDraw.Draw(img)
        try: font = ImageFont.truetype("arialbd.ttf", 40)
        except: font = ImageFont.load_default()
        try:
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
            draw.text(((64-(right-left))//2, (64-(bottom-top))//2), text, font=font, fill="white")
        except: pass
        return img

    def _update_tray_status(self, rem_sec):
        if self.tray_icon is None or self.is_quitting: return
        bg = self.COLOR_WARN_ICON if rem_sec <= 300 else self.COLOR_SAFE_ICON
        if rem_sec > 60:
            m = int(rem_sec // 60)
            txt, tooltip = ("99+", f"あと {m}分") if m >= 100 else (str(m), f"あと {m}分")
        else:
            txt, tooltip = (str(int(rem_sec)), f"あと {int(rem_sec)}秒")
        try:
            self.tray_icon.icon = self._create_icon_image(txt, bg)
            self.tray_icon.title = tooltip
        except: pass

    def _on_close_window(self): self.root.withdraw()
    def _show_window(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify)
        self.root.after(0, self.root.lift)
    def _quit_app(self, icon=None, item=None):
        self.is_quitting = True; self.is_running = False
        if self.tray_icon: self.tray_icon.stop()
        self.root.after(0, self.root.destroy)
        self.root.after(0, sys.exit)


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("設定")
        self.geometry("320x350")
        self.attributes("-topmost", True)
        self.grab_set()
        
        # 画面のテーマ適用
        bg_col = "#2b2b2b" if app.settings["theme"] == "Dark" else "#f0f0f0"
        fg_col = "#ffffff" if app.settings["theme"] == "Dark" else "#000000"
        self.config(bg=bg_col)

        self.var_topmost = tk.BooleanVar(value=app.settings["topmost"])
        self.var_theme = tk.StringVar(value=app.settings["theme"])
        self.var_sound_on = tk.BooleanVar(value=app.settings["sound_enabled"])
        self.var_sound_pat = tk.StringVar(value=app.settings["sound_pattern"])
        self.var_opacity = tk.DoubleVar(value=app.settings["opacity"])
        self.var_pomo_w = tk.IntVar(value=app.settings["pomo_work_min"])
        self.var_pomo_b = tk.IntVar(value=app.settings["pomo_break_min"])
        self.var_mile_on = tk.BooleanVar(value=app.settings["auto_milestone_enabled"])
        self.var_mile_per = tk.IntVar(value=app.settings["auto_milestone_percent"])

        f = tk.Frame(self, padx=15, pady=10, bg=bg_col)
        f.pack(fill="both", expand=True)
        
        def _lbl(r, c, txt):
            lbl = tk.Label(f, text=txt, bg=bg_col, fg=fg_col)
            lbl.grid(row=r, column=c, sticky="e", pady=4)

        _lbl(0, 0, "最前面表示:")
        tk.Checkbutton(f, text="ON", variable=self.var_topmost, bg=bg_col, fg=fg_col, selectcolor=bg_col).grid(row=0, column=1, sticky="w")
        
        _lbl(1, 0, "テーマ:")
        ttk.Combobox(f, textvariable=self.var_theme, values=["Light", "Dark"], state="readonly", width=10).grid(row=1, column=1, sticky="w")
        
        _lbl(2, 0, "タイマー中透過度:")
        tk.Scale(f, variable=self.var_opacity, from_=0.1, to=1.0, resolution=0.1, orient="horizontal", 
                 showvalue=0, bg=bg_col, fg=fg_col).grid(row=2, column=1, sticky="w")

        _lbl(3, 0, "通知音:")
        sf = tk.Frame(f, bg=bg_col)
        sf.grid(row=3, column=1, sticky="w")
        tk.Checkbutton(sf, text="ON", variable=self.var_sound_on, bg=bg_col, fg=fg_col, selectcolor=bg_col).pack(side="left")
        ttk.Combobox(sf, textvariable=self.var_sound_pat, values=["ブザー(標準)", "低音(控えめ)", "Windows通知", "アラーム(ピッピッ)"], 
                     state="readonly", width=12).pack(side="left")
        tk.Button(sf, text="テスト", command=self._test_sound, font=("Meiryo UI", 8)).pack(side="left", padx=5)

        _lbl(4, 0, "Pomo(作業/休憩):")
        pf = tk.Frame(f, bg=bg_col)
        pf.grid(row=4, column=1, sticky="w")
        tk.Entry(pf, textvariable=self.var_pomo_w, width=4).pack(side="left")
        tk.Label(pf, text="分 / ", bg=bg_col, fg=fg_col).pack(side="left")
        tk.Entry(pf, textvariable=self.var_pomo_b, width=4).pack(side="left")
        tk.Label(pf, text="分", bg=bg_col, fg=fg_col).pack(side="left")

        _lbl(5, 0, "途中お知らせ:")
        mf = tk.Frame(f, bg=bg_col)
        mf.grid(row=5, column=1, sticky="w")
        tk.Checkbutton(mf, text="ON", variable=self.var_mile_on, bg=bg_col, fg=fg_col, selectcolor=bg_col).pack(side="left")
        tk.Entry(mf, textvariable=self.var_mile_per, width=4).pack(side="left")
        tk.Label(mf, text="% 経過時", bg=bg_col, fg=fg_col).pack(side="left")

        bf = tk.Frame(self, pady=10, bg=bg_col)
        bf.pack(fill="x")
        tk.Button(bf, text="保存して適用", command=self._save, width=15).pack()

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
        s["opacity"] = self.var_opacity.get()
        try:
            s["pomo_work_min"] = max(1, self.var_pomo_w.get())
            s["pomo_break_min"] = max(1, self.var_pomo_b.get())
            s["auto_milestone_percent"] = max(1, min(99, self.var_mile_per.get()))
        except: pass
        s["auto_milestone_enabled"] = self.var_mile_on.get()
        
        self.app.save_settings()
        self.destroy()

class PresetManagerDialog(tk.Toplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("プリセット管理")
        self.geometry("340x300")
        self.attributes("-topmost", True)
        self.grab_set()

        frame_list = tk.Frame(self, padx=10, pady=10)
        frame_list.pack(fill="both", expand=True)

        scrollbar = tk.Scrollbar(frame_list)
        scrollbar.pack(side="right", fill="y")
        self.listbox = tk.Listbox(frame_list, yscrollcommand=scrollbar.set, font=("Meiryo UI", 10))
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)

        btn_frame = tk.Frame(self, padx=10, pady=10)
        btn_frame.pack(fill="x")
        
        tk.Button(btn_frame, text="追加", width=6, command=self._add).pack(side="left", padx=2)
        tk.Button(btn_frame, text="編集", width=6, command=self._edit).pack(side="left", padx=2)
        tk.Button(btn_frame, text="削除", width=6, command=self._del).pack(side="left", padx=2)
        tk.Button(btn_frame, text="閉じる", command=self.destroy).pack(side="right")
        self._refresh_list()

    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for p in self.app.presets: self.listbox.insert(tk.END, p.get("name", "無名"))

    def _get_idx(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("確認", "対象を選択してください", parent=self)
            return None
        return sel[0]

    def _add(self): PresetEditDialog(self, self.app, None)
    def _edit(self):
        idx = self._get_idx()
        if idx is not None: PresetEditDialog(self, self.app, idx)
    def _del(self):
        idx = self._get_idx()
        if idx is not None:
            if messagebox.askyesno("確認", "削除しますか？", parent=self):
                del self.app.presets[idx]
                self.app.save_presets()
                self._refresh_list()
                self.app._update_preset_combo()

class PresetEditDialog(tk.Toplevel):
    def __init__(self, parent, app, index=None):
        super().__init__(parent)
        self.app = app
        self.parent_dialog = parent
        self.index = index
        self.title("プリセット編集")
        self.geometry("300x250")
        self.attributes("-topmost", True)
        self.grab_set()

        self.var_name = tk.StringVar()
        self.var_task = tk.StringVar()
        self.var_time_type = tk.StringVar(value="end_time")
        self.var_time_val = tk.StringVar()
        self.var_pomo = tk.BooleanVar(value=False)

        if index is not None:
            p = self.app.presets[index]
            self.var_name.set(p.get("name", ""))
            self.var_task.set(p.get("task", ""))
            self.var_time_type.set(p.get("time_type", "end_time"))
            self.var_time_val.set(str(p.get("time_val", "")))
            self.var_pomo.set(p.get("pomodoro", False))

        f = tk.Frame(self, padx=15, pady=15)
        f.pack(fill="both", expand=True)

        tk.Label(f, text="プリセット名:").grid(row=0, column=0, sticky="e", pady=5)
        tk.Entry(f, textvariable=self.var_name, width=20).grid(row=0, column=1, sticky="w", pady=5)

        tk.Label(f, text="用件:").grid(row=1, column=0, sticky="e", pady=5)
        tk.Entry(f, textvariable=self.var_task, width=20).grid(row=1, column=1, sticky="w", pady=5)

        tk.Label(f, text="時間指定:").grid(row=2, column=0, sticky="e", pady=5)
        rf = tk.Frame(f)
        rf.grid(row=2, column=1, sticky="w")
        tk.Radiobutton(rf, text="終了時刻", variable=self.var_time_type, value="end_time").pack(side="left")
        tk.Radiobutton(rf, text="所要時間", variable=self.var_time_type, value="duration").pack(side="left")

        tk.Label(f, text="値(例1430/30):").grid(row=3, column=0, sticky="e", pady=5)
        tk.Entry(f, textvariable=self.var_time_val, width=10).grid(row=3, column=1, sticky="w", pady=5)

        tk.Label(f, text="ポモドーロ:").grid(row=4, column=0, sticky="e", pady=5)
        tk.Checkbutton(f, text="ONにする", variable=self.var_pomo).grid(row=4, column=1, sticky="w", pady=5)

        bf = tk.Frame(self, pady=10)
        bf.pack(fill="x")
        tk.Button(bf, text="保存", command=self._save, width=10).pack(side="left", expand=True)
        tk.Button(bf, text="キャンセル", command=self.destroy, width=10).pack(side="left", expand=True)

    def _save(self):
        name = self.var_name.get().strip()
        if not name: return
        new_data = {
            "name": name, "task": self.var_task.get(),
            "time_type": self.var_time_type.get(), "time_val": self.var_time_val.get().strip(),
            "pomodoro": self.var_pomo.get()
        }
        if self.index is None: self.app.presets.append(new_data)
        else: self.app.presets[self.index] = new_data
        self.app.save_presets()
        self.parent_dialog._refresh_list()
        self.app._update_preset_combo()
        self.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = SimpleTimer(root)
    root.mainloop()