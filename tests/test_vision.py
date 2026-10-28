import unittest
import cv2
import numpy as np
from vision import GaugeDetector, menu_action


def gauge(needle, blue):
    im = np.full((321, 321, 3), (45, 30, 30), dtype=np.uint8)
    a = np.deg2rad(np.linspace(*blue, 100))
    outer = np.column_stack((160+159*np.cos(a), 160+159*np.sin(a)))
    inner = np.column_stack((160+139*np.cos(a[::-1]), 160+139*np.sin(a[::-1])))
    cv2.fillPoly(im, [np.rint(np.vstack((outer, inner))).astype(np.int32)], (255, 220, 25))
    angle = np.deg2rad(needle)
    end = (round(160+130*np.cos(angle)), round(160+130*np.sin(angle)))
    cv2.line(im, (160, 160), end, (255, 255, 255), 4)
    cv2.circle(im, (160, 160), 7, (195, 195, 195), -1)
    cv2.ellipse(im, (160, 160), (150, 150), 0, 375, 410, (0, 0, 255), 4)
    # Realistic inner white arc and digits must not override the needle.
    cv2.ellipse(im, (160, 160), (110, 110), 0, 145, 360, (255, 255, 255), 10)
    cv2.putText(im, '158', (110, 215), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 3)
    return im


class VisionTests(unittest.TestCase):
    def test_launch_and_shift_and_other_angles(self):
        detector = GaugeDetector(160)
        for needle, blue, kind in [(165, (243, 260), 'launch'), (250, (243, 260), 'launch'),
                                   (315, (305, 328), 'race'), (370, (305, 328), 'race')]:
            with self.subTest(needle=needle):
                result = detector.read(gauge(needle, blue))
                self.assertIsNotNone(result)
                self.assertEqual(result.kind, kind)
                self.assertLess(abs(result.needle-needle), 2)
                self.assertLess(abs(result.blue_start-blue[0]), 3)

    def test_missing_gauge(self):
        self.assertIsNone(GaugeDetector(160).read(np.zeros((321, 321, 3), dtype=np.uint8)))

    def test_race_counter_ignores_stage_text(self):
        rows = [('RACE', .99, 1100, 900), ('CASH OUT', .99, 700, 900)]
        self.assertEqual(menu_action(rows, 43, 0)[0], 'RACE')
        self.assertEqual(menu_action(rows+[('STAGE 999', .99, 950, 50)], 43, 42)[0], 'RACE')
        self.assertEqual(menu_action(rows+[('STAGE 1', .99, 950, 50)], 43, 43)[0], 'CASH OUT')
        self.assertIsNone(menu_action([('RACE', .99, 1100, 900)], 43, 43))

    def test_cash_out_from_map_at_limit(self):
        rows = [('NEXT STAGE', .99, 1500, 1000), ('CASH OUT', .99, 1100, 1000)]
        self.assertEqual(menu_action(rows, 43, 42)[0], 'NEXT STAGE')
        self.assertEqual(menu_action(rows, 43, 43)[0], 'CASH OUT')


if __name__ == '__main__':
    unittest.main()
