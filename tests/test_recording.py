from pathlib import Path
import unittest
import cv2
from vision import GaugeDetector


class RecordingRegressionTests(unittest.TestCase):
    def test_real_gauge_states(self):
        detector = GaugeDetector(163)
        for name, kind, angle, gear in [('launch_white', 'launch', 178, 1), ('launch_cyan', 'launch', 251, 1),
                                        ('launch_green', 'launch', 261, 1), ('race', 'race', 314, 2),
                                        ('race_shift', 'race', 322, 8), ('top_gear', 'top', 291, 9)]:
            with self.subTest(name=name):
                frame = cv2.imread(str(Path(__file__).parent/'fixtures'/f'{name}.png'))
                reading = detector.read(frame)
                self.assertIsNotNone(reading)
                self.assertEqual(reading.kind, kind)
                self.assertEqual(reading.gear, gear)
                self.assertLess(abs(reading.needle-angle), 8)

    def test_launch_needle_colors_from_recording(self):
        for name, color in [('launch_white', 'white'), ('launch_cyan', 'cyan'), ('launch_green', 'green')]:
            with self.subTest(color=color):
                frame = cv2.imread(str(Path(__file__).parent/'fixtures'/f'{name}.png'))
                self.assertEqual(GaugeDetector(163).read(frame).needle_color, color)

    def test_cyan_ladder_artwork_is_not_a_tachometer(self):
        frame = cv2.imread(str(Path(__file__).parent/'fixtures'/'cyan_ladder.png'))
        self.assertIsNone(GaugeDetector(163).read(frame))

    def test_menu_is_not_a_gauge(self):
        frame = cv2.imread(str(Path(__file__).parent/'fixtures'/'menu.png'))
        self.assertIsNone(GaugeDetector(163).read(frame))
