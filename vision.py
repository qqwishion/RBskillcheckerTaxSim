"""Pure image analysis; no capture or input side effects."""
from dataclasses import dataclass
from pathlib import Path
import re
import cv2
import numpy as np


@dataclass
class GaugeReading:
    needle: float
    blue_start: float
    blue_end: float
    kind: str
    confidence: float
    gear: int | None = None
    needle_color: str = 'unknown'


def gear_glyph(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] < 80) & (hsv[:, :, 2] > 125)).astype(np.uint8)*255
    n, labels, stats, centers = cv2.connectedComponentsWithStats(mask)
    options = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area >= 15 and x > 0 and y > 0 and x+w < mask.shape[1] and y+h < mask.shape[0]:
            options.append((area, x, y, w, h, i))
    if not options:
        return None
    _, x, y, w, h, i = max(options)
    glyph = (labels[y:y+h, x:x+w] == i).astype(np.uint8)*255
    scale = min(20/w, 28/h)
    resized = cv2.resize(glyph, (max(1, round(w*scale)), max(1, round(h*scale))), interpolation=cv2.INTER_NEAREST)
    out = np.zeros((32, 24), dtype=np.uint8)
    xx, yy = (24-resized.shape[1])//2, (32-resized.shape[0])//2
    out[yy:yy+resized.shape[0], xx:xx+resized.shape[1]] = resized
    return out


class GaugeDetector:
    def __init__(self, radius):
        self.radius = radius
        self.angles = np.arange(155.0, 411.0, 0.5)
        a = np.deg2rad(self.angles)[:, None]
        self.maps = []
        yy, xx = np.ogrid[:2*radius+1, :2*radius+1]
        distance = ((xx-radius)/radius)**2+((yy-radius)/radius)**2
        self.pivot_mask = distance <= .025**2
        self.pivot_surround = (distance >= .06**2) & (distance <= .12**2)
        template = cv2.imread(str(Path(__file__).parent/'assets'/'top_gear.png'), cv2.IMREAD_GRAYSCALE)
        self.top_template = (cv2.resize(template, None, fx=radius/163, fy=radius/163)
                             if template is not None else None)
        self.gear_templates = {}
        for gear in range(1, 10):
            path = Path(__file__).parent/'assets'/f'gear_{gear}.png'
            if path.exists():
                self.gear_templates[gear] = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) > 0
        for radii in (np.linspace(.82, 1.0, 16), np.linspace(.18, .82, 40)):
            self.maps.append((np.rint(radius + np.cos(a) * radius * radii).astype(int),
                              np.rint(radius + np.sin(a) * radius * radii).astype(int)))

    def read(self, bgr):
        if bgr.shape[:2] != (2*self.radius+1, 2*self.radius+1):
            return None
        gear = self.read_gear(bgr)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        # Color alone is insufficient: require the actual pivot and dial.
        pivot = ((hsv[..., 1] < 60) & (hsv[..., 2] > 125))[self.pivot_mask].mean()
        dark = (hsv[..., 2] < 130)[self.pivot_surround].mean()
        if pivot < .75 or dark < .65:
            return None
        x, y = self.maps[0]
        ring = hsv[y, x]
        red = (((ring[..., 0] < 12) | (ring[..., 0] > 170)) &
               (ring[..., 1] > 110) & (ring[..., 2] > 110))
        if red.mean() < .004:
            return None
        cyan = ((ring[..., 0] >= 80) & (ring[..., 0] <= 105) &
                (ring[..., 1] > 95) & (ring[..., 2] > 135)).mean(axis=1)
        good = np.flatnonzero(cyan > .30)
        low, high = None, None
        if len(good) >= 6:
            groups = np.split(good, np.where(np.diff(good) > 2)[0]+1)
            group = max(groups, key=len)
            if len(group) >= 6:
                low, high = self.angles[group[0]], self.angles[group[-1]]
                if not 3 <= high-low <= 55:
                    low, high = None, None
        x, y = self.maps[1]
        ray = hsv[y, x]
        # Launch needle transitions white -> cyan -> green around the target band.
        white = (((ray[..., 1] < 65) & (ray[..., 2] > 180)) |
                 ((ray[..., 0] >= 43) & (ray[..., 0] <= 105) &
                  (ray[..., 1] > 100) & (ray[..., 2] > 180))).mean(axis=1)
        idx = int(np.argmax(white))
        if white[idx] < .60:
            return None
        needle = ray[idx]
        is_cyan = (needle[:, 0] >= 80) & (needle[:, 0] <= 105) & (needle[:, 1] > 100) & (needle[:, 2] > 150)
        is_green = (needle[:, 0] >= 43) & (needle[:, 0] < 80) & (needle[:, 1] > 100) & (needle[:, 2] > 150)
        color = 'cyan' if is_cyan.mean() > .35 else 'green' if is_green.mean() > .35 else 'white'
        if low is None:
            if self.top_template is None:
                return None
            bottom = cv2.cvtColor(bgr[int(self.radius*1.65):, int(self.radius*.4):int(self.radius*1.6)], cv2.COLOR_BGR2GRAY)
            if any(a < b for a, b in zip(bottom.shape, self.top_template.shape)):
                return None
            score = cv2.minMaxLoc(cv2.matchTemplate(bottom, self.top_template, cv2.TM_CCOEFF_NORMED))[1]
            if score < .80:
                return None
            return GaugeReading(float(self.angles[idx]), 0., 0., 'top', float(score), gear, color)
        # The launch band is left of twelve o'clock; shift band is on the right.
        kind = 'launch' if (low+high)/2 < 275 else 'race'
        return GaugeReading(float(self.angles[idx]), float(low), float(high), kind, float(white[idx]), gear, color)

    def read_gear(self, bgr):
        r = self.radius
        crop = bgr[round(r*(1-65/163)):round(r*(1-25/163)),
                   round(r*(1-20/163)):round(r*(1+20/163))]
        glyph = gear_glyph(cv2.resize(crop, (40, 40)))
        if glyph is None or not self.gear_templates:
            return None
        mask = glyph > 0
        scores = sorted(((2*np.count_nonzero(mask & template)/(np.count_nonzero(mask)+np.count_nonzero(template)), gear)
                         for gear, template in self.gear_templates.items()), reverse=True)
        if scores[0][0] >= .80 and (len(scores) == 1 or scores[0][0]-scores[1][0] >= .06):
            return scores[0][1]
        return None


def normalize(text):
    cleaned = re.sub(r'[^A-Z0-9 ]', '', text.upper()).strip()
    compact = cleaned.replace(' ', '')
    return {'NEXTSTAGE': 'NEXT STAGE', 'CASHOUT': 'CASH OUT'}.get(compact, cleaned)


def menu_action(rows, race_limit, completed=0):
    """Rows: (recognized text, confidence, absolute x, absolute y)."""
    labels = {normalize(t): (x, y) for t, score, x, y in rows if score >= .80}
    if 'COLLECT' in labels:
        return 'COLLECT', labels['COLLECT'], None
    if 'START' in labels:
        return 'START', labels['START'], None
    compact = ''.join(labels).replace(' ', '')
    if 'TAXICITYLADDER' in compact and 'RACETHECREWS' in compact:
        return 'ENTER LADDER', (0, 0), None
    if 'RACE' in labels or 'NEXT STAGE' in labels:
        if completed >= race_limit:
            return ('CASH OUT', labels['CASH OUT'], None) if 'CASH OUT' in labels else None
        name = 'RACE' if 'RACE' in labels else 'NEXT STAGE'
        return name, labels[name], None
    if completed >= race_limit and 'CASH OUT' in labels:
        return 'CASH OUT', labels['CASH OUT'], None
    for name in ('CONTINUE', 'NEXT STAGE', 'START'):
        if name in labels:
            return name, labels[name], None
    return None
