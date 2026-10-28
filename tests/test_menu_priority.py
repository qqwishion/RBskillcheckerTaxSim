from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import cv2
import numpy as np
import bot
from progress import RaceProgress
from vision import GaugeReading


class MenuPriorityTests(unittest.TestCase):
    def test_cyan_false_positive_does_not_block_next_stage(self):
        image = np.full((1080, 1920, 3), 20, dtype=np.uint8)
        button = cv2.imread(str(Path(__file__).parent/'fixtures'/'buttons'/'next_stage.png'))
        image[956:956+button.shape[0], 1344:1344+button.shape[1]] = button
        b = bot.Bot()
        b.config['race_limit'] = 43
        with tempfile.TemporaryDirectory() as folder:
            b.progress = RaceProgress(Path(folder)/'progress.json')
            b.progress.set_completed(31)
            clicks, keydowns = [], []

            class Controls:
                held = set()
                mouse_held = False
                lock = threading.RLock()

                def release(self):
                    self.held.clear()

                def key(self, scan, down):
                    if down:
                        keydowns.append(scan)

                def click(self, x, y, allowed):
                    self_test.assertTrue(allowed())
                    clicks.append((x, y))
                    b.stop.set()
                    return True

            class FakeGauge:
                def read(self, frame):
                    return GaugeReading(220, 240, 265, 'launch', 1, None, 'cyan')

            class Capture:
                monitors = [None, dict(left=0, top=0, width=1920, height=1080)]

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def grab(self, region):
                    return image[region['top']:region['top']+region['height'], region['left']:region['left']+region['width']]

            def load():
                b.detectors = {'fake': (dict(cx=960, cy=915, radius=163), FakeGauge())}
                b.active_screen_size = [1920, 1080]

            self_test = self
            b.controls = Controls()
            b.running = True
            timer = threading.Timer(2, b.stop.set)
            timer.start()
            try:
                with patch.object(b, 'load_detectors', side_effect=load), patch.object(b, 'hotkeys'), \
                     patch.object(b, 'ocr_worker'), patch.object(bot.mss, 'mss', return_value=Capture()), \
                     patch.object(bot, 'roblox_focused', return_value=True):
                    b.run()
            finally:
                timer.cancel()
            self.assertEqual(len(clicks), 1)
            self.assertEqual(keydowns, [])
