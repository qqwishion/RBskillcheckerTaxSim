"""Overlay-only desktop status. Tk stays on the main thread."""
import ctypes as C
import logging
import queue
import threading
import time
import tkinter as tk

import mss
from bot import Bot, ROOT, calibrate


class Overlay:
    def __init__(self, root, bot):
        self.root, self.bot = root, bot
        self.closed = False
        self.calibrating = False
        self.bot.ui_attached = True
        root.withdraw()
        self.panel = tk.Toplevel(root)
        self.panel.overrideredirect(True)
        self.panel.geometry('410x218+12+55')
        self.panel.configure(bg='#10151f')
        self.panel.attributes('-topmost', True)
        self.panel.attributes('-alpha', .84)
        self.title = tk.StringVar(value='DRAG • Пауза')
        self.reason = tk.StringVar(value='Перейдите в игру и нажмите F8.')
        self.metrics = tk.StringVar()
        self.last_action = tk.StringVar()
        for variable, color, font in [(self.title, '#83edc6', ('Segoe UI', 11, 'bold')),
                                       (self.reason, '#eef4ff', ('Segoe UI', 9)),
                                       (self.metrics, '#b8d7ed', ('Segoe UI', 9)),
                                       (self.last_action, '#9bacc4', ('Segoe UI', 8))]:
            tk.Label(self.panel, textvariable=variable, bg='#10151f', fg=color, font=font,
                     justify='left', anchor='nw', wraplength=386).pack(fill='x', padx=12, pady=(5, 0))
        tk.Label(self.panel, text='F8 — запуск / пауза   •   F10 — выход\nF9 — сброс заездов   •   F6/F7 — калибровка',
                 bg='#10151f', fg='#9bacc4', font=('Segoe UI', 8), justify='left', anchor='w').pack(fill='x', padx=12, pady=7)
        self.panel.update_idletasks()
        self.make_passthrough()
        self.worker = threading.Thread(target=self.work, daemon=True)
        self.worker.start()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.refresh)

    def make_passthrough(self):
        user = C.WinDLL('user32')
        user.GetParent.argtypes = [C.c_void_p]
        user.GetParent.restype = C.c_void_p
        getter = user.GetWindowLongPtrW if C.sizeof(C.c_void_p) == 8 else user.GetWindowLongW
        setter = user.SetWindowLongPtrW if C.sizeof(C.c_void_p) == 8 else user.SetWindowLongW
        getter.argtypes, getter.restype = [C.c_void_p, C.c_int], C.c_ssize_t
        setter.argtypes, setter.restype = [C.c_void_p, C.c_int, C.c_ssize_t], C.c_ssize_t
        hwnd = user.GetParent(self.panel.winfo_id())
        # No activation, no taskbar button, clicks pass through to the game.
        setter(hwnd, -20, getter(hwnd, -20) | 0x08000000 | 0x00000080 | 0x00000020)

    def work(self):
        try:
            self.bot.run()
        except Exception:
            logging.exception('Ошибка выполнения')
            self.bot.pause('Ошибка выполнения. Подробности в bot.log.')
            self.bot.stop.set()

    def do_calibration(self, job):
        kind, monitor, done, results = job
        try:
            if not self.bot.stop.is_set():
                with mss.mss() as sct:
                    results.append(calibrate(sct, monitor, kind, parent=self.root))
        except Exception:
            if not self.closed:
                logging.exception('Ошибка калибровки')
        finally:
            done.set()
            self.calibrating = False
            if not self.closed:
                self.panel.deiconify()

    def refresh(self):
        if self.closed:
            return
        if self.bot.stop.is_set():
            self.close()
            return
        s = self.bot.snapshot()
        self.title.set(f"DRAG • {s['state']}")
        self.reason.set(s['reason'])
        keys = ' + '.join({0x11: 'W', 0x12: 'E'}.get(k, hex(k)) for k in s['keys']) or 'Клавиши отпущены'
        fresh = self.bot.running and time.perf_counter()-s['reading_at'] < .3
        gear = str(s['gear']) if fresh and s['gear'] is not None else '—'
        fps = f"{s['fps']:.0f} FPS" if self.bot.running else '— FPS'
        color = {'cyan': 'голубая', 'green': 'зелёная', 'white': 'белая'}.get(s.get('needle_color'), '—') if fresh else '—'
        self.metrics.set(f"Заездов: {s['completed']}/{s['race_limit']}   •   Кругов: {s['cycles']}   •   Передача: {gear}\n{keys}   •   {fps}   •   Стрелка: {color}\nOCR: {s['ocr']}")
        self.last_action.set(s['last_action'])
        try:
            job = self.bot.calibration_requests.get_nowait()
            self.calibrating = True
            self.panel.withdraw()
            self.root.after(250, lambda: self.do_calibration(job))
        except queue.Empty:
            pass
        self.root.after(100, self.refresh)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.bot.pause()
        self.bot.stop.set()
        self.root.destroy()


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
                        handlers=[logging.FileHandler(ROOT/'bot.log', encoding='utf-8')])
    root = tk.Tk()
    root.withdraw()
    Overlay(root, Bot())
    root.mainloop()


if __name__ == '__main__':
    main()
