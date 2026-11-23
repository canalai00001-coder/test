"""操作画面を開くときの自動更新を確かめる。GitHub には接続しない。"""
import unittest
from unittest import mock

from hitomane_agent import app as app_mod


class FakeApp:
    def __init__(self, new=True, error=None):
        self.new, self.error, self.updated = new, error, False

    def update_info(self):
        if self.error:
            raise self.error
        return {"new": self.new, "latest": {"message": "最新"}, "current": {}}

    def update_from_github(self):
        self.updated = True
        return {"changed": 3, "pip_ok": True}


class TestAutoUpdate(unittest.TestCase):
    def run_it(self, fake, settings=None):
        with mock.patch("builtins.print"), \
                mock.patch.object(app_mod.config, "load", return_value=settings or {"update": {}}):
            return app_mod.auto_update(fake)

    def test_new_version_is_taken(self):
        fake = FakeApp(new=True)
        self.assertTrue(self.run_it(fake))
        self.assertTrue(fake.updated)

    def test_latest_does_nothing(self):
        fake = FakeApp(new=False)
        self.assertFalse(self.run_it(fake))
        self.assertFalse(fake.updated)

    def test_offline_opens_current_version(self):
        self.assertFalse(self.run_it(FakeApp(error=OSError("つながりません"))))

    def test_can_be_turned_off(self):
        fake = FakeApp(new=True)
        self.assertFalse(self.run_it(fake, {"update": {"auto": False}}))
        self.assertFalse(fake.updated)

    def test_restarts_with_new_version(self):
        with mock.patch.object(app_mod, "auto_update", return_value=True), \
                mock.patch.object(app_mod, "App"), mock.patch.object(app_mod.sys, "argv", ["app"]), \
                mock.patch.object(app_mod.subprocess, "call", return_value=0) as call, \
                mock.patch.object(app_mod, "serve") as serve:
            with self.assertRaises(SystemExit):
                app_mod.main()
        self.assertIn("--no-auto-update", call.call_args[0][0])
        serve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
