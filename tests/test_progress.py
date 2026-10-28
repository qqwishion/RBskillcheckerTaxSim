from pathlib import Path
import tempfile
import json
import unittest
from progress import RaceProgress
from vision import menu_action


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/'progress.json'
        self.progress = RaceProgress(self.path)

    def test_count_only_after_race_results_and_next_menu(self):
        p = self.progress
        p.observe_menu('NEXT STAGE')
        self.assertEqual(p.completed, 0)
        p.race_visible()
        p.observe_menu('CONTINUE')
        p.observe_menu('CONTINUE')
        self.assertEqual(p.completed, 0)
        self.assertTrue(p.observe_menu('NEXT STAGE'))
        self.assertFalse(p.observe_menu('NEXT STAGE'))
        self.assertEqual(p.completed, 1)

    def test_restart_during_results_preserves_pending_finish(self):
        self.progress.race_visible()
        self.progress.observe_menu('CONTINUE')
        p = RaceProgress(self.path)
        self.assertTrue(p.observe_menu('NEXT STAGE'))
        self.assertEqual(RaceProgress(self.path).completed, 1)

    def test_complete_two_races_and_reset_for_new_series(self):
        for _ in range(2):
            self.progress.race_visible()
            self.progress.observe_menu('CONTINUE')
            self.progress.observe_menu('NEXT STAGE')
        self.assertEqual(self.progress.completed, 2)
        self.progress.set_completed(0)
        self.assertEqual(RaceProgress(self.path).completed, 0)

    def test_failed_series_start_does_not_count(self):
        self.progress.race_visible()
        self.progress.observe_menu('CONTINUE')
        self.progress.observe_menu('START')
        self.progress.observe_menu('RACE')
        self.assertEqual(self.progress.completed, 0)

    def test_video_menu_cycle_without_stage_and_cash_out_on_43rd_finish(self):
        rows = json.loads((Path(__file__).parent/'fixtures'/'menu_rows.json').read_text(encoding='utf-8'))
        for initial, expected in [(0, 'NEXT STAGE'), (42, 'CASH OUT')]:
            with self.subTest(initial=initial):
                p = self.progress
                p.set_completed(initial)
                self.assertEqual(menu_action(rows['6'], 43, p.completed)[0], 'RACE')
                p.race_visible()
                p.observe_menu(menu_action(rows['17'], 43, p.completed)[0])
                p.observe_menu(menu_action(rows['19'], 43, p.completed)[0])
                self.assertEqual(p.completed, initial+1)
                self.assertEqual(menu_action(rows['19'], 43, p.completed)[0], expected)
