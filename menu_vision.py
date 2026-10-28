"""Locate colored buttons and recognize their text with small visual templates."""
from pathlib import Path
import cv2
import numpy as np


def button_text(crop, yellow=False):
    h, w = crop.shape[:2]
    crop = crop[max(2, round(h*.12)):h-max(2, round(h*.12)),
                max(3, round(w*.025)):w-max(3, round(w*.025))]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 2] < 170) if yellow else
            ((hsv[:, :, 1] < 135) & (hsv[:, :, 2] > 170))).astype(np.uint8)*255
    # Suppress compression speckles, keep all letters in the same line.
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    cleaned = np.zeros_like(mask)
    minimum_area = max(4, h*h*.004)
    heights = [stats[i, cv2.CC_STAT_HEIGHT] for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= minimum_area]
    if not heights:
        return None
    letter_height = float(np.percentile(heights, 65))
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= minimum_area and stats[i, cv2.CC_STAT_HEIGHT] >= .70*letter_height:
            cleaned[labels == i] = 255
    # A recorded/live hand cursor can overlap or sit next to the label. Trim
    # sparse rows outside the actual text line before normalizing the glyphs.
    counts = np.count_nonzero(cleaned, axis=1)
    line = np.flatnonzero(counts >= max(3, float(counts.max())*.22))
    if len(line) == 0:
        return None
    cleaned[:line[0]] = 0
    cleaned[line[-1]+1:] = 0
    n, labels, stats, _ = cv2.connectedComponentsWithStats(cleaned)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_HEIGHT] < .60*letter_height:
            cleaned[labels == i] = 0
    points = cv2.findNonZero(cleaned)
    if points is None:
        return None
    x, y, w, h = cv2.boundingRect(points)
    if w < 12 or h < 7:
        return None
    return cv2.resize(cleaned[y:y+h, x:x+w], (256, 40), interpolation=cv2.INTER_NEAREST)


class MenuDetector:
    def __init__(self):
        self.templates = {}
        for name in ('START', 'NEXT STAGE', 'RACE', 'CONTINUE', 'CASH OUT', 'COLLECT'):
            stem = f'button_{name.replace(" ", "_").lower()}'
            paths = (Path(__file__).parent/'assets').glob(f'{stem}*.png')
            self.templates[name] = [cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) > 0 for path in paths]

    def candidates(self, frame):
        # Only bottom 40%: avoid the ladder's bright crew banners and the overlay.
        offset = int(frame.shape[0]*.60)
        hsv = cv2.cvtColor(frame[offset:], cv2.COLOR_BGR2HSV)
        for yellow, low, high in [(False, (37, 95, 60), (82, 255, 255)),
                                  (True, (12, 110, 130), (36, 255, 255))]:
            mask = cv2.inRange(hsv, low, high)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 7), np.uint8))
            for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
                x, y, w, h = cv2.boundingRect(contour)
                if w >= 95 and h >= 25 and 2.1 < w/h < 13 and cv2.contourArea(contour)/(w*h) > .65:
                    yield yellow, (x, y+offset, w, h)

    def read(self, frame, left=0, top=0):
        rows = []
        for yellow, (x, y, w, h) in self.candidates(frame):
            glyph = button_text(frame[y:y+h, x:x+w], yellow)
            if glyph is None:
                continue
            glyph = glyph > 0
            scores = []
            for name, templates in self.templates.items():
                if yellow != (name == 'CASH OUT'):
                    continue
                if not templates:
                    continue
                score = max(2*np.count_nonzero(glyph & template)/(np.count_nonzero(glyph)+np.count_nonzero(template))
                            for template in templates)
                scores.append((float(score), name))
            scores.sort(reverse=True)
            if scores and scores[0][0] >= .79 and (len(scores) == 1 or scores[0][0]-scores[1][0] >= .07):
                score, name = scores[0]
                rows.append((name, max(.81, score), left+x+w/2, top+y+h/2))
        return rows

    def learn_collect(self, frame, point, left=0, top=0):
        """Cache only a twice-OCR-confirmed COLLECT button from the actual game."""
        px, py = point[0]-left, point[1]-top
        for yellow, (x, y, w, h) in self.candidates(frame):
            if not yellow and x <= px < x+w and y <= py < y+h:
                glyph = button_text(frame[y:y+h, x:x+w])
                if glyph is not None:
                    self.templates['COLLECT'] = [glyph > 0]
                    return cv2.imwrite(str(Path(__file__).parent/'assets'/'button_collect.png'), glyph)
        return False
