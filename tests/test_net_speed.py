"""Tests for bin/net-speed, run against fake sysfs and proc trees.

Run from the repository root: python3 -m unittest discover -s tests
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.dont_write_bytecode = True

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "bin", "net-speed")

_loader = importlib.machinery.SourceFileLoader("net_speed", SCRIPT)
_spec = importlib.util.spec_from_loader("net_speed", _loader)
net_speed = importlib.util.module_from_spec(_spec)
_loader.exec_module(net_speed)

ROUTE_HEADER = (
    "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
)


class FakeSystem:
    """A throwaway /sys/class/net, /proc and state directory."""

    def __init__(self, root):
        self.root = root
        self.sysfs = os.path.join(root, "sys", "class", "net")
        self.proc = os.path.join(root, "proc")
        self.state = os.path.join(root, "state")
        self.devices = os.path.join(root, "sys", "devices")
        os.makedirs(self.sysfs)
        os.makedirs(os.path.join(self.proc, "net"))
        os.makedirs(os.path.join(self.proc, "sys", "kernel", "random"))
        os.makedirs(os.path.join(root, "sys", "bus", "usb"))
        os.makedirs(os.path.join(root, "sys", "bus", "pci"))
        self.set_boot_id("boot-one")
        self.set_routes([])
        self.set_routes6([])

    def _write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def add(self, name, type_=1, operstate="up", flags="0x1003", physical=False,
            wireless=False, usb=False, tun_flags=False, rx=0, tx=0,
            carrier=None, driver=None, usb_class=None):
        path = os.path.join(self.sysfs, name)
        os.makedirs(os.path.join(path, "statistics"))
        self._write(os.path.join(path, "type"), "%d\n" % type_)
        self._write(os.path.join(path, "operstate"), operstate + "\n")
        self._write(os.path.join(path, "flags"), flags + "\n")
        if physical:
            dev = os.path.join(self.devices, name)
            os.makedirs(dev)
            bus = "usb" if usb else "pci"
            os.symlink(os.path.join(self.root, "sys", "bus", bus), os.path.join(dev, "subsystem"))
            os.symlink(dev, os.path.join(path, "device"))
            if driver:
                drv = os.path.join(self.root, "sys", "bus", bus, "drivers", driver)
                os.makedirs(drv, exist_ok=True)
                os.symlink(drv, os.path.join(dev, "driver"))
            if usb_class:
                self._write(os.path.join(dev, "bInterfaceClass"), usb_class + "\n")
        if carrier is not None:
            self._write(os.path.join(path, "carrier"), "%d\n" % carrier)
        if wireless:
            os.makedirs(os.path.join(path, "wireless"))
        if tun_flags:
            self._write(os.path.join(path, "tun_flags"), "0x1001\n")
        self.set_counters(name, rx, tx)

    def set_counters(self, name, rx, tx):
        stats = os.path.join(self.sysfs, name, "statistics")
        self._write(os.path.join(stats, "rx_bytes"), "%d\n" % rx)
        self._write(os.path.join(stats, "tx_bytes"), "%d\n" % tx)

    def set_routes(self, defaults):
        """defaults: list of (iface, metric) IPv4 default routes."""
        lines = [ROUTE_HEADER]
        for name, metric in defaults:
            lines.append("%s\t00000000\t0100000A\t0003\t0\t0\t%d\t00000000\t0\t0\t0\n"
                         % (name, metric))
        # A non-default route, which must be ignored.
        lines.append("lo\t0000000A\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n")
        self._write(os.path.join(self.proc, "net", "route"), "".join(lines))

    def set_routes6(self, defaults):
        """defaults: list of (iface, metric, reject) IPv6 default routes."""
        zero = "0" * 32
        lines = []
        for name, metric, reject in defaults:
            flags = 0x00200200 if reject else 0x00450003
            lines.append("%s 00 %s 00 %s %08x 00000001 00000000 %08x %8s\n"
                         % (zero, zero, "fe80" + "0" * 27 + "1", metric, flags, name))
        # A non-default route, which must be ignored.
        lines.append("fe800000000000000000000000000000 40 %s 00 %s 00000100 "
                     "00000001 00000000 00000001 lo\n" % (zero, zero))
        self._write(os.path.join(self.proc, "net", "ipv6_route"), "".join(lines))

    def set_boot_id(self, value):
        self._write(os.path.join(self.proc, "sys", "kernel", "random", "boot_id"), value + "\n")

    @property
    def usage_file(self):
        return os.path.join(self.state, "usage.json")

    def env(self, today="2026-01-10"):
        return {
            "NET_SPEED_SYSFS": self.sysfs,
            "NET_SPEED_PROC": self.proc,
            "NET_SPEED_STATE": self.state,
            "NET_SPEED_TODAY": today,
        }

    def run(self, *args, today="2026-01-10"):
        buf = io.StringIO()
        with mock.patch.dict(os.environ, self.env(today)), redirect_stdout(buf):
            code = net_speed.main(list(args))
        self.last_code = code
        return json.loads(buf.getvalue())

    def load_state(self):
        with open(self.usage_file) as f:
            return json.load(f)

    def age_state(self, seconds=60):
        """Pretend the last write happened a while ago, to pass the throttle."""
        state = self.load_state()
        state["saved"] -= seconds
        with open(self.usage_file, "w") as f:
            json.dump(state, f)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fs = FakeSystem(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def assertContract(self, out):
        self.assertEqual(self.fs.last_code, 0)
        self.assertEqual(out["v"], 1)
        for key in ("mono", "link", "tunnel", "ifaces", "today", "days", "error"):
            self.assertIn(key, out)
        self.assertIsInstance(out["mono"], float)


class LinkSelection(Base):
    def vpn_laptop(self):
        """A laptop with a VPN kill switch: the dummy holds the best metric."""
        self.fs.add("wlp0s0", physical=True, wireless=True, rx=5000, tx=700)
        self.fs.add("wg0", type_=65534, operstate="unknown", flags="0x10d1", rx=4000, tx=600)
        self.fs.add("kswitch0", operstate="unknown", flags="0x10c3", rx=0, tx=0)
        self.fs.set_routes([("kswitch0", 98), ("wlp0s0", 600)])

    def test_kill_switch_dummy_ignored_for_physical_wifi(self):
        self.vpn_laptop()
        out = self.fs.run()
        self.assertContract(out)
        self.assertIsNone(out["error"])
        self.assertEqual(out["link"], {"name": "wlp0s0", "kind": "wifi", "up": True,
                                       "rx": 5000, "tx": 700, "reason": "auto"})
        kinds = {i["name"]: (i["kind"], i["physical"]) for i in out["ifaces"]}
        self.assertEqual(kinds["kswitch0"], ("dummy", False))
        self.assertEqual(kinds["wg0"], ("tunnel", False))
        self.assertEqual(kinds["wlp0s0"], ("wifi", True))
        self.assertEqual(out["tunnel"], {"name": "wg0", "rx": 4000, "tx": 600})

    def test_lo_excluded(self):
        self.fs.add("lo", type_=772, operstate="unknown")
        self.fs.add("enp0s0", physical=True)
        out = self.fs.run()
        self.assertEqual([i["name"] for i in out["ifaces"]], ["enp0s0"])

    def test_lowest_metric_physical_wins(self):
        self.fs.add("enp0s0", physical=True, rx=10)
        self.fs.add("wlp0s0", physical=True, wireless=True, rx=99999)
        self.fs.set_routes([("wlp0s0", 600), ("enp0s0", 100)])
        out = self.fs.run()
        self.assertEqual(out["link"]["name"], "enp0s0")
        self.assertEqual(out["link"]["kind"], "ethernet")

    def test_no_physical_route_falls_back_to_most_rx(self):
        self.fs.add("enp0s0", physical=True, rx=10)
        self.fs.add("wlp0s0", physical=True, wireless=True, rx=500)
        self.fs.add("kswitch0", operstate="unknown")
        self.fs.set_routes([("kswitch0", 50)])
        out = self.fs.run()
        self.assertEqual(out["link"]["name"], "wlp0s0")

    def test_down_physical_is_not_chosen(self):
        self.fs.add("enp0s0", physical=True, operstate="down", rx=999)
        self.fs.add("wlp0s0", physical=True, wireless=True, rx=1)
        self.fs.set_routes([("enp0s0", 10), ("wlp0s0", 600)])
        out = self.fs.run()
        self.assertEqual(out["link"]["name"], "wlp0s0")

    def test_offline_gives_null_link(self):
        self.fs.add("wlp0s0", physical=True, wireless=True, operstate="down")
        self.fs.add("kswitch0", operstate="unknown")
        self.fs.set_routes([("kswitch0", 98)])
        out = self.fs.run()
        self.assertContract(out)
        self.assertIsNone(out["link"])
        self.assertIsNone(out["error"])

    def test_usb_adapter_kind(self):
        self.fs.add("enx0", physical=True, usb=True)
        out = self.fs.run()
        self.assertEqual(out["link"]["kind"], "usb")

    def test_unknown_operstate_with_carrier_is_picked(self):
        # Android USB tethering: rndis_host never reports link state.
        self.fs.add("enp0s20f0u3", physical=True, usb=True, operstate="unknown",
                    carrier=1, driver="rndis_host", rx=200, tx=10)
        self.fs.add("wlo1", physical=True, wireless=True, operstate="down", rx=3)
        self.fs.set_routes([("enp0s20f0u3", 100)])
        out = self.fs.run()
        self.assertIsNone(out["error"])
        self.assertEqual(out["link"], {"name": "enp0s20f0u3", "kind": "tether", "up": True,
                                       "rx": 200, "tx": 10, "reason": "auto"})

    def test_unknown_operstate_without_carrier_is_not_picked(self):
        self.fs.add("enx0", physical=True, usb=True, operstate="unknown", carrier=0)
        self.fs.add("enx1", physical=True, usb=True, operstate="unknown", flags="0x1002",
                    carrier=1)
        self.fs.add("enx2", physical=True, usb=True, operstate="unknown")
        self.fs.set_routes([("enx0", 10), ("enx1", 20), ("enx2", 30)])
        self.assertIsNone(self.fs.run()["link"])

    def test_routed_tether_beats_unrouted_wifi(self):
        self.fs.add("wlp0s0", physical=True, wireless=True, rx=99999)
        self.fs.add("usb0", physical=True, usb=True, operstate="unknown", carrier=1,
                    driver="rndis_host", rx=5)
        self.fs.set_routes([("usb0", 100)])
        self.assertEqual(self.fs.run()["link"]["name"], "usb0")

    def test_tether_kinds(self):
        self.fs.add("usb0", physical=True, usb=True, driver="rndis_host")
        self.fs.add("eth1", physical=True, usb=True, driver="ipheth")
        self.fs.add("usb1", physical=True, usb=True, driver="cdc_ether", usb_class="E0")
        self.fs.add("enx0", physical=True, usb=True, driver="cdc_ether", usb_class="02")
        kinds = {i["name"]: i["kind"] for i in self.fs.run()["ifaces"]}
        self.assertEqual(kinds, {"usb0": "tether", "eth1": "tether",
                                 "usb1": "tether", "enx0": "usb"})

    def test_ipv6_default_route_decides(self):
        self.fs.add("enp0s0", physical=True, rx=10)
        self.fs.add("wlp0s0", physical=True, wireless=True, rx=99999)
        self.fs.set_routes6([("enp0s0", 1024, False)])
        self.assertEqual(self.fs.run()["link"]["name"], "enp0s0")

    def test_ipv6_reject_default_is_ignored(self):
        self.fs.add("enp0s0", physical=True, rx=10)
        self.fs.add("wlp0s0", physical=True, wireless=True, rx=99999)
        self.fs.set_routes6([("enp0s0", 1, True)])
        self.assertEqual(self.fs.run()["link"]["name"], "wlp0s0")

    def test_missing_ipv6_route_file(self):
        os.unlink(os.path.join(self.fs.proc, "net", "ipv6_route"))
        self.fs.add("enp0s0", physical=True)
        out = self.fs.run()
        self.assertEqual(out["link"]["name"], "enp0s0")
        self.assertIsNone(out["error"])

    def test_usb_wifi_dongle_is_wifi(self):
        self.fs.add("wlx0", physical=True, usb=True, wireless=True)
        out = self.fs.run()
        self.assertEqual(out["link"]["kind"], "wifi")


class TunnelDetection(Base):
    def kinds(self):
        return {i["name"]: i["kind"] for i in self.fs.run()["ifaces"]}

    def test_type_none_is_tunnel(self):
        self.fs.add("vpnx", type_=65534, operstate="unknown")
        self.assertEqual(self.kinds()["vpnx"], "tunnel")

    def test_wireguard_name_is_tunnel(self):
        self.fs.add("wg7", type_=1, operstate="unknown")
        self.assertEqual(self.kinds()["wg7"], "tunnel")

    def test_tap_with_tun_flags_is_tunnel(self):
        self.fs.add("vpn9", type_=1, tun_flags=True, operstate="unknown")
        self.assertEqual(self.kinds()["vpn9"], "tunnel")

    def test_other_tunnel_names(self):
        for name in ("tun0", "proton1", "tailscale0", "nordlynx", "mullvad-a"):
            self.fs.add(name, type_=1, operstate="unknown")
        kinds = self.kinds()
        for name in ("tun0", "proton1", "tailscale0", "nordlynx", "mullvad-a"):
            self.assertEqual(kinds[name], "tunnel", name)

    def test_down_tunnel_is_not_reported(self):
        self.fs.add("wg0", type_=65534, operstate="down", flags="0x1090")
        self.assertIsNone(self.fs.run()["tunnel"])

    def test_tunnel_with_default_route_preferred(self):
        self.fs.add("tun0", type_=65534, operstate="unknown")
        self.fs.add("wg0", type_=65534, operstate="unknown")
        self.fs.set_routes([("wg0", 50)])
        self.assertEqual(self.fs.run()["tunnel"]["name"], "wg0")

    def test_first_tunnel_without_routes(self):
        self.fs.add("wg1", type_=65534, operstate="unknown")
        self.fs.add("tun0", type_=65534, operstate="unknown")
        self.assertEqual(self.fs.run()["tunnel"]["name"], "tun0")

    def test_bridge_is_not_dummy(self):
        self.fs.add("br0", type_=1)
        os.makedirs(os.path.join(self.fs.sysfs, "br0", "bridge"))
        self.assertEqual(self.kinds()["br0"], "other")


class Pinning(Base):
    def test_pinned_interface(self):
        self.fs.add("enp0s0", physical=True, operstate="down", rx=3, tx=4)
        self.fs.add("wlp0s0", physical=True, wireless=True)
        self.fs.set_routes([("wlp0s0", 600)])
        out = self.fs.run("--iface", "enp0s0")
        self.assertContract(out)
        self.assertEqual(out["link"], {"name": "enp0s0", "kind": "ethernet", "up": False,
                                       "rx": 3, "tx": 4, "reason": "pinned"})
        self.assertIsNone(out["error"])

    def test_pinned_equals_form(self):
        self.fs.add("wg0", type_=65534, operstate="unknown")
        out = self.fs.run("--iface=wg0")
        self.assertEqual(out["link"]["reason"], "pinned")
        self.assertEqual(out["link"]["kind"], "tunnel")

    def test_iface_auto_is_auto(self):
        self.fs.add("wlp0s0", physical=True, wireless=True)
        self.assertEqual(self.fs.run("--iface", "auto")["link"]["reason"], "auto")

    def test_missing_pinned_interface(self):
        self.fs.add("wlp0s0", physical=True, wireless=True)
        out = self.fs.run("--iface", "eth9")
        self.assertContract(out)
        self.assertIsNone(out["link"])
        self.assertIn("eth9", out["error"])


class UsageRecording(Base):
    def setUp(self):
        super().setUp()
        self.fs.add("wlp0s0", physical=True, wireless=True, rx=1000, tx=100)
        self.fs.add("enp0s0", physical=True, rx=50, tx=5)
        self.fs.add("wg0", type_=65534, operstate="unknown", rx=900, tx=90)
        self.fs.add("kswitch0", operstate="unknown", rx=7, tx=7)

    def test_first_run_is_baseline(self):
        out = self.fs.run()
        self.assertEqual(out["today"], {"date": "2026-01-10", "rx": 0, "tx": 0})
        state = self.fs.load_state()
        self.assertEqual(sorted(state["last"]), ["enp0s0", "wlp0s0"])
        self.assertEqual(state["boot_id"], "boot-one")

    def test_records_physical_deltas_across_calls(self):
        self.fs.run()
        self.fs.age_state()
        self.fs.set_counters("wlp0s0", 1500, 300)
        self.fs.set_counters("enp0s0", 60, 10)
        self.fs.set_counters("wg0", 99999, 99999)  # tunnel traffic is not counted
        self.fs.set_counters("kswitch0", 99999, 99999)
        out = self.fs.run()
        self.assertEqual(out["today"], {"date": "2026-01-10", "rx": 510, "tx": 205})
        self.assertEqual(self.fs.load_state()["days"]["2026-01-10"], {"rx": 510, "tx": 205})

    def test_counter_reset_counts_current_value(self):
        self.fs.run()
        self.fs.age_state()
        self.fs.set_counters("wlp0s0", 200, 20)  # driver reload: counters went backwards
        self.fs.set_counters("enp0s0", 50, 5)
        out = self.fs.run()
        self.assertEqual(out["today"]["rx"], 200)
        self.assertEqual(out["today"]["tx"], 20)

    def test_boot_id_change_counts_current_value(self):
        self.fs.run()
        self.fs.age_state()
        self.fs.set_boot_id("boot-two")
        self.fs.set_counters("wlp0s0", 3000, 300)  # higher than before, but a new boot
        self.fs.set_counters("enp0s0", 1, 1)
        out = self.fs.run()
        self.assertEqual(out["today"]["rx"], 3001)
        self.assertEqual(out["today"]["tx"], 301)
        self.assertEqual(self.fs.load_state()["boot_id"], "boot-two")

    def test_new_interface_counts_current_value(self):
        self.fs.run()
        self.fs.age_state()
        self.fs.add("enx0", physical=True, usb=True, rx=40, tx=4)
        out = self.fs.run()
        self.assertEqual(out["today"]["rx"], 40)

    def test_date_rollover_writes_immediately(self):
        self.fs.run(today="2026-01-10")
        self.fs.set_counters("wlp0s0", 1100, 110)
        # No ageing: the 30 s throttle would apply, but the date changed.
        out = self.fs.run(today="2026-01-11")
        self.assertEqual(out["today"], {"date": "2026-01-11", "rx": 100, "tx": 10})
        state = self.fs.load_state()
        self.assertEqual(state["days"]["2026-01-11"], {"rx": 100, "tx": 10})
        self.assertEqual(state["days"]["2026-01-10"], {"rx": 0, "tx": 0})
        self.assertEqual([d["date"] for d in out["days"]], ["2026-01-11", "2026-01-10"])

    def test_write_throttle(self):
        self.fs.run()
        before = self.fs.load_state()
        self.fs.set_counters("wlp0s0", 1400, 140)
        out = self.fs.run()
        # Shown at once, but not written within 30 s of the last write.
        self.assertEqual(out["today"]["rx"], 400)
        self.assertEqual(self.fs.load_state(), before)
        # The next run after the interval counts the same bytes exactly once.
        self.fs.age_state(31)
        self.fs.set_counters("wlp0s0", 1500, 150)
        out = self.fs.run()
        self.assertEqual(out["today"]["rx"], 500)
        self.assertEqual(self.fs.load_state()["days"]["2026-01-10"]["rx"], 500)

    def test_prunes_to_31_days_and_lists_7(self):
        self.fs.run()
        state = self.fs.load_state()
        from datetime import date, timedelta
        start = date(2026, 1, 10)
        for n in range(1, 41):
            state["days"][(start - timedelta(days=n)).isoformat()] = {"rx": n, "tx": n}
        state["saved"] -= 60
        with open(self.fs.usage_file, "w") as f:
            json.dump(state, f)
        out = self.fs.run()
        kept = sorted(self.fs.load_state()["days"])
        self.assertEqual(len(kept), 31)
        self.assertEqual(kept[0], "2025-12-11")
        self.assertEqual(kept[-1], "2026-01-10")
        self.assertEqual(len(out["days"]), 7)
        self.assertEqual(out["days"][0]["date"], "2026-01-10")
        self.assertEqual(out["days"][6], {"date": "2026-01-04", "rx": 6, "tx": 6})

    def test_days_skip_missing_dates(self):
        self.fs.run()
        state = self.fs.load_state()
        state["days"]["2026-01-07"] = {"rx": 1, "tx": 2}
        with open(self.fs.usage_file, "w") as f:
            json.dump(state, f)
        out = self.fs.run()
        self.assertEqual([d["date"] for d in out["days"]], ["2026-01-10", "2026-01-07"])

    def test_corrupt_state_is_replaced(self):
        os.makedirs(self.fs.state)
        for junk in ("{not json", "[]", '{"days": 5, "last": {}}', ""):
            with open(self.fs.usage_file, "w") as f:
                f.write(junk)
            out = self.fs.run()
            self.assertContract(out)
            self.assertIsNone(out["error"], junk)
            state = self.fs.load_state()
            self.assertIn("2026-01-10", state["days"])
            self.assertIn("wlp0s0", state["last"])

    def test_unreadable_state_dir_is_not_fatal(self):
        # The state path is a file, so the directory cannot be created.
        with open(os.path.join(self.fs.root, "blocker"), "w") as f:
            f.write("x")
        env = self.fs.env()
        env["NET_SPEED_STATE"] = os.path.join(self.fs.root, "blocker", "sub")
        buf = io.StringIO()
        with mock.patch.dict(os.environ, env), redirect_stdout(buf):
            code = net_speed.main([])
        out = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(out["link"]["name"], "wlp0s0")
        self.assertIn("usage", out["error"])
        self.assertEqual(out["today"]["date"], "2026-01-10")

    def test_no_temp_files_left(self):
        self.fs.run()
        self.assertEqual(os.listdir(self.fs.state), ["usage.json"])

    def test_no_record_writes_nothing(self):
        out = self.fs.run("--no-record")
        self.assertContract(out)
        self.assertFalse(os.path.exists(self.fs.state))
        self.assertEqual(out["today"], {"date": "2026-01-10", "rx": 0, "tx": 0})

    def test_no_record_reads_but_leaves_state_alone(self):
        self.fs.run()
        self.fs.age_state()
        with open(self.fs.usage_file, "rb") as f:
            before = f.read()
        self.fs.set_counters("wlp0s0", 9000, 900)
        out = self.fs.run("--no-record")
        with open(self.fs.usage_file, "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(out["today"]["date"], "2026-01-10")


class AlwaysJson(Base):
    """Run the real executable, as the bar does."""

    def run_script(self, *args, env=None):
        full = dict(os.environ)
        full.update(env if env is not None else self.fs.env())
        proc = subprocess.run([sys.executable, SCRIPT, *args], env=full,
                              capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        return json.loads(proc.stdout)

    def test_normal_run(self):
        self.fs.add("wlp0s0", physical=True, wireless=True, rx=1, tx=2)
        out = self.run_script("--no-record")
        self.assertEqual(out["link"]["name"], "wlp0s0")
        self.assertIsNone(out["error"])

    def test_missing_sysfs(self):
        env = self.fs.env()
        env["NET_SPEED_SYSFS"] = os.path.join(self.fs.root, "nowhere")
        env["NET_SPEED_PROC"] = os.path.join(self.fs.root, "nowhere")
        out = self.run_script(env=env)
        self.assertIsNone(out["link"])
        self.assertIsNotNone(out["error"])

    def test_bad_arguments(self):
        out = self.run_script("--bogus", "--iface")
        self.assertIn("--bogus", out["error"])
        self.assertIn("--iface", out["error"])

    def test_garbage_counters_and_route_file(self):
        self.fs.add("wlp0s0", physical=True, wireless=True)
        with open(os.path.join(self.fs.sysfs, "wlp0s0", "statistics", "rx_bytes"), "w") as f:
            f.write("garbage")
        with open(os.path.join(self.fs.proc, "net", "route"), "w") as f:
            f.write("header\nshort line\nwlp0s0 zz yy xx 0 0 q r\n")
        out = self.run_script("--no-record")
        self.assertEqual(out["link"]["rx"], 0)


if __name__ == "__main__":
    unittest.main()
