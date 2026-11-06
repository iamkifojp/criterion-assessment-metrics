"""The idle watchdog that stops CAM2 once no tab is open, including after
the computer has been asleep, how a double-click starts the Mac app, and what
happens when a CAM2 is already running.

Run:  python -m unittest tests.test_launcher
"""

import contextlib
import http.server
import io
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

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


class MacDoubleClickTests(unittest.TestCase):
    def start(self, platform, frozen, argv):
        with mock.patch.object(launcher.sys, "platform", platform), \
                mock.patch.object(launcher.pickers, "_frozen", return_value=frozen), \
                mock.patch.object(launcher.sys, "argv", argv), \
                mock.patch.object(launcher.sys, "executable", "/app/cam2"), \
                mock.patch.object(launcher.subprocess, "Popen") as popen:
            return launcher.start_in_background_if_mac_double_click(), popen

    def test_a_double_click_hands_over_to_a_child_that_stays(self):
        started, popen = self.start("darwin", True, ["/app/cam2"])
        self.assertTrue(started)
        command = popen.call_args.args[0]
        self.assertEqual(command[0], "/app/cam2")
        self.assertTrue(command[1:], "the child needs an argument, or it would hand over again")

    def test_only_the_packaged_mac_app_with_no_arguments_does(self):
        for platform, frozen, argv in (("darwin", True, ["/app/cam2", "--idle", "600"]),
                                       ("darwin", False, ["launcher.py"]),
                                       ("win32", True, ["cam2.exe"])):
            started, popen = self.start(platform, frozen, argv)
            self.assertFalse(started)
            popen.assert_not_called()


class RunningInstanceTests(unittest.TestCase):
    """A small stand-in for a running CAM2, which stops when told to quit."""

    def start_server(self, version):
        requests = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.reply({"app": "cam2", "version": version})

            def do_POST(self):
                requests.append(self.path)
                self.reply({"ok": True})
                threading.Thread(target=self.server.shutdown).start()

            def reply(self, data):
                body = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)

        def serve():
            server.serve_forever()
            server.server_close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(lambda: requests or server.shutdown())
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, launcher.SERVER_FILE)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"port": server.server_address[1]}, fh)
        patcher = mock.patch.object(launcher, "_server_file", return_value=path)
        patcher.start()
        self.addCleanup(patcher.stop)
        return f"http://127.0.0.1:{server.server_address[1]}/", requests

    def test_the_same_version_is_left_running(self):
        url, requests = self.start_server(launcher.VERSION)
        self.assertEqual(launcher.running_instance(), url)
        self.assertEqual(requests, [])

    def test_another_version_is_stopped_before_the_new_one_starts(self):
        url, requests = self.start_server("0.0.1-old")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(launcher.running_instance())
        self.assertEqual(requests, ["/api/quit"])
        with self.assertRaises(OSError):
            launcher._ping(url)

    def test_a_different_version_is_stopped_in_both_directions(self):
        for running, starting in (("0.3.2-dev", "0.3.1-dev"), ("0.3.1-dev", "0.3.2-dev")):
            with self.subTest(running=running, starting=starting):
                url, requests = self.start_server(running)
                with mock.patch.object(launcher, "VERSION", starting), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertIsNone(launcher.running_instance())
                self.assertEqual(requests, ["/api/quit"], "nothing is handed to the other version")
                with self.assertRaises(OSError):
                    launcher._ping(url)

    def test_nothing_running(self):
        with mock.patch.object(launcher, "_server_file", return_value=os.devnull + "-none"):
            self.assertIsNone(launcher.running_instance())


class WatchdogTests(unittest.TestCase):
    def test_stops_when_no_tab_is_open(self):
        self.assertEqual(watch(range(0, 2000, 30)), 630)

    def test_waking_from_sleep_restarts_the_wait(self):
        # Checks every 30 s, then the lid is closed for 15 minutes.
        times = [0, 30, 60, 960] + list(range(990, 3000, 30))
        self.assertEqual(watch(times), 960 + 630)


if __name__ == "__main__":
    unittest.main()
