import ctypes
import unittest
from unittest.mock import patch
import bot


class MouseTests(unittest.TestCase):
    def run_click(self, allowed=lambda: True, cursor=(500, 400), sleep_effect=None):
        events = []
        controls = bot.Controls()

        def position(ptr):
            point = ctypes.cast(ptr, ctypes.POINTER(bot.W.POINT)).contents
            point.x, point.y = cursor
            return True

        with patch.object(bot.user, 'GetSystemMetrics', side_effect=lambda index: {76: 0, 77: 0, 78: 1920, 79: 1080}[index]), \
             patch.object(bot.user, 'GetCursorPos', side_effect=position), \
             patch.object(controls, 'mouse', side_effect=lambda flags, *xy: events.append((flags, xy))), \
             patch.object(bot.time, 'sleep', side_effect=sleep_effect) as sleep:
            result = controls.click(500, 400, allowed)
        return result, events, sleep.call_args_list, controls

    def test_hover_and_hold_are_separate_steps(self):
        result, events, delays, controls = self.run_click()
        self.assertTrue(result)
        self.assertEqual([event[0] for event in events], [0x2001, 0xE001, 0xE001, 0x2001, 2, 4])
        self.assertEqual([call.args[0] for call in delays], [.030, .050, .040, .080, .100])
        self.assertFalse(controls.mouse_held)

    def test_pause_during_hover_cancels_button_down(self):
        states = iter([True, False])
        result, events, _, _ = self.run_click(allowed=lambda: next(states))
        self.assertFalse(result)
        self.assertEqual([event[0] for event in events], [0x2001])

    def test_cursor_not_at_button_cancels_click(self):
        result, events, _, _ = self.run_click(cursor=(300, 200))
        self.assertFalse(result)
        self.assertEqual([event[0] for event in events], [0x2001, 0xE001, 0xE001, 0x2001])

    def test_exception_while_held_still_releases_mouse(self):
        controls = bot.Controls()
        flags = []
        def sleep(duration):
            if duration == .100:
                raise RuntimeError('interrupted')
        with patch.object(bot.user, 'GetSystemMetrics', side_effect=lambda index: {76: 0, 77: 0, 78: 1920, 79: 1080}[index]), \
             patch.object(bot.user, 'GetCursorPos', return_value=True), \
             patch.object(controls, 'mouse', side_effect=lambda flag, *xy: flags.append(flag)), \
             patch.object(bot.time, 'sleep', side_effect=sleep):
            with self.assertRaises(RuntimeError):
                controls.click(0, 0)
        self.assertEqual(flags, [0x2001, 0xE001, 0xE001, 0x2001, 2, 4])
        self.assertFalse(controls.mouse_held)
