import unittest
from launch_control import LaunchController


class LaunchTests(unittest.TestCase):
    def test_throttle_settles_with_different_acceleration_and_input_lag(self):
        for up, down, lag in [(300, 300, 0), (420, 180, 0), (300, 250, .025)]:
            with self.subTest(up=up, down=down, lag=lag):
                controller = LaunchController()
                angle, velocity, hits, pulses = 180., 0., [], set()
                for i in range(300):
                    on = controller.update(angle, 240, 265, 'cyan' if 247 <= angle <= 259 else 'white', 1+i/60)
                    target_velocity = up if on else -down
                    velocity = target_velocity if lag == 0 else velocity+(target_velocity-velocity)*min(1, 1/60/lag)
                    angle += velocity/60
                    if i > 90:
                        hits.append(247 <= angle <= 259)
                        pulses.add(on)
                self.assertGreater(sum(hits)/len(hits), .75)
                self.assertEqual(pulses, {True, False})

    def test_cyan_feedback_moves_target_into_observed_valid_region(self):
        controller = LaunchController()
        for i in range(10):
            controller.update(258, 240, 265, 'cyan', 1+i/60)
        self.assertGreater(controller.target, 256)
