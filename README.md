# omarchy-net-speed

Live network speed for the Omarchy bar. The bar shows the speed of the
physical Wi-Fi or Ethernet link in two small rows: upload in blue on top and
download in green below. Click it and a panel opens with the link and the VPN
tunnel side by side, a marker saying whether a VPN is up, a short speed graph,
and the data used today and over the last seven days.

The colours are chosen so that neither row looks like a warning. Red and amber
mean a problem in the other brightwalker25 widgets, so upload avoids them;
blue carries no meaning of its own. Blue and green are also easy to tell apart
with red-green colour blindness, the common kind, which red and green are not.
With the rare blue-yellow kind they look much alike, so the arrows and the
fixed order (upload on top) say which is which without the colour.

```bash
omarchy plugin add https://github.com/brightwalker25/omarchy-net-speed.git --enable
```

The collector ships inside the plugin and is found relative to it, so there is
no symlink or PATH step. To remove it:

```bash
omarchy plugin disable brightwalker25.net-speed
omarchy plugin remove brightwalker25.net-speed
```

Removing the plugin leaves the usage history in `~/.local/state/omarchy-net-speed`;
delete that folder too to remove every trace.

[docs/usage.md](docs/usage.md) covers placing the widget, the settings, the
development install, running the collector by hand, and uninstalling.

## What it shows

![The bar rows and the panel with a VPN up](preview.png)

![The panel with the VPN down](docs/panel-vpn-down.png)

| Where | What |
|---|---|
| Bar | `↑` upload over `↓` download on the physical link, at a fixed width so the bar does not shift as the figures change |
| Panel header | The interface being measured with an icon for its kind (Wi-Fi, Ethernet, USB, USB tether), its kind, whether it was chosen automatically or pinned, and a green "VPN up: wg0" or amber "VPN down" |
| Speed | current upload and download for the link and for the tunnel, in the same two columns |
| Overhead | how much more the link carried than the tunnel over the last minute, when a tunnel is up and busy |
| Graph | download and upload on the link over the last 120 samples (two minutes at the default interval), scaled to the busiest moment in view |
| Data used | upload and download for today and each of the last seven days, with a total |

Clicking the readout toggles the panel, and a middle click takes a fresh
sample at once.

## Design

A collector script prints one JSON snapshot; the QML renders it. This is the
same shape as `omarchy-system` and `omarchy-vpn-check`, and it means every
decision about which interface is which lives in one testable file that runs
fine from a terminal:

```bash
./bin/net-speed --no-record            # one snapshot, without touching the usage file
./bin/net-speed --iface wlp0s0         # measure a named interface instead
python3 -m unittest discover -s tests  # the collector's tests, on made-up sysfs trees
```

The collector is stateless apart from the usage file. Byte counters are
printed raw beside a monotonic timestamp, and the bar widget turns two
consecutive snapshots into a rate. Nothing sleeps and nothing runs a
subprocess: one call is a pass over `/sys/class/net` and one small file, which
is why it can run every second.

The bar widget is the only thing that runs the collector. The panel reads the
widget's snapshot, rates and history and draws them, so the bar and the panel
can never disagree about the current speed.

### Why it measures the physical link, not the default route

The usual way to decide which interface to watch is to follow the default
route. On a machine with a VPN that gives the wrong answer, in two different
ways.

A VPN kill switch commonly works by adding a dummy interface that holds a
default route with a better metric than the real connection. Anything that
falls out of the tunnel is routed into the dummy and discarded. The dummy
carries no traffic at all, so a widget following the route would show zero
permanently while the machine is busy.

When the tunnel is up, the default route may instead point at the tunnel
itself. A widget following it would then show the tunnel's traffic and call it
the connection's, and nothing at all when the VPN is off.

So the bar measures the interface that actually puts bits on the air or the
wire. An interface counts as physical when the kernel gives it a device node
(`/sys/class/net/<name>/device`), which Wi-Fi cards, Ethernet ports and USB
adapters have and tunnels, dummies and bridges do not. Among the physical
interfaces that are up, the one with the best default route, IPv4 or IPv6,
wins. If none of them has a default route, the one that has moved the most
data is used. If you would rather choose yourself, set `interface` to a name
and it is used as given.

Some USB drivers never report link state, so the kernel leaves the interface's
state at "unknown". Android USB tethering (`rndis_host`) and iPhone tethering
(`ipheth`) both work this way. Such an interface counts as up when it is
enabled and has a carrier. The panel shows it as "USB tether".

The tunnel is found separately: the first tunnel interface that is up
(WireGuard, OpenVPN's `tun`, and the interfaces Proton, Tailscale, NordVPN and
Mullvad create), preferring one that carries a default route.

### What Overhead means

Everything that goes through the tunnel also crosses the physical link, but
wrapped: each packet gains the tunnel's own headers, and the link also carries
the tunnel's handshakes and keepalives. So over the same stretch of time the
link moves more bytes than the tunnel does.

The Overhead line is that difference as a share of the tunnel's traffic, over
the last sixty seconds. A figure of 8% means the link carried 8% more than the
tunnel delivered. It only appears while a tunnel is up and has averaged at
least 1 KB/s over the minute, since a percentage of almost nothing is noise.

Anything on the link that bypasses the tunnel is counted in the difference
too: traffic to a printer or another machine on the local network, or apps
excluded by a split tunnel. The figure is therefore an upper bound on what the
VPN protocol costs, not a measurement of the protocol alone.

### Data used

Daily totals are counted on physical interfaces only, summed. Tunnel traffic is
already inside those figures, so counting the tunnel too would count it twice.

Counters reset when the machine reboots or an interface is recreated. The
collector keeps the last counter it saw for each interface along with the boot
id, and when a counter goes backwards or the boot id changes it counts the new
value from zero rather than subtracting across the reset. The totals are
written to `~/.local/state/omarchy-net-speed/usage.json` (under
`$XDG_STATE_HOME` when that is set) at most once every 30 seconds, and 31 days
are kept. A damaged file is replaced rather than stopping the widget.

The totals only cover time the bar was running. Data moved while the shell was
stopped, or before the plugin was installed, is not in them.

## What it never does

- It never runs a speed test. Every figure is the traffic the machine is
  already carrying, read from the kernel's own counters.
- It makes no network calls of any kind.
- It runs with ordinary user rights and installs nothing outside the plugin
  folder, apart from the usage file under `~/.local/state`.
- It runs no subprocesses. The collector is Python 3 with the standard library
  only.

## Settings

| Key | Default | Effect |
|---|---|---|
| `intervalMs` | 1000 | How often the collector runs, from 500 to 5000 milliseconds |
| `interface` | `auto` | `auto` picks the physical link as described above; an interface name pins it |
| `units` | `bits` | `bits` shows Kb/s and Mb/s on a 1000 base, as broadband speeds are quoted; `bytes` shows KB/s and MB/s on a 1024 base |

Rates below 10 are shown with one decimal place and larger ones without, so
the readout stays short. Data used is always shown in bytes. To change a
setting from a terminal:

```bash
omarchy bar set brightwalker25.net-speed units bytes
```

## Requirements

Python 3 and a Linux `/sys` are all it needs.

## Acknowledgements

Inspired by [NetworkStats](https://github.com/Turing-Cat/NetworkStats). No code
was taken from it.

The bar widget and the panel scaffolding are derived from Omarchy's own shell
plugins, which are MIT licensed: Copyright (c) David Heinemeier Hansson,
https://github.com/basecamp/omarchy. The injectPanel / open / close /
closeForPopoutSwitch contract in `BarWidget.qml` follows the `omarchy.weather`
bar widget, and the panel's open/close and IPC scaffolding follows
`omarchy.weather` and `omarchy.agents`. Omarchy's copyright and permission
notice is reproduced in `LICENSE`.

## Written with AI help

Yes, an AI helped write this. No, it is not Skynet (or is it? 😉). Either
way, I have checked the code to make sure it is not plotting Judgment Day. If
that still puts you off, no hard feelings. The whole point of Linux is that you
decide what runs on your computer.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Licence

MIT. See `LICENSE`.
