import threading
import unittest
from bot import Bot
from vision import GaugeReading


class FakeControls:
    def __init__(self):
        self.lock = threading.RLock()
        self.events = []

    def key(self, scan, down):
        self.events.append((scan, down))


class ControlTests(unittest.TestCase):
    def make_bot(self):
        bot = Bot()
        bot.controls = FakeControls()
        bot.running = True
        return bot

    def test_shift_once_then_rearm_after_rpm_drop(self):
        bot = self.make_bot()
        r = lambda angle: GaugeReading(angle, 305, 328, 'race', 1)
        bot.drive(r(315), 10)
        bot.drive(r(318), 10.02)
        bot.drive(r(321), 10.3)
        self.assertEqual(bot.controls.events.count((0x12, True)), 1)
        bot.drive(r(280), 10.4)
        bot.drive(r(315), 10.7)
        self.assertEqual(bot.controls.events.count((0x12, True)), 2)

    def test_launch_regulates_throttle(self):
        bot = self.make_bot()
        bot.drive(GaugeReading(200, 243, 260, 'launch', 1), 10)
        bot.drive(GaugeReading(270, 243, 260, 'launch', 1), 11)
        self.assertEqual(bot.controls.events, [(0x11, True), (0x11, False)])

    def test_pause_prevents_new_keydown(self):
        bot = self.make_bot()
        bot.running = False
        bot.drive(GaugeReading(315, 305, 328, 'race', 1), 10)
        self.assertEqual(bot.controls.events, [])

    def test_top_gear_keeps_throttle_without_shift(self):
        bot = self.make_bot()
        bot.drive(GaugeReading(291, 0, 0, 'top', 1), 10)
        self.assertEqual(bot.controls.events, [(0x11, True)])
        self.assertFalse(bot.shift_armed)

    def test_small_drop_in_high_gear_rearms_shift(self):
        bot = self.make_bot()
        r = lambda angle: GaugeReading(angle, 315, 328, 'race', 1)
        bot.drive(r(319), 10)
        bot.drive(r(310), 10.05)
        self.assertTrue(bot.shift_armed)
        bot.drive(r(320), 10.3)
        self.assertEqual(bot.controls.events.count((0x12, True)), 2)

    def test_no_duplicate_shift_until_displayed_gear_changes(self):
        bot = self.make_bot()
        r = lambda angle, gear: GaugeReading(angle, 315, 328, 'race', 1, gear)
        bot.drive(r(300, 5), 10)
        bot.drive(r(319, 5), 10.1)
        bot.drive(r(310, 5), 10.15)
        bot.drive(r(320, 5), 10.4)
        self.assertEqual(bot.controls.events.count((0x12, True)), 1)
        bot.drive(r(320, 6), 10.6)
        bot.drive(r(320, 6), 10.7)
        self.assertEqual(bot.controls.events.count((0x12, True)), 2)

    def test_ninth_gear_never_shifts_even_while_blue_band_fades(self):
        bot = self.make_bot()
        bot.config['max_gears'] = 9
        bot.drive(GaugeReading(322, 315, 328, 'race', 1, 9), 10)
        self.assertEqual(bot.controls.events, [(0x11, True)])


if __name__ == '__main__':
    unittest.main()
