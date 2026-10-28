from pathlib import Path
import tempfile
import threading
import unittest
from bot import Bot
from progress import RaceProgress
from vision import menu_action


class Controls:
    def __init__(self):
        self.lock = threading.RLock()
        self.held = set()
        self.mouse_held = False

    def key(self, scan, down):
        if down:
            self.held.add(scan)
        else:
            self.held.discard(scan)

    def release(self):
        self.held.clear()


class RepeatCycleTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.bot = Bot()
        self.bot.config.update(race_limit=3, repeat_runs=True, entry_hold_seconds=1.5, entry_retry_seconds=1.)
        self.bot.progress = RaceProgress(Path(folder.name)/'progress.json')
        self.bot.controls = Controls()
        self.bot.running = True

    def test_two_complete_three_race_cycles_reset_only_on_start(self):
        b = self.bot
        next_rows = [('NEXT STAGE', .99, 1500, 1000), ('CASH OUT', .99, 1100, 950)]
        for cycle in range(2):
            for count in range(1, 4):
                b.progress.race_visible()
                b.progress.observe_menu('CONTINUE')
                b.progress.observe_menu('NEXT STAGE')
                self.assertEqual(b.progress.completed, count)
                self.assertEqual(b.choose_action(next_rows)[0], 'CASH OUT' if count == 3 else 'NEXT STAGE')
            b.progress.cash_out_sent()
            self.assertEqual(b.choose_action([('COLLECT', .99, 660, 700)])[0], 'COLLECT')
            b.progress.collect_sent()
            b.enter_ladder(10+cycle*10)
            self.assertEqual(b.controls.held, {0x12})
            self.assertEqual(b.progress.completed, 3)
            self.assertEqual(b.choose_action([('START', .99, 1500, 1000)])[0], 'START')
            b.progress.confirm_start()
            b.maintain_idle_inputs(10.1+cycle*10)
            self.assertEqual(b.controls.held, set())
            self.assertEqual(b.progress.completed, 0)
            self.assertEqual(b.progress.cycles, cycle+1)
            b.progress.confirm_start()
            self.assertEqual(b.progress.cycles, cycle+1)

    def test_entry_hold_timeout_pause_and_retry(self):
        b = self.bot
        b.enter_ladder(10)
        self.assertEqual(b.controls.held, {0x12})
        self.assertFalse(b.maintain_idle_inputs(11.6))
        self.assertEqual(b.controls.held, set())
        b.enter_ladder(11.7)
        self.assertEqual(b.controls.held, set())
        b.enter_ladder(12.6)
        self.assertEqual(b.controls.held, {0x12})
        b.pause()
        self.assertEqual(b.controls.held, set())
        self.assertEqual(b.entry_hold_until, 0)

    def test_automatic_entry_without_any_prompt_or_ocr_results(self):
        b = self.bot
        b.progress.set_completed(3)
        b.progress.collect_sent()
        b.entry_retry_after = 11.
        self.assertIsNone(b.choose_action([]))
        self.assertFalse(b.maintain_idle_inputs(10.5))
        self.assertTrue(b.maintain_idle_inputs(11.))
        self.assertEqual(b.controls.held, {0x12})
        self.assertFalse(b.maintain_idle_inputs(12.6))
        self.assertTrue(b.maintain_idle_inputs(13.6))
        self.assertEqual(b.controls.held, {0x12})
        b.progress.confirm_start()
        self.assertFalse(b.maintain_idle_inputs(13.7))
        self.assertEqual(b.controls.held, set())
        self.assertEqual(b.progress.completed, 0)
        b.pause()
        self.assertFalse(b.maintain_idle_inputs(100))

    def test_entry_requires_both_prompt_labels(self):
        self.assertIsNone(menu_action([('Race the crews', .99, 500, 600)], 3, 3))
        rows = [('Taxi City Ladder', .99, 500, 580), ('Race the crews', .99, 500, 600)]
        self.assertEqual(menu_action(rows, 3, 3)[0], 'ENTER LADDER')
        self.assertEqual(menu_action(rows+[('START', .99, 1500, 1000)], 3, 3)[0], 'START')

    def test_collect_prioritizes_popup_over_background_buttons(self):
        rows = [('COLLECT', .99, 600, 700), ('RACE', .99, 1100, 900), ('CASH OUT', .99, 700, 900)]
        self.assertEqual(menu_action(rows, 3, 3)[0], 'COLLECT')

    def test_resume_after_collect_keeps_counter_until_confirmed_start(self):
        p = self.bot.progress
        p.set_completed(3)
        p.cash_out_sent()
        self.assertEqual(RaceProgress(p.path).phase, 'collect')
        p.collect_sent()
        restored = RaceProgress(p.path)
        self.assertEqual((restored.phase, restored.completed), ('entry', 3))
        restored.confirm_start()
        self.assertEqual((restored.phase, restored.completed, restored.cycles), ('racing', 0, 1))
