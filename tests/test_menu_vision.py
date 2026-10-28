from pathlib import Path
import unittest
import cv2
import numpy as np
from menu_vision import MenuDetector
from vision import menu_action


class MenuVisionTests(unittest.TestCase):
    def setUp(self):
        self.detector = MenuDetector()

    def test_recorded_buttons_at_multiple_scales(self):
        for name in ('START', 'NEXT STAGE', 'RACE', 'CONTINUE', 'CASH OUT', 'CASH OUT_map',
                     'START_hover', 'RACE_hover', 'NEXT STAGE_hover'):
            image = cv2.imread(str(Path(__file__).parent/'fixtures'/'buttons'/f'{name.lower().replace(" ", "_")}.png'))
            for scale in (.75, 1., 1.25):
                with self.subTest(name=name, scale=scale):
                    canvas = np.full((1080, 1920, 3), 20, dtype=np.uint8)
                    resized = cv2.resize(image, None, fx=scale, fy=scale)
                    h, w = resized.shape[:2]
                    canvas[900-h//2:900-h//2+h, 1000-w//2:1000-w//2+w] = resized
                    rows = self.detector.read(canvas)
                    self.assertEqual([r[0] for r in rows], [name.replace('_map', '').replace('_hover', '')])
                    self.assertLess(abs(rows[0][2]-1000), 3)
                    self.assertLess(abs(rows[0][3]-900), 3)

    def test_next_stage_with_no_ocr_results_or_stage_number(self):
        image = cv2.imread(str(Path(__file__).parent/'fixtures'/'buttons'/'next_stage.png'))
        canvas = np.full((1080, 1920, 3), 20, dtype=np.uint8)
        canvas[956:956+image.shape[0], 1344:1344+image.shape[1]] = image
        action = menu_action(self.detector.read(canvas), 43, 4)
        self.assertEqual(action[0], 'NEXT STAGE')

    def test_plain_green_button_is_not_guessed(self):
        canvas = np.full((1080, 1920, 3), 20, dtype=np.uint8)
        canvas[900:1000, 1300:1800] = (20, 145, 45)
        self.assertEqual(self.detector.read(canvas), [])
