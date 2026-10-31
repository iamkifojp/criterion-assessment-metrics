"""The idle watchdog that stops CAM2 once no tab is open, including after
the computer has been asleep.

Run:  python -m unittest tests.test_launcher
"""

import contextlib
import io
import unittest

import launcher


class FakeState:
    def __init__(self, last_heartbeat=0.0):
        self.last_heartbeat = last_heartbeat


def watch(times, idle=600):
    """Run the watchdog over a list of clock readings; return the reading at
    which it stopped CAM2, or None if it never did."""
    readings = iter(times)
    now = [None]

    def clock():
        now[0] = next(readings)
        return now[0]

    stopped = []
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            launcher.watch_idle(FakeState(), idle, lambda: stopped.append(now[0]),
                                clock=clock, sleep=lambda _s: None)
        except StopIteration:
            pass
    return stopped[0] if stopped else None


class WatchdogTests(unittest.TestCase):
    def test_stops_when_no_tab_is_open(self):
        self.assertEqual(watch(range(0, 2000, 30)), 630)

    def test_waking_from_sleep_restarts_the_wait(self):
        # Checks every 30 s, then the lid is closed for 15 minutes.
        times = [0, 30, 60, 960] + list(range(990, 3000, 30))
        self.assertEqual(watch(times), 960 + 630)


if __name__ == "__main__":
    unittest.main()
