#SimpleTimer.py

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

# 外部ライブラリのインポートチェック
try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("ライブラリ不足", f"起動に必要なライブラリが見つかりません。\n以下のコマンドを実行してください:\n\npip install pystray Pillow\n\nエラー詳細: {e}")
    sys.exit(1)

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class SimpleTimer:
    def __init__(self, root):
        self.root = root
        self.root.title("SimpleTimer")
        
        self.icon_file = resource_path("timer.ico")
        if os.path.exists(self.icon_file):
            try:
                self.root.iconbitmap(default=self.icon_file)
            except: pass

        self.root.attributes("-topmost", True)
        self.root.minsize(350, 240)
        
        self.is_running = False
        self.start_datetime = None
        self.target_datetime = None
        self.task_name = ""
        self.is_alarming = False
        self.log_file = "timer_log.txt"
        
        # ポモドーロ・マイルストーン関連
        self.pomodoro_enabled = tk.BooleanVar(value=False)
        self.is_pomodoro = False
        self.pomodoro_phase = "IDLE"
        self.pomodoro_count = 0
        self.milestones = set()

        self.sound_enabled = tk.BooleanVar(value=True)
        self.opacity_val = tk.DoubleVar(value=0.6) 
        self.sound_pattern = tk.StringVar(value="ブザー(標準)")
        
        self.tray_icon = None
        self.icon_thread = None
        self.is_quitting = False 

        self.COLOR_NORMAL = "#f0f0f0" 
        self.COLOR_WARN = "#FF6347"   
        self.COLOR_SAFE_ICON = "#228B22" 
        self.COLOR_WARN_ICON = "#DC143C"
        self.COLOR_IDLE_ICON = "#808080"

        self._setup_structure()
        self._switch_ui_to_idle()
        self._center_window_initial()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close_window)
        self._init_tray_icon()

    def _center_window_initial(self):
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        height = self.root.winfo_reqheight()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        self.root.geometry(f"+{x}+{y}")

    def _setup_structure(self):
        self.static_frame = tk.Frame(self.root, padx=10, pady=10)
        self.static_frame.pack(fill="x")

        row1 = tk.Frame(self.static_frame)
        row1.pack(fill="x", pady=(0, 5))
        tk.Label(row1, text="用件:", font=("Meiryo UI", 10)).pack(side="left")
        self.entry_task = tk.Entry(row1, font=("Meiryo UI", 10))
        self.entry_task.insert(0, "作業")
        self.entry_task.pack(side="left", padx=5, fill="x", expand=True)

        self.chk_pomodoro = tk.Checkbutton(row1, text="ポモドーロ(25m/5m)", variable=self.pomodoro_enabled, font=("Meiryo UI", 9), command=self._toggle_pomodoro)
        self.chk_pomodoro.pack(side="right")

        row2 = tk.Frame(self.static_frame)
        row2.pack(fill="x", pady=(0, 5))
        tk.Label(row2, text="終了時刻:", font=("Meiryo UI", 10)).pack(side="left")
        self.entry_time = tk.Entry(row2, width=8, font=("Meiryo UI", 14))
        self.entry_time.insert(0, datetime.datetime.now().strftime("%H:%M"))
        self.entry_time.pack(side="left", padx=5)
        tk.Label(row2, text="(例 1430)", font=("Meiryo UI", 9), fg="gray").pack(side="left")

        opt_frame = tk.Frame(self.static_frame)
        opt_frame.pack(fill="x", pady=(5, 0))
        
        sound_frame = tk.LabelFrame(opt_frame, text="通知音設定", font=("Meiryo UI", 8), padx=5, pady=2)
        sound_frame.pack(fill="x", pady=(0, 5))
        
        self.chk_sound = tk.Checkbutton(sound_frame, text="ON", variable=self.sound_enabled, font=("Meiryo UI", 9))
        self.chk_sound.pack(side="left")

        self.combo_sound = ttk.Combobox(sound_frame, textvariable=self.sound_pattern, 
                                      values=["ブザー(標準)", "低音(控えめ)", "Windows通知", "アラーム(ピッピッ)",
                                              "レトロ(テレレレ♪)", "駅メロ(SH-1風)", "水滴(ピロリロ)"], 
                                      state="readonly", width=16, font=("Meiryo UI", 9))
        self.combo_sound.pack(side="left", padx=5)

        alpha_frame = tk.Frame(opt_frame)
        alpha_frame.pack(fill="x")
        tk.Label(alpha_frame, text="透過:", font=("Meiryo UI", 9)).pack(side="left")
        self.scale_opacity = tk.Scale(alpha_frame, variable=self.opacity_val, from_=0.1, to=1.0, 
                                    resolution=0.1, orient="horizontal", showvalue=0, length=100,
                                    command=self._on_opacity_change)
        self.scale_opacity.pack(side="left")
        tk.Label(alpha_frame, text="(右=濃)", font=("Meiryo UI", 8), fg="gray").pack(side="left")

        self.dynamic_frame = tk.Frame(self.root, padx=10) 
        self.dynamic_frame.pack(fill="both", expand=True, pady=(0, 10))

    def _toggle_pomodoro(self):
        if self.pomodoro_enabled.get():
            self.entry_time.config(state="disabled")
        else:
            self.entry_time.config(state="normal")

    def _clear_dynamic_area(self):
        for widget in self.dynamic_frame.winfo_children(): widget.destroy()
    
    def _autosize_window(self):
        self.root.geometry("") 

    def _switch_ui_to_idle(self):
        self._clear_dynamic_area()
        self.entry_task.config(state="normal")
        self.chk_pomodoro.config(state="normal")
        self._toggle_pomodoro()
        self.chk_sound.config(state="normal")
        self.combo_sound.config(state="readonly")
        
        btn = tk.Button(self.dynamic_frame, text="タイマー開始", command=self.start_timer, 
                        bg="#e1e1e1", font=("Meiryo UI", 12, "bold"), pady=5)
        btn.pack(fill="x", pady=10)
        
        if self.tray_icon:
            self.tray_icon.icon = self._get_idle_icon_image()
            self.tray_icon.title = "待機中"
        self._autosize_window()

    def _switch_ui_to_running(self):
        self._clear_dynamic_area()
        self.entry_task.config(state="disabled")
        self.entry_time.config(state="disabled")
        self.chk_sound.config(state="disabled")
        self.combo_sound.config(state="disabled")
        self.chk_pomodoro.config(state="disabled")
        
        lbl_info = tk.Label(self.dynamic_frame, text=f"予定: {self.task_name}", font=("Meiryo UI", 11))
        lbl_info.pack(pady=2)
        
        target_str = self.target_datetime.strftime("%H:%M")
        lbl_target = tk.Label(self.dynamic_frame, text=f"目標: {target_str}", font=("Meiryo UI", 10), fg="#666666")
        lbl_target.pack()
        
        self.lbl_countdown = tk.Label(self.dynamic_frame, text="--:--:--", font=("Meiryo UI", 24, "bold"), fg="#333333")
        self.lbl_countdown.pack(pady=5)

        self.canvas_bar = tk.Canvas(self.dynamic_frame, height=40, bg=self.COLOR_NORMAL, highlightthickness=0)
        self.canvas_bar.pack(fill="x", pady=(0, 10))
        self.canvas_bar.bind("<Button-1>", self._on_canvas_click)
        
        btn_cancel = tk.Button(self.dynamic_frame, text="停止・解除", command=self.reset_timer, bg="#ffdddd", font=("Meiryo UI", 10))
        btn_cancel.pack(fill="x", pady=5)
        
        self.root.attributes("-alpha", self.opacity_val.get())
        self._autosize_window()
        self.root.after(50, self._draw_bar)

    def _trigger_alarm_ui(self):
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 1.0)
        self.root.focus_force()

        self.static_frame.pack_forget()
        self.dynamic_frame.pack_forget()
        
        self.alarm_frame = tk.Frame(self.root, bg=self.COLOR_WARN)
        self.alarm_frame.pack(expand=True, fill="both")

        tk.Label(self.alarm_frame, text="Time's Up!", font=("Meiryo UI", 16), bg=self.COLOR_WARN).pack(pady=(20, 5))
        tk.Label(self.alarm_frame, text=self.task_name, font=("Meiryo UI", 24, "bold"), bg=self.COLOR_WARN, wraplength=300).pack(pady=5)

        if self.is_pomodoro:
            if self.pomodoro_phase == "WORK":
                btn_text = "休憩(5分)を開始 (Enter)"
                next_action = self.start_pomodoro_break
            else:
                btn_text = "次の作業を開始 (Enter)"
                next_action = self.start_pomodoro_work
                
            btn_next = tk.Button(self.alarm_frame, text=btn_text, font=("Meiryo UI", 14, "bold"), command=next_action, bg="#ffffff")
            btn_next.pack(pady=10)
            self.root.bind('<Return>', lambda e: next_action())
            
            btn_stop = tk.Button(self.alarm_frame, text="終了して戻る", command=self.stop_alarm, font=("Meiryo UI", 10), bg="#ffdddd")
            btn_stop.pack(pady=5)
            btn_next.focus_set()
        else:
            btn_stop = tk.Button(self.alarm_frame, text="停止 (Enter)", font=("Meiryo UI", 14, "bold"), command=self.stop_alarm, width=15, bg="#ffffff")
            btn_stop.pack(pady=20)
            btn_stop.focus_set()
            self.root.bind('<Return>', lambda e: self.stop_alarm())

        self._autosize_window()

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

    def start_timer(self):
        self.milestones.clear()
        if self.pomodoro_enabled.get():
            self.is_pomodoro = True
            self.pomodoro_count = 0
            self.start_pomodoro_work()
        else:
            self.is_pomodoro = False
            try:
                hour, minute = self._parse_time_input(self.entry_time.get())
                if not (0 <= hour <= 23 and 0 <= minute <= 59): raise ValueError("時刻範囲外")

                self.task_name = self.entry_task.get()
                now = datetime.datetime.now()
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now: target += datetime.timedelta(days=1)

                self.start_datetime = now
                self.target_datetime = target
                self.is_running = True
                self._switch_ui_to_running()
                self._update_countdown_loop()
            except ValueError: messagebox.showerror("入力エラー", "時刻を正しく入力してください（例: 1430）")
            except Exception as e: messagebox.showerror("エラー", f"予期せぬエラー: {e}")

    def start_pomodoro_work(self):
        self.pomodoro_phase = "WORK"
        self.pomodoro_count += 1
        base_task = self.entry_task.get() or "作業"
        self._start_internal(minutes=25, task_name=f"{base_task} (ポモドーロ {self.pomodoro_count}回目)")

    def start_pomodoro_break(self):
        self.pomodoro_phase = "BREAK"
        self._start_internal(minutes=5, task_name="休憩")

    def _start_internal(self, minutes, task_name):
        self._stop_alarm_silent()
        now = datetime.datetime.now()
        self.start_datetime = now
        self.target_datetime = now + datetime.timedelta(minutes=minutes)
        self.task_name = task_name
        self.is_running = True
        self.milestones.clear()
        self._switch_ui_to_running()
        self._update_countdown_loop()

    def _update_countdown_loop(self):
        if not self.is_running: return
        now = datetime.datetime.now()
        remaining = self.target_datetime - now
        total_seconds = remaining.total_seconds()

        self._draw_bar()

        if total_seconds > 0: self._update_tray_status(total_seconds)
        if total_seconds <= 0:
            self.lbl_countdown.config(text="00:00:00")
            self._update_tray_status(0)
            self._draw_bar()
            self._trigger_alarm()
        else:
            safe_seconds = int(max(0, total_seconds))
            h, rem = divmod(safe_seconds, 3600)
            m, s = divmod(rem, 60)
            time_str = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
            self.lbl_countdown.config(text=time_str)
            self.root.after(200, self._update_countdown_loop)

    def _on_canvas_click(self, event):
        if not hasattr(self, 'canvas_bar'): return
        w = self.canvas_bar.winfo_width()
        if w <= 1: return
        bw = w / 20
        idx = int(event.x // bw)
        if 0 <= idx < 20:
            if idx in self.milestones: self.milestones.remove(idx)
            else: self.milestones.add(idx)
            self._draw_bar()

    def _draw_bar(self):
        if not hasattr(self, 'canvas_bar') or not self.canvas_bar.winfo_exists(): return
        self.canvas_bar.delete("all")
        w = self.canvas_bar.winfo_width()
        h = self.canvas_bar.winfo_height()
        if w <= 1:
            self.root.after(50, self._draw_bar)
            return
            
        bw = w / 20
        now = datetime.datetime.now()
        total = (self.target_datetime - self.start_datetime).total_seconds()
        rem = (self.target_datetime - now).total_seconds()
        
        ratio = max(0, min(1, rem / total)) if total > 0 else 0
        visible_blocks = int(math.ceil(ratio * 20))
        
        for i in range(20):
            x1 = i * bw + 1
            x2 = (i + 1) * bw - 1
            y1 = 12
            y2 = h
            
            if i < 5: color = "#E74C3C" 
            elif i < 10: color = "#F39C12" 
            elif i < 15: color = "#2ECC71" 
            else: color = "#3498DB" 
            
            fill_color = color if i < visible_blocks else "#DDDDDD"
            self.canvas_bar.create_rectangle(x1, y1, x2, y2, fill=fill_color, outline="")

        for ms in self.milestones:
            mx = ms * bw + bw / 2
            self.canvas_bar.create_polygon(mx, 10, mx-6, 0, mx+6, 0, fill="#333333")
            self.canvas_bar.create_line(mx, 10, mx, h, fill="#333333", dash=(2, 2))

    def _trigger_alarm(self):
        self.is_running = False
        self.is_alarming = True
        self._write_log()
        self._trigger_alarm_ui()
        self._start_flashing()
        if self.sound_enabled.get(): threading.Thread(target=self._sound_loop, daemon=True).start()

    def _stop_alarm_silent(self):
        self.is_alarming = False
        self.root.unbind('<Return>')
        if hasattr(self, 'alarm_frame') and self.alarm_frame.winfo_exists():
            self.alarm_frame.destroy()
        self.static_frame.pack(fill="x")
        self.dynamic_frame.pack(fill="both", expand=True, pady=(0, 10))
        self.root.attributes("-alpha", 1.0)

    def stop_alarm(self):
        self._stop_alarm_silent()
        self.is_pomodoro = False
        self._switch_ui_to_idle()

    def reset_timer(self):
        self.is_running = False
        self.is_pomodoro = False
        self.root.attributes("-alpha", 1.0)
        self._switch_ui_to_idle()

    def _sound_loop(self):
        pattern = self.sound_pattern.get()
        while self.is_alarming:
            if "ブザー" in pattern: winsound.Beep(880, 400); self._wait_with_check(0.4)
            elif "低音" in pattern: winsound.Beep(440, 300); self._wait_with_check(0.5)
            elif "Windows" in pattern: winsound.MessageBeep(winsound.MB_ICONASTERISK); self._wait_with_check(1.0)
            elif "アラーム" in pattern:
                winsound.Beep(1000, 50); self._wait_with_check(0.1)
                if not self.is_alarming: break
                winsound.Beep(1000, 50); self._wait_with_check(0.8)
            elif "レトロ" in pattern:
                for note in [523, 659, 784, 1047]:
                    if not self.is_alarming: break
                    winsound.Beep(note, 100)
                self._wait_with_check(1.0)
            elif "駅メロ" in pattern:
                for note in [523, 659, 784, 1047, 1319, 1568]:
                    if not self.is_alarming: break
                    winsound.Beep(note, 120)
                self._wait_with_check(1.5)
            elif "水滴" in pattern:
                for freq, dur in [(1568, 100), (1480, 100), (1319, 100), (1175, 100), (1047, 400)]:
                    if not self.is_alarming: break
                    winsound.Beep(freq, dur)
                self._wait_with_check(2.0)
            else: winsound.Beep(880, 400); self._wait_with_check(0.4)

    def _wait_with_check(self, seconds):
        start = time.time()
        while time.time() - start < seconds:
            if not self.is_alarming: return
            time.sleep(0.05)

    def _start_flashing(self):
        if not self.is_alarming: return
        try:
            current_bg = self.alarm_frame.cget("bg")
            next_bg = self.COLOR_NORMAL if current_bg == self.COLOR_WARN else self.COLOR_WARN
            if self.tray_icon:
                icon_bg = self.COLOR_WARN_ICON if next_bg == self.COLOR_WARN else self.COLOR_SAFE_ICON
                try: self.tray_icon.icon = self._create_icon_image("!!", icon_bg)
                except: pass
            self.alarm_frame.config(bg=next_bg)
            for child in self.alarm_frame.winfo_children():
                if isinstance(child, (tk.Label, tk.Frame)): child.config(bg=next_bg)
            self.root.after(500, self._start_flashing)
        except: return

    def _write_log(self):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{now_str}] 完了: {self.task_name} (目標: {self.target_datetime})\n")
        except: pass

    def _on_opacity_change(self, value):
        if self.is_running:
            try: self.root.attributes("-alpha", float(value))
            except: pass

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
        return self._create_clock_icon()

    def _create_clock_icon(self):
        width, height = 64, 64
        image = Image.new('RGB', (width, height), color=self.COLOR_IDLE_ICON)
        draw = ImageDraw.Draw(image)
        margin = 8
        draw.ellipse((margin, margin, width-margin, height-margin), outline="white", width=3)
        cx, cy = width // 2, height // 2
        draw.line((cx, cy, cx - 10, cy - 10), fill="white", width=4)
        draw.line((cx, cy, cx + 15, cy - 15), fill="white", width=3)
        return image

    def _create_icon_image(self, text, bg_color):
        width, height = 64, 64
        image = Image.new('RGB', (width, height), color=bg_color)
        draw = ImageDraw.Draw(image)
        font_size = 40
        try: font = ImageFont.truetype("arialbd.ttf", font_size)
        except: font = ImageFont.load_default()
        
        try:
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
            text_width = right - left
            text_height = bottom - top
        except AttributeError:
            text_width, text_height = draw.textsize(text, font=font)
            
        draw.text(((width - text_width) // 2, (height - text_height) // 2), text, font=font, fill="white")
        return image

    def _update_tray_status(self, remaining_seconds):
        if self.tray_icon is None or self.is_quitting: return
        bg_color = self.COLOR_WARN_ICON if remaining_seconds <= 300 else self.COLOR_SAFE_ICON
        if remaining_seconds > 60:
            m = int(remaining_seconds // 60)
            txt = "99+" if m >= 100 else str(m)
            tooltip = f"あと {m}分"
        else:
            s = int(remaining_seconds)
            txt = str(s)
            tooltip = f"あと {s}秒"
        try:
            self.tray_icon.icon = self._create_icon_image(txt, bg_color)
            self.tray_icon.title = tooltip
        except: pass

    def _on_close_window(self): self.root.withdraw()
    def _show_window(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify); self.root.after(0, self.root.lift); self.root.after(0, self.root.focus_force)
    def _quit_app(self, icon=None, item=None):
        self.is_quitting = True; self.is_running = False
        if self.tray_icon: self.tray_icon.stop()
        self.root.after(0, self.root.destroy); self.root.after(0, sys.exit)

if __name__ == "__main__":
    root = tk.Tk()
    app = SimpleTimer(root)
    root.mainloop()
