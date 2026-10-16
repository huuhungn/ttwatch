import sys
import unittest
import uuid

import autostart
from test_core import _fresh_db, _make_scraper

WINDOWS = sys.platform == "win32"
EXE = r"C:\Tools\ttwatch folder\ttwatch.exe"


def _delete_tree(key_path):
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    sub = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_tree(f"{key_path}\\{sub}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
    except FileNotFoundError:
        pass


class CommandTest(unittest.TestCase):
    def test_command_quotes_the_path_and_asks_for_a_silent_start(self):
        self.assertEqual(autostart.command_for(EXE), f'"{EXE}" --background')

    def test_browser_opens_only_for_a_normal_start(self):
        self.assertTrue(autostart.should_open_browser([], {}))
        self.assertFalse(autostart.should_open_browser(["--background"], {}))
        self.assertFalse(autostart.should_open_browser([], {"NO_OPEN": "1"}))
        self.assertTrue(autostart.should_open_browser(["--other"], {"NO_OPEN": ""}))

    def test_running_from_source_is_not_supported_and_touches_nothing(self):
        state = autostart.Autostart(frozen=False)
        snap = state.snapshot()
        self.assertFalse(snap["supported"])
        self.assertIn("mã nguồn", snap["reason"])
        for call in (state.enable, state.disable):
            with self.assertRaises(autostart.AutostartError):
                call()
        state.sync(True)   # must not raise or write anything


class StartupSyncTest(unittest.TestCase):
    """app._sync_autostart runs once at start; it follows the setting and can never stop the tool from starting."""

    def setUp(self):
        import app as appmod

        self.appmod = appmod
        self.db = _fresh_db("autostart-sync")
        self.addCleanup(setattr, appmod, "startup", appmod.startup)

    def fake(self, sync):
        calls = []

        class Fake:
            def sync(self, wanted):
                calls.append(wanted)
                sync()

        self.appmod.startup = Fake()
        return calls

    def test_the_setting_decides_what_is_asked_for(self):
        calls = self.fake(lambda: None)
        self.appmod._sync_autostart()
        self.db.set_settings({"autostart": "1"})
        self.appmod._sync_autostart()
        self.assertEqual(calls, [False, True])

    def test_any_failure_is_swallowed_and_reported(self):
        def boom():
            raise autostart.AutostartError("registry is locked")

        self.fake(boom)
        self.appmod._sync_autostart()   # must not raise
        calls = self.fake(lambda: (_ for _ in ()).throw(TypeError("unexpected registry value type")))
        self.appmod._sync_autostart()   # not only AutostartError
        self.assertEqual(calls, [False])


@unittest.skipUnless(WINDOWS, "the Run key exists only on Windows")
class RegistryTest(unittest.TestCase):
    def setUp(self):
        import winreg

        self.winreg = winreg
        self.base = f"Software\\ttwatch-test-{uuid.uuid4().hex}"
        self.addCleanup(_delete_tree, self.base)

    def make(self, exe=EXE, frozen=True):
        return autostart.Autostart(frozen=frozen, exe=exe, run_key=self.base + r"\Run",
                                   approved_key=self.base + r"\StartupApproved")

    def value(self, sub, name=autostart.VALUE_NAME):
        try:
            with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER, f"{self.base}\\{sub}") as key:
                return self.winreg.QueryValueEx(key, name)[0]
        except FileNotFoundError:
            return None

    def mark_approval(self, first_byte):
        with self.winreg.CreateKeyEx(self.winreg.HKEY_CURRENT_USER, self.base + r"\StartupApproved", 0,
                                     self.winreg.KEY_SET_VALUE) as key:
            self.winreg.SetValueEx(key, autostart.VALUE_NAME, 0, self.winreg.REG_BINARY,
                                   bytes([first_byte]) + bytes(11))

    def test_enable_writes_the_run_value_and_disable_removes_it(self):
        state = self.make()
        self.assertFalse(state.snapshot()["enabled"])
        snap = state.enable()
        self.assertEqual(self.value("Run"), f'"{EXE}" --background')
        self.assertTrue(snap["enabled"] and snap["supported"])
        self.assertFalse(snap["stale"] or snap["blocked"])
        snap = state.disable()
        self.assertIsNone(self.value("Run"))
        self.assertFalse(snap["enabled"])

    def test_enable_and_disable_are_repeatable(self):
        state = self.make()
        state.disable()   # nothing there yet
        state.enable()
        state.enable()
        self.assertEqual(self.value("Run"), state.command())
        state.disable()
        state.disable()
        self.assertIsNone(self.value("Run"))

    def test_other_values_in_the_run_key_are_left_alone(self):
        with self.winreg.CreateKeyEx(self.winreg.HKEY_CURRENT_USER, self.base + r"\Run", 0,
                                     self.winreg.KEY_SET_VALUE) as key:
            self.winreg.SetValueEx(key, "SomethingElse", 0, self.winreg.REG_SZ, "other.exe")
        state = self.make()
        state.enable()
        state.disable()
        self.assertEqual(self.value("Run", "SomethingElse"), "other.exe")

    def test_a_moved_install_folder_is_reported_stale_and_sync_repairs_it(self):
        self.make(exe=r"C:\Old\ttwatch.exe").enable()
        state = self.make()
        self.assertTrue(state.snapshot()["stale"])
        state.sync(True)
        self.assertEqual(self.value("Run"), state.command())
        self.assertFalse(state.snapshot()["stale"])

    def test_sync_adds_a_missing_entry_only_when_the_user_wants_autostart(self):
        state = self.make()
        state.sync(False)
        self.assertIsNone(self.value("Run"))
        state.sync(True)
        self.assertEqual(self.value("Run"), state.command())

    def test_sync_does_not_turn_it_off_when_not_wanted(self):
        state = self.make()
        state.enable()
        state.sync(False)
        self.assertEqual(self.value("Run"), state.command())

    def test_task_manager_disable_is_reported_and_survives_startup_sync(self):
        state = self.make()
        state.enable()
        self.mark_approval(0x03)   # what Task Manager writes for "Disabled"
        self.assertTrue(state.snapshot()["blocked"])
        state.sync(True)
        self.assertTrue(state.snapshot()["blocked"], "the startup check must not override the user's choice in Windows")
        self.mark_approval(0x02)   # enabled again
        self.assertFalse(state.snapshot()["blocked"])

    def test_choosing_it_in_the_settings_clears_the_task_manager_block(self):
        state = self.make()
        state.enable()
        self.mark_approval(0x07)
        self.assertTrue(state.snapshot()["blocked"])
        snap = state.enable()
        self.assertFalse(snap["blocked"])
        self.assertIsNone(self.value("StartupApproved"))

    def test_environment_override_redirects_the_default_keys(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"TTWATCH_AUTOSTART_KEY": self.base}):
            state = autostart.Autostart(frozen=True, exe=EXE)
        self.assertEqual(state.run_key, self.base + r"\Run")
        self.assertEqual(state.approved_key, self.base + r"\StartupApproved")


@unittest.skipUnless(WINDOWS, "the Run key exists only on Windows")
class ApiTest(unittest.TestCase):
    def setUp(self):
        import app as appmod
        from fastapi.testclient import TestClient

        self.base = f"Software\\ttwatch-test-{uuid.uuid4().hex}"
        self.addCleanup(_delete_tree, self.base)
        self.appmod = appmod
        self.db = _fresh_db("autostart-api")
        appmod.scraper = _make_scraper()
        self.client = TestClient(appmod.app)
        self.addCleanup(setattr, appmod, "startup", appmod.startup)

    def use(self, frozen):
        self.appmod.startup = autostart.Autostart(frozen=frozen, exe=EXE, run_key=self.base + r"\Run",
                                                  approved_key=self.base + r"\StartupApproved")

    def test_state_explains_why_it_is_unavailable_from_source(self):
        self.use(frozen=False)
        state = self.client.get("/api/autostart").json()
        self.assertFalse(state["supported"])
        self.assertIn("mã nguồn", state["reason"])
        res = self.client.post("/api/autostart", json={"enabled": True})
        self.assertEqual(res.status_code, 400)
        self.assertIn("mã nguồn", res.json()["detail"])
        self.assertEqual(self.db.get_setting("autostart"), "0")

    def test_turning_it_on_and_off_is_saved_as_a_setting(self):
        self.use(frozen=True)
        self.assertEqual(self.db.get_setting("autostart"), "0")
        on = self.client.post("/api/autostart", json={"enabled": True}).json()
        self.assertTrue(on["enabled"])
        self.assertEqual(self.db.get_setting("autostart"), "1")
        self.assertTrue(self.client.get("/api/autostart").json()["enabled"])
        self.assertEqual(self.client.get("/api/settings").json()["autostart"], "1")
        off = self.client.post("/api/autostart", json={"enabled": False}).json()
        self.assertFalse(off["enabled"])
        self.assertEqual(self.db.get_setting("autostart"), "0")


if __name__ == "__main__":
    unittest.main()
