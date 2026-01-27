# File Path: C:\Users\Public\fixed_timer.py
# Description: 再設定バグ修正済み・堅牢タイマー
# Author: Gemini (Bug fixed version)

import tkinter as tk
from tkinter import messagebox
import threading
import time
import winsound
import datetime
import re
import sys

class RobustTimer:
    def __init__(self, root):
        self.root = root
        self.root.title("確実なタイマー（修正版）")
        
        # ウィンドウ初期サイズ
        self.default_width = 500
        self.default_height = 400
        self._center_window(self.default_width, self.default_height)
        
        # 状態管理変数
        self.is_running = False
        self.target_datetime = None
        self.task_name = ""
        self.is_alarming = False
        self.log_file = "timer_log.txt"
        self.sound_enabled = tk.BooleanVar(value=True)

        # 色設定
        self.COLOR_NORMAL = "#FFFFFF" 
        self.COLOR_WARN = "#FF6347"   

        # GUI構成
        self._setup_ui()

    def _center_window(self, width, height):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _setup_ui(self):
        # メインフレーム
        self.main_frame = tk.Frame(self.root, padx=30, pady=30)
        self.main_frame.pack(expand=True, fill="both")

        # 1. 用件入力エリア
        tk.Label(self.main_frame, text="用件:", font=("Meiryo UI", 12)).pack(anchor="w")
        self.entry_task = tk.Entry(self.main_frame, width=40, font=("Meiryo UI", 12))
        self.entry_task.insert(0, "作業")
        self.entry_task.pack(pady=(0, 15), fill="x")

        # 2. 時間入力エリア
        tk.Label(self.main_frame, text="終了時刻 (例: 1430 または 14:30):", font=("Meiryo UI", 12)).pack(anchor="w")
        time_control_frame = tk.Frame(self.main_frame)
        time_control_frame.pack(fill="x", pady=(0, 20))
        
        self.entry_time = tk.Entry(time_control_frame, width=15, font=("Meiryo UI", 18))
        self.entry_time.insert(0, datetime.datetime.now().strftime("%H:%M"))
        self.entry_time.pack(side="left", padx=(0, 20))

        self.chk_sound = tk.Checkbutton(time_control_frame, text="通知音を鳴らす", 
                                      variable=self.sound_enabled, font=("Meiryo UI", 11))
        self.chk_sound.pack(side="left")

        # 3. ボタンエリア（フレームで場所を確保）
        self.button_frame = tk.Frame(self.main_frame, height=60)
        self.button_frame.pack(fill="x", pady=10)
        self.button_frame.pack_propagate(False) # 高さを固定してレイアウト崩れを防ぐ

        self.btn_start = tk.Button(self.button_frame, text="タイマーセット", 
                                 command=self.start_timer, 
                                 bg="#e1e1e1", font=("Meiryo UI", 14, "bold"))
        self.btn_start.pack(fill="both", expand=True)

        # 4. 情報表示エリア
        self.info_frame = tk.Frame(self.main_frame)
        self.info_frame.pack(fill="both", expand=True, pady=10)

        self.lbl_info = tk.Label(self.info_frame, text="", font=("Meiryo UI", 14))
        self.lbl_countdown = tk.Label(self.info_frame, text="", font=("Meiryo UI", 28, "bold"), fg="#333333")
        
        self.btn_cancel = tk.Button(self.info_frame, text="設定解除", 
                                  command=self.reset_timer, bg="#ffdddd", font=("Meiryo UI", 10))

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
        try:
            hour, minute = self._parse_time_input(self.entry_time.get())
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("時刻範囲外")

            self.task_name = self.entry_task.get()
            now = datetime.datetime.now()
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            day_offset_str = "今日"
            if target <= now:
                target += datetime.timedelta(days=1)
                day_offset_str = "明日"

            self.target_datetime = target
            
            # UI切り替え
            self.entry_task.config(state="disabled")
            self.entry_time.config(state="disabled")
            self.chk_sound.config(state="disabled")
            
            self.btn_start.pack_forget() # ボタンを隠す
            
            self.lbl_info.config(text=f"予定: {self.task_name}\n目標: {day_offset_str} {hour:02d}:{minute:02d}")
            self.lbl_info.pack(pady=5)
            self.lbl_countdown.pack(pady=10)
            self.btn_cancel.pack(fill="x", pady=5)
            
            self.is_running = True
            self._update_countdown_loop()
            
        except ValueError:
            messagebox.showerror("入力エラー", "時刻を正しく入力してください（例: 1430）")
        except Exception as e:
            messagebox.showerror("エラー", f"予期せぬエラー: {e}")

    def _update_countdown_loop(self):
        if not self.is_running: return
        now = datetime.datetime.now()
        remaining = self.target_datetime - now
        total_seconds = int(remaining.total_seconds())

        if total_seconds <= 0:
            self.lbl_countdown.config(text="00:00:00")
            self._trigger_alarm()
        else:
            h, rem = divmod(total_seconds, 3600)
            m, s = divmod(rem, 60)
            time_str = f"あと {h}時間 {m:02d}分 {s:02d}秒" if h > 0 else f"あと {m}分 {s:02d}秒"
            self.lbl_countdown.config(text=time_str)
            self.root.after(200, self._update_countdown_loop)

    def _trigger_alarm(self):
        self.is_running = False
        self.is_alarming = True
        self._write_log()

        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.focus_force()
        
        self.main_frame.pack_forget()
        self.alarm_frame = tk.Frame(self.root, bg=self.COLOR_WARN)
        self.alarm_frame.pack(expand=True, fill="both")

        tk.Label(self.alarm_frame, text=f"時間になりました", 
                 font=("Meiryo UI", 20), bg=self.COLOR_WARN).pack(pady=(60, 10))
        tk.Label(self.alarm_frame, text=self.task_name, 
                 font=("Meiryo UI", 36, "bold"), bg=self.COLOR_WARN).pack(pady=10)

        btn_frame = tk.Frame(self.alarm_frame, bg=self.COLOR_WARN)
        btn_frame.pack(pady=40)
        
        self.btn_stop = tk.Button(btn_frame, text="確認・停止 (Enter)", font=("Meiryo UI", 16, "bold"),
                  command=self.stop_alarm, width=20, height=2, bg="#ffffff")
        self.btn_stop.pack()
        self.btn_stop.focus_set()

        self.root.bind('<Return>', lambda e: self.stop_alarm())

        self._start_flashing()
        if self.sound_enabled.get():
            threading.Thread(target=self._sound_loop, daemon=True).start()

    def _start_flashing(self):
        if not self.is_alarming: return
        current_bg = self.alarm_frame.cget("bg")
        next_bg = self.COLOR_NORMAL if current_bg == self.COLOR_WARN else self.COLOR_WARN
        try:
            self.alarm_frame.config(bg=next_bg)
            for child in self.alarm_frame.winfo_children():
                if isinstance(child, (tk.Label, tk.Frame)): child.config(bg=next_bg)
        except: return
        self.root.after(500, self._start_flashing)

    def _sound_loop(self):
        while self.is_alarming:
            winsound.Beep(880, 400) 
            time.sleep(0.4) 

    def stop_alarm(self, snooze=False):
        self.is_alarming = False
        self.root.unbind('<Return>')
        self.root.attributes("-topmost", False)
        if hasattr(self, 'alarm_frame'): self.alarm_frame.destroy()
        
        self.main_frame.pack(expand=True, fill="both")
        
        # 表示のリセット
        self.lbl_info.pack_forget()
        self.lbl_countdown.pack_forget()
        self.btn_cancel.pack_forget()
        
        # スタートボタンを元の位置（button_frame内）に再表示
        self.btn_start.pack(fill="both", expand=True)
        
        self.entry_task.config(state="normal")
        self.entry_time.config(state="normal")
        self.chk_sound.config(state="normal")
        self.entry_task.focus_set()

    def reset_timer(self):
        """カウントダウン中のキャンセル処理"""
        self.is_running = False
        # 通常のstop_alarmと同じ処理を行うが、画面サイズ等は維持
        self.lbl_info.pack_forget()
        self.lbl_countdown.pack_forget()
        self.btn_cancel.pack_forget()
        
        self.btn_start.pack(fill="both", expand=True)
        
        self.entry_task.config(state="normal")
        self.entry_time.config(state="normal")
        self.chk_sound.config(state="normal")

    def _write_log(self):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        target_str = self.target_datetime.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{now_str}] 完了: {self.task_name} (目標: {target_str})\n")
        except: pass

if __name__ == "__main__":
    root = tk.Tk()
    app = RobustTimer(root)
    root.mainloop()