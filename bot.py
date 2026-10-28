"""Windows visual drag assistant. F8 pause/run, F10 exit, F6/F7 calibration."""
import ctypes as C
from ctypes import wintypes as W
import json
import logging
from pathlib import Path
import queue
import threading
import time
import tkinter as tk

import cv2
import mss
import numpy as np
from PIL import Image, ImageTk
from vision import GaugeDetector, menu_action
from progress import RaceProgress
from menu_vision import MenuDetector
from launch_control import LaunchController

ROOT = Path(__file__).resolve().parent
user = C.WinDLL('user32', use_last_error=True)
kernel = C.WinDLL('kernel32', use_last_error=True)
user.SetProcessDPIAware()
user.GetForegroundWindow.restype = W.HWND
user.GetAsyncKeyState.argtypes = [C.c_int]
user.GetAsyncKeyState.restype = C.c_short
kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel.OpenProcess.restype = W.HANDLE
kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
kernel.CloseHandle.argtypes = [W.HANDLE]
user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]


def roblox_focused():
    pid = W.DWORD()
    user.GetWindowThreadProcessId(user.GetForegroundWindow(), C.byref(pid))
    handle = kernel.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return False
    try:
        name, length = C.create_unicode_buffer(1024), W.DWORD(1024)
        return bool(kernel.QueryFullProcessImageNameW(handle, 0, name, C.byref(length)) and
                    Path(name.value).name.lower() == 'robloxplayerbeta.exe')
    finally:
        kernel.CloseHandle(handle)


class KeyInput(C.Structure):
    _fields_ = [('vk', W.WORD), ('scan', W.WORD), ('flags', W.DWORD),
                ('time', W.DWORD), ('extra', C.c_size_t)]


class MouseInput(C.Structure):
    _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('data', W.DWORD),
                ('flags', W.DWORD), ('time', W.DWORD), ('extra', C.c_size_t)]


class InputUnion(C.Union):
    _fields_ = [('ki', KeyInput), ('mi', MouseInput)]


class Input(C.Structure):
    _anonymous_ = ('value',)
    _fields_ = [('type', W.DWORD), ('value', InputUnion)]


user.SendInput.argtypes = [W.UINT, C.POINTER(Input), C.c_int]
user.SendInput.restype = W.UINT
user.GetCursorPos.argtypes = [C.POINTER(W.POINT)]
user.GetCursorPos.restype = W.BOOL


class Controls:
    def __init__(self):
        self.held = set()
        self.lock = threading.RLock()
        self.mouse_held = False

    def mouse(self, flags, dx=0, dy=0):
        event = Input(type=0, mi=MouseInput(dx, dy, 0, flags, 0, 0))
        if user.SendInput(1, C.byref(event), C.sizeof(Input)) != 1:
            raise RuntimeError('Mouse SendInput failed')

    def key(self, scan, down):
        with self.lock:
            if down == (scan in self.held):
                return
            event = Input(type=1, ki=KeyInput(0, scan, 0x8 | (0 if down else 2), 0, 0))
            if user.SendInput(1, C.byref(event), C.sizeof(Input)) != 1:
                raise RuntimeError('SendInput failed. Check game/application privilege levels.')
            if down:
                self.held.add(scan)
            else:
                self.held.discard(scan)

    def release(self):
        with self.lock:
            for scan in tuple(self.held):
                self.key(scan, False)
            if self.mouse_held:
                self.mouse(4)
                self.mouse_held = False

    def click(self, x, y, allowed=lambda: True):
        # Deliver hover and down/up on separate rendered frames. Back-to-back
        # down/up can both arrive between Roblox UI updates and be ignored.
        with self.lock:
            if not allowed():
                return False
            left, top, width, height = (user.GetSystemMetrics(i) for i in (76, 77, 78, 79))
            x, y = round(x), round(y)
            if not (left <= x < left+width and top <= y < top+height):
                raise RuntimeError(f'Click target outside desktop: {x}, {y}')
            dx = round((x-left)*65535/max(1, width-1))
            dy = round((y-top)*65535/max(1, height-1))
            # Relative motion wakes Roblox's mouse input; leaving/re-entering the
            # target avoids stale hover state when the cursor was already there.
            self.mouse(0x2001, 6, 0)
            time.sleep(.030)
            if not allowed():
                return False
            away_y = y-96 if y-top >= 96 else min(top+height-1, y+96)
            self.mouse(0xE001, dx, round((away_y-top)*65535/max(1, height-1)))
            time.sleep(.050)
            if not allowed():
                return False
            self.mouse(0xE001, dx, dy)
            time.sleep(.040)
            if not allowed():
                return False
            self.mouse(0x2001, 1, 0)
            time.sleep(.080)
            if not allowed():
                return False
            point = W.POINT()
            if not user.GetCursorPos(C.byref(point)) or abs(point.x-x) > 3 or abs(point.y-y) > 3:
                logging.warning('Click cancelled: cursor did not reach target (%s, %s)', x, y)
                return False
            try:
                self.mouse(2)
                self.mouse_held = True
                time.sleep(.100)
            finally:
                if self.mouse_held:
                    self.mouse(4)
                    self.mouse_held = False
            return True


def calibrate(sct, monitor, kind, parent=None):
    """Two clicks on a frozen full-screen snapshot, without sending game input."""
    image = Image.fromarray(cv2.cvtColor(np.array(sct.grab(monitor)), cv2.COLOR_BGRA2RGB))
    root = tk.Toplevel(parent) if parent else tk.Tk()
    root.title('Gauge calibration')
    root.geometry(f"{monitor['width']}x{monitor['height']}+{monitor['left']}+{monitor['top']}")
    root.overrideredirect(True)
    canvas = tk.Canvas(root, highlightthickness=0)
    canvas.pack(fill='both', expand=True)
    photo = ImageTk.PhotoImage(image)
    canvas.create_image(0, 0, image=photo, anchor='nw')
    title = canvas.create_text(30, 30, anchor='nw', fill='yellow', font=('Arial', 20),
                               text='Калибровка: нажмите на центр вращения стрелки, затем на внешний край шкалы. Esc — отмена.')
    points, result = [], []

    def click(event):
        points.append((event.x, event.y))
        if len(points) == 1:
            canvas.create_oval(event.x-4, event.y-4, event.x+4, event.y+4, fill='red')
            canvas.itemconfigure(title, text='Теперь нажмите на внешний край окружности шкалы. Esc — отмена.')
        else:
            cx, cy = points[0]
            radius = round(np.hypot(event.x-cx, event.y-cy))
            if radius >= 40 and cx-radius >= 0 and cy-radius >= 0 and cx+radius < image.width and cy+radius < image.height:
                result.append(dict(cx=cx+monitor['left'], cy=cy+monitor['top'], radius=radius))
            root.destroy()

    canvas.bind('<Button-1>', click)
    root.bind('<Escape>', lambda event: root.destroy())
    if parent:
        parent.wait_window(root)
    else:
        root.mainloop()
    return result[0] if result else None


class Bot:
    def __init__(self):
        self.config = json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
        self.config.setdefault('race_limit', self.config.get('cash_out_before_stage', 44)-1)
        self.progress = RaceProgress(ROOT/'progress.json')
        self.controls = Controls()
        self.running = False
        self.stop = threading.Event()
        self.commands = queue.Queue()
        self.ocr_jobs, self.ocr_results = queue.Queue(1), queue.Queue(1)
        self.epoch = 0
        self.detectors = {}
        self.last_gauge = 0
        self.last_shift = 0
        self.e_release = 0
        self.shift_armed = True
        self.previous = None
        self.gear_control = False
        self.last_shift_gear = None
        self.current_gear = None
        self.gear_seen_since = 0
        self.ui_attached = False
        self.calibration_requests = queue.Queue()
        self.telemetry_lock = threading.Lock()
        self.telemetry = dict(state='Пауза', reason='Готов профиль из вашей записи. Перейдите в Roblox и нажмите F8. F6/F7 — ручная настройка при необходимости.',
                              fps=0, stage=None, needle=None, blue=None, ocr='Загрузка…',
                              shifts=0, last_action='—', preview=None, reading_at=0, gear=None)
        self.last_preview = 0
        self.launch_controller = LaunchController()
        self.entry_hold_until = 0.
        self.entry_retry_after = 0.

    def report(self, **values):
        with self.telemetry_lock:
            self.telemetry.update(values)

    def snapshot(self):
        with self.telemetry_lock:
            result = dict(self.telemetry)
        with self.controls.lock:
            result['keys'] = tuple(sorted(self.controls.held))
            result['mouse_held'] = self.controls.mouse_held
        result['completed'] = self.progress.completed
        result['race_limit'] = self.config['race_limit']
        result['cycles'] = self.progress.cycles
        return result

    def choose_action(self, rows):
        action = menu_action(rows, self.config['race_limit'], self.progress.completed)
        if action is None:
            return None
        if self.progress.phase == 'collect' and action[0] not in ('CASH OUT', 'COLLECT'):
            return None
        if self.progress.phase == 'entry' and action[0] not in ('COLLECT', 'ENTER LADDER', 'START'):
            return None
        return action

    def maintain_idle_inputs(self, now):
        with self.controls.lock:
            if self.running and not self.stop.is_set() and self.progress.phase == 'entry':
                if now >= self.entry_retry_after:
                    self.e_release = 0
                    self.entry_hold_until = now+self.config.get('entry_hold_seconds', 1.5)
                    self.entry_retry_after = self.entry_hold_until+self.config.get('entry_retry_seconds', 1.)
                    self.report(state='Возврат на старт', reason='Удерживаю E для входа. Положение подсказки не используется.',
                                last_action='Удержание E — вход в новую серию')
                if now < self.entry_hold_until:
                    self.controls.key(0x11, False)
                    self.controls.key(0x12, True)
                    return True
            self.controls.release()
            return False

    def enter_ladder(self, now):
        self.progress.collect_sent()
        self.maintain_idle_inputs(now)

    def pause(self, reason='Пауза. Для продолжения вернитесь в игру и нажмите F8.'):
        self.running = False
        self.epoch += 1
        self.menu_candidate = None
        self.entry_hold_until = 0.
        self.entry_retry_after = 0.
        self.controls.release()
        self.report(state='Пауза', reason=reason)

    def hotkeys(self):
        old = set()
        while not self.stop.wait(.008):
            current = {k for k in (0x75, 0x76, 0x77, 0x78, 0x79) if user.GetAsyncKeyState(k) & 0x8000}
            for key in current-old:
                if key == 0x79:
                    self.pause()
                    self.stop.set()
                elif key == 0x78:
                    self.pause('Новая серия: сбрасываю счётчик. Для запуска нажмите F8.')
                    self.commands.put(dict(completed_races=0))
                elif key == 0x77:
                    # Pausing releases input here, independently of capture/OCR.
                    if self.running:
                        self.pause()
                        logging.info('PAUSED')
                    else:
                        self.commands.put('run')
                else:
                    self.pause()
                    self.commands.put('launch' if key == 0x75 else 'race')
            old = current

    def ocr_worker(self):
        try:
            from rapidocr import RapidOCR
            engine = RapidOCR(params={'EngineConfig.onnxruntime.intra_op_num_threads': 2,
                                      'EngineConfig.onnxruntime.inter_op_num_threads': 1})
            logging.info('Menu OCR ready')
            self.report(ocr='Готово')
            while not self.stop.is_set():
                try:
                    epoch, stamp, frame, mon = self.ocr_jobs.get(timeout=.2)
                except queue.Empty:
                    continue
                # Fallback OCR reads only the button area at native scale.
                # Whole-screen OCR can merge NEXT STAGE with nearby overlays.
                offset = int(frame.shape[0]*.60)
                area = frame[offset:]
                scale = min(1., 1600/area.shape[1])
                small = cv2.resize(area, None, fx=scale, fy=scale)
                out = engine(small, use_cls=False)
                rows = []
                if out.txts is not None:
                    for box, text, score in zip(out.boxes, out.txts, out.scores):
                        x, y = np.mean(box, axis=0)/scale
                        rows.append((text, float(score), x+mon['left'], y+offset+mon['top']))
                try:
                    self.ocr_results.put_nowait((epoch, stamp, rows))
                except queue.Full:
                    pass
        except Exception:
            logging.exception('Menu OCR unavailable; stopping bot')
            self.pause('Ошибка распознавания меню. Подробности в журнале ниже.')
            self.report(ocr='Ошибка')
            self.stop.set()

    def load_detectors(self):
        gauges = self.config['gauges']
        monitor = getattr(self, 'monitor', None)
        profile = self.config.get('gauge_profile')
        if not gauges and monitor and profile:
            scale = monitor['height']/profile['reference_height']
            radius = round(profile['radius']*scale)
            gauges = {'video': dict(cx=monitor['left']+monitor['width']//2,
                                    cy=monitor['top']+round(profile['cy']*scale), radius=radius)}
            self.active_screen_size = [monitor['width'], monitor['height']]
        else:
            self.active_screen_size = self.config.get('screen_size')
        self.detectors = {name: (g, GaugeDetector(g['radius'])) for name, g in gauges.items()}

    def run(self):
        self.load_detectors()
        threading.Thread(target=self.hotkeys, daemon=True).start()
        threading.Thread(target=self.ocr_worker, daemon=True).start()
        logging.info('F6 calibrate LAUNCH | F7 calibrate RACE | F8 run/pause | F9 reset races | F10 exit')
        logging.info('Completed races: %s / %s; bot starts PAUSED', self.progress.completed, self.config['race_limit'])
        last_menu, menu_blocked_until, last_log, last_ocr = 0, 0, 0, 0
        menu_visible_until = 0
        menu_detector = MenuDetector()
        frames = 0
        with mss.mss() as sct:
            mon = sct.monitors[self.config['monitor']]
            self.monitor = mon
            self.load_detectors()
            try:
                while not self.stop.is_set():
                    tick = time.perf_counter()
                    try:
                        command = self.commands.get_nowait()
                        if command == 'run':
                            if not self.detectors:
                                logging.info('No gauge calibration: menu navigation only; use F6/F7 for throttle and shifts')
                            if roblox_focused():
                                self.epoch += 1
                                self.previous = None
                                self.launch_controller.reset()
                                self.shift_armed = True
                                self.gear_control = False
                                self.last_shift_gear = None
                                self.current_gear = None
                                self.last_gauge = 0
                                self.running = True
                                self.report(state='Поиск интерфейса', reason='Ищу тахометр или кнопки меню.')
                                logging.info('RUNNING')
                            else:
                                self.report(state='Нет фокуса игры', reason='Переключитесь в Roblox и нажмите F8.')
                                logging.info('Focus Roblox, then press F8')
                        elif isinstance(command, dict):
                            values = dict(command)
                            if 'completed_races' in values:
                                self.progress.set_completed(values.pop('completed_races'))
                                self.menu_candidate = None
                                self.epoch += 1
                                logging.info('Race counter set to %s', self.progress.completed)
                            self.config.update(values)
                            self.load_detectors()
                            (ROOT/'config.json').write_text(json.dumps(self.config, indent=2), encoding='utf-8')
                            self.report(reason=(f'Счётчик заездов: {self.progress.completed}. Для запуска нажмите F8.'
                                                if 'completed_races' in command else 'Настройки сохранены. Для запуска нажмите F8 в игре.'))
                        elif command in ('launch', 'race'):
                            self.report(state='Калибровка', reason='Отметьте центр стрелки и внешний край шкалы на снимке.')
                            if self.ui_attached:
                                done, results = threading.Event(), []
                                self.calibration_requests.put((command, dict(mon), done, results))
                                while not done.wait(.05) and not self.stop.is_set():
                                    pass
                                result = results[0] if results else None
                            else:
                                result = calibrate(sct, mon, command)
                            if result:
                                self.config['gauges'][command] = result
                                self.config['screen_size'] = [mon['width'], mon['height']]
                                (ROOT/'config.json').write_text(json.dumps(self.config, indent=2), encoding='utf-8')
                                self.load_detectors()
                                logging.info('%s calibration saved: %s', command, result)
                                self.report(state='Пауза', reason='Калибровка сохранена. Вернитесь в игру и нажмите F8.')
                            else:
                                self.report(state='Пауза', reason='Калибровка отменена или круг выходит за пределы экрана. Повторите F6/F7.')
                    except queue.Empty:
                        pass
                    if not self.running:
                        self.stop.wait(.02)
                        continue
                    if not roblox_focused():
                        self.pause('Roblox потерял фокус. Вернитесь в игру и нажмите F8.')
                        logging.info('PAUSED: Roblox lost focus')
                        continue
                    if self.active_screen_size != [mon['width'], mon['height']]:
                        self.pause('Изменилось разрешение. Повторите калибровку F6/F7.')
                        logging.info('Resolution changed: calibrate again')
                        continue
                    reading = None
                    for name, (g, detector) in self.detectors.items():
                        region = dict(left=g['cx']-g['radius'], top=g['cy']-g['radius'],
                                      width=2*g['radius']+1, height=2*g['radius']+1)
                        crop = np.array(sct.grab(region))[:, :, :3]
                        found = detector.read(crop)
                        if tick-self.last_preview > .10:
                            self.report(preview=crop.copy())
                            self.last_preview = tick
                        if found:
                            reading = found
                            break
                    now = time.perf_counter()
                    fast_menu_result = None
                    if self.progress.phase != 'racing':
                        reading = None
                        self.last_gauge = 0
                    if now < menu_visible_until:
                        reading = None
                        self.last_gauge = 0
                    # Probe uncertain gauge readings too: cyan ladder artwork
                    # must never suppress an independently recognized button.
                    probe = (reading is None and now-self.last_gauge > .20) or (reading is not None and reading.gear is None)
                    if probe and now-last_menu > .12 and now > menu_blocked_until:
                        frame = np.array(sct.grab(mon))[:, :, :3]
                        started = time.perf_counter()
                        rows = menu_detector.read(frame, mon['left'], mon['top'])
                        if rows and self.choose_action(rows):
                            fast_menu_result = (self.epoch, time.perf_counter(), rows)
                            reading = None
                            self.last_gauge = 0
                            menu_visible_until = now+.35
                            self.maintain_idle_inputs(now)
                            self.report(ocr=f'Кнопки: {(time.perf_counter()-started)*1000:.0f} мс',
                                        recognized=' • '.join(row[0] for row in rows))
                        elif reading is None and now-last_ocr > .8 and self.ocr_jobs.empty():
                            self.ocr_jobs.put_nowait((self.epoch, now, frame, dict(mon)))
                            last_ocr = now
                        last_menu = now
                    if self.e_release and now >= self.e_release:
                        self.controls.key(0x12, False)
                        self.e_release = 0
                    if reading:
                        if reading.kind in ('race', 'top'):
                            self.progress.race_visible()
                        self.report(needle=reading.needle, blue=(reading.blue_start, reading.blue_end), reading_at=now, gear=reading.gear,
                                    needle_color=reading.needle_color)
                        self.last_gauge = now
                        self.drive(reading, now)
                    elif now-self.last_gauge > .20:
                        if now < menu_blocked_until:
                            self.report(state='Переход', reason='Кнопка нажата. Жду обновления экрана перед следующим действием.', needle=None, blue=None)
                        elif not getattr(self, 'menu_candidate', None):
                            reason = ('Жду COLLECT, чтобы забрать награду и вернуться ко входу.'
                                      if self.progress.phase == 'collect' else
                                      'Удерживаю E у входа; жду стартовое меню.'
                                      if now < self.entry_hold_until else
                                      'Короткая пауза перед удержанием E. Подсказку искать не нужно.'
                                      if self.progress.phase == 'entry' else
                                      'Тахометр не настроен: могу нажимать только кнопки меню. Для газа и передач отметьте шкалу через F6/F7.'
                                      if not self.detectors else
                                      f'Ищу кнопки меню. Завершено заездов: {self.progress.completed}/{self.config["race_limit"]}; надпись STAGE не нужна.')
                            self.report(state='Возврат на старт' if self.progress.phase == 'entry' else 'Поиск меню', reason=reason, needle=None, blue=None)
                        self.maintain_idle_inputs(now)
                        self.previous = None
                    try:
                        if fast_menu_result is not None:
                            epoch, stamp, rows = fast_menu_result
                        else:
                            epoch, stamp, rows = self.ocr_results.get_nowait()
                        action = self.choose_action(rows)
                        if action and epoch == self.epoch:
                            self.report(recognized=' • '.join(row[0] for row in rows))
                        if (action and epoch == self.epoch and now-stamp < 3 and now > menu_blocked_until
                                and now-self.last_gauge > .25 and self.running and roblox_focused()):
                            # Require the same menu on two independent captures before clicking.
                            signature = (action[0], action[2], round(action[1][0]/30), round(action[1][1]/30))
                            if getattr(self, 'menu_candidate', None) == signature:
                                if action[0] == 'ENTER LADDER':
                                    self.enter_ladder(now)
                                    self.menu_candidate = None
                                    continue
                                if action[0] == 'START':
                                    self.entry_hold_until = self.entry_retry_after = 0.
                                    self.controls.release()
                                    if self.progress.confirm_start():
                                        logging.info('New start screen confirmed: counter reset; cycles=%s', self.progress.cycles)
                                    self.launch_controller.reset()
                                if action[0] == 'COLLECT':
                                    collect_frame = np.array(sct.grab(mon))[:, :, :3]
                                    if menu_detector.learn_collect(collect_frame, action[1], mon['left'], mon['top']):
                                        logging.info('COLLECT visual template cached from confirmed game button')
                                counted = self.progress.observe_menu(action[0])
                                if counted:
                                    logging.info('Race completion confirmed: %s / %s', self.progress.completed, self.config['race_limit'])
                                # Re-evaluate after counting: the final finish must
                                # select CASH OUT on this map, never NEXT STAGE.
                                action = self.choose_action(rows)
                                if action is None:
                                    self.menu_candidate = None
                                    continue
                                with self.controls.lock:
                                    if not self.running or self.stop.is_set() or not roblox_focused():
                                        continue
                                    self.controls.release()
                                    sent = self.controls.click(*action[1], allowed=lambda: self.running and not self.stop.is_set() and roblox_focused())
                                if not sent:
                                    self.menu_candidate = None
                                    self.report(state='Клик отменён', reason='Курсор не достиг кнопки или игра потеряла фокус. Повторю распознавание.')
                                    logging.warning('Click cancelled for %s at %s', action[0], action[1])
                                    continue
                                logging.info('LMB sent to %s at (%s, %s), held 100 ms (stage %s); awaiting transition',
                                             action[0], round(action[1][0]), round(action[1][1]), action[2])
                                self.report(stage=action[2] if action[2] is not None else self.snapshot()['stage'],
                                            last_action=f'ЛКМ → {action[0]} ({round(action[1][0])}, {round(action[1][1])}), 100 мс',
                                            state='Переход', reason=f'ЛКМ отправлен на {action[0]}. Жду следующий экран.')
                                menu_blocked_until = time.perf_counter()+.30
                                self.epoch += 1
                                self.menu_candidate = None
                                if action[0] == 'CASH OUT':
                                    if self.config.get('repeat_runs', False):
                                        self.progress.cash_out_sent()
                                        self.report(state='Получение награды', reason='CASH OUT отправлен. Жду COLLECT; затем снова войду через E.')
                                    else:
                                        self.pause('Нажата CASH OUT: достигнут лимит. Для новой серии нажмите F9, затем F8.')
                                elif action[0] == 'COLLECT':
                                    self.progress.collect_sent()
                                    self.entry_hold_until = 0.
                                    self.entry_retry_after = time.perf_counter()+self.config.get('entry_initial_delay_seconds', 1.)
                                    self.report(state='Новый круг', reason='COLLECT отправлен. После короткой загрузки начну удерживать E автоматически.')
                            else:
                                self.menu_candidate = signature
                                self.report(stage=action[2] if action[2] is not None else self.snapshot()['stage'],
                                            state='Проверка кнопки', reason=f'Вижу {action[0]}. Жду повторного распознавания перед кликом.')
                        else:
                            self.menu_candidate = None
                    except queue.Empty:
                        pass
                    frames += 1
                    if now-last_log > 2:
                        if last_log:
                            self.report(fps=frames/max(.001, now-last_log))
                        logging.info('%s | %.0f loop FPS%s', 'GAUGE' if reading else 'WAIT / MENU',
                                     frames/max(.001, now-last_log) if last_log else 0,
                                     f' | needle {reading.needle:.1f}, blue {reading.blue_start:.1f}..{reading.blue_end:.1f}' if reading else '')
                        frames, last_log = 0, now
                    self.stop.wait(max(0, 1/self.config['target_fps']-(time.perf_counter()-tick)))
            finally:
                self.pause(self.snapshot()['reason'] if self.stop.is_set() else 'Программа остановлена.')
                self.stop.set()

    def drive(self, r, now):
        # Synchronize with pause hotkey so no key-down can follow its release.
        with self.controls.lock:
            if not self.running or self.stop.is_set():
                return
            velocity = 0
            rpm_drop = False
            moving_up = True
            if self.previous and self.previous[2] == r.kind:
                old_angle, old_time, _ = self.previous
                dt = now-old_time
                if .001 < dt < .15 and abs(r.needle-old_angle) < 45:
                    velocity = max(0, min(1500, (r.needle-old_angle)/dt))
                    rpm_drop = old_angle-r.needle >= 5
                    moving_up = r.needle >= old_angle-1
            self.previous = (r.needle, now, r.kind)
            if r.kind == 'launch':
                self.gear_control = False
                self.last_shift_gear = None
                self.current_gear = None
                down = self.launch_controller.update(r.needle, r.blue_start, r.blue_end, r.needle_color, now)
                self.controls.key(0x11, down)
                self.shift_armed = True
                self.report(state='Подготовка старта', reason=('Голубая стрелка — целевая зона. Поддерживаю обороты импульсами W.'
                            if r.needle_color == 'cyan' else 'Регулирую газ по скорости стрелки. Цель — голубая стрелка.'))
            elif r.kind == 'top' or (r.gear is not None and r.gear >= self.config.get('max_gears', 99)):
                self.controls.key(0x11, True)
                self.shift_armed = False
                self.report(state='Последняя передача', reason='Вижу TOP GEAR. Держу W до финиша; переключать больше не нужно.')
            else:
                if r.gear is not None:
                    self.gear_control = True
                    if r.gear != self.current_gear:
                        self.current_gear = r.gear
                        self.gear_seen_since = now
                    if self.last_shift_gear is not None and r.gear != self.last_shift_gear:
                        self.shift_armed = True
                self.report(state='Гонка', reason='Держу W; жду синюю зону для переключения E.' if self.shift_armed else 'Передача переключена. Жду падения оборотов перед следующим E.')
                self.controls.key(0x11, True)
                if r.needle < r.blue_start-12 or rpm_drop:
                    self.shift_armed = True
                predicted = r.needle + velocity*self.config['shift_lead_ms']/1000
                target = r.blue_start + max(1., .10*(r.blue_end-r.blue_start))
                gear_ready = not self.gear_control or (r.gear is not None and r.gear != self.last_shift_gear
                                                       and now-self.gear_seen_since >= .06)
                if self.gear_control and not gear_ready:
                    self.report(reason='Держу W. Жду подтверждения новой передачи по цифре на тахометре.')
                if (self.shift_armed and gear_ready and moving_up and predicted >= target and r.needle <= r.blue_end+2
                        and now-self.last_shift > self.config['shift_cooldown_ms']/1000):
                    self.controls.key(0x12, True)
                    self.e_release = now+.025
                    self.last_shift = now
                    self.shift_armed = False
                    self.last_shift_gear = r.gear
                    with self.telemetry_lock:
                        self.telemetry['shifts'] += 1
                        self.telemetry['last_action'] = 'Нажата E — стрелка достигла зоны переключения'


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
                        handlers=[logging.StreamHandler(), logging.FileHandler(ROOT/'bot.log', encoding='utf-8')])
    try:
        Bot().run()
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.exception('Bot stopped')
