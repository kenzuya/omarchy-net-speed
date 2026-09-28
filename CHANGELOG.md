# Changelog

## Unreleased

### Added

- The panel header shows an icon for the link's kind to the left of the
  interface name: Wi-Fi, Ethernet, USB, USB tether, or a generic network
  icon for anything else. When no link is up it shows a disconnected icon
  in the dim colour.

## 0.3.2 - 2026-09-28

### Fixed

- USB tethering from an Android phone is detected. The `rndis_host` driver
  never reports link state, so the kernel shows the interface as "unknown"
  instead of "up". The widget only accepted "up", so it found no link at all
  and the bar showed nothing. An "unknown" interface now counts as up when it
  is enabled and has a carrier. The same applies to iPhone tethering
  (`ipheth`) and to other USB network drivers that behave like this.

### Changed

- IPv6 default routes are used when picking the link, as well as IPv4 ones.
  On a network that only has an IPv6 default route, the routed interface now
  wins. Before this, the widget picked whichever interface had moved the most
  data. Reject routes, such as the kernel's unreachable default, are ignored.
- Tethering has its own kind, `tether`, which the panel shows as
  "USB tether". It is used for the `rndis_host` and `ipheth` drivers and for
  the RNDIS USB class. Other USB network adapters are still "USB".

## 0.3.1 - 2026-09-26

### Changed

- The graph draws upload in blue (#58a6ff) and download in green (#3fb950),
  the colours the bar already uses. Before this, download was drawn in the
  theme's text colour and upload in a darker shade of it. Two greys that
  differ only in brightness are hard to tell apart where the lines cross or
  sit close together, and they gave no link back to the bar. With the same
  colours in both places, blue always means upload and green always means
  download.
- The legend under the graph uses the same colours, because it draws its
  swatches from the graph.
- The live rates for the physical link (the Wi-Fi row) and for the tunnel are
  coloured the same way, so the numbers match the graph beside them and the
  bar above them.
- A row with nothing to measure stays dim, for example the tunnel row when
  the VPN is down. A coloured "not up" or "--" would look like a live
  reading.
- The column headings and the DATA USED rows are not coloured. The headings
  already carry the arrows, and the usage rows are totals over a day, not
  live rates. Colour there would stop marking what is happening now.
- The panel reads the colours from the bar widget instead of keeping its own
  copy, so changing them in `BarWidget.qml` changes both places at once. The
  panel falls back to the same two values if it is ever loaded without the
  bar widget.
- In the graph, the lines have no arrows or row order to fall back on, so the
  note under 0.3.0 about blue-yellow colour blindness applies more strongly.
  There, the legend and the fact that download is drawn on top are what tell
  the two lines apart.
- `preview.png` is retaken to show the coloured panel. Like the old one, it
  holds only the chunks needed to display it (IHDR, IDAT and IEND). Cropping
  had added a timestamp and text chunks, and they were removed so the image
  publishes nothing about when or how it was made.
  `docs/panel-vpn-down.png` is retaken the same way, with the same
  three chunks only.

## 0.3.0 - 2026-09-26

### Changed

- The two bar rows set `textFormat: Text.PlainText`, like every text in the
  panel, so nothing shown in the bar can be read as rich text.
- `INSTALL.md` is now `docs/usage.md`, and the README carries the removal
  commands itself.
- Upload is mid blue (#58a6ff) instead of violet. It reads more clearly on
  the bar and sits better beside the green. Blue and green stay easy to tell
  apart with red-green colour blindness; with the rare blue-yellow kind they
  are closer, and the arrows and row order carry the meaning.
- The display name is now Net Speed Colour, since another plugin in the
  directory is already called Net Speed. The id stays brightwalker25.net-speed.
- Added `preview.png`, the bar rows with the panel open and a VPN up, and
  `docs/panel-vpn-down.png`, the panel with the VPN down. Both are shown in
  the README and carry no metadata.

## 0.2.0 - 2026-09-26

### Changed

- Rates are shown in bits by default (b/s, Kb/s, Mb/s, Gb/s on a 1000 base),
  the unit broadband speeds are quoted in, still changing unit with the
  speed. The bits labels are shorter than before (Mb/s rather than Mbit/s).
  Set `units` to `bytes` for the old KB/s and MB/s readout.
- The bar rows are coloured, arrow and figure alike: upload in violet and
  download in green. Red and orange were tried first and dropped, because
  they read as a warning (red and amber mean a problem in the other
  brightwalker25 widgets) and red is hard to tell from green with red-green
  colour blindness. Violet carries no meaning and stays distinct from green.

## 0.1.0 - 2026-09-26

### Added

- A bar readout of upload over download for the physical Wi-Fi or Ethernet
  link, at a fixed width so the bar does not shift as the figures change.
  Clicking it opens the panel; a middle click takes a fresh sample.
- Automatic link selection that ignores tunnels and kill-switch dummy
  interfaces. Only interfaces with a device node are candidates, and among
  those that are up the one with the best default route wins. The
  `interface` setting pins a named interface instead.
- A panel with the link and the VPN tunnel side by side, a green "VPN up" or
  amber "VPN down" marker, an Overhead line comparing link and tunnel traffic
  over the last minute, and a graph of the link's recent download and upload.
- Data used today and on each of the last seven days, counted on physical
  interfaces only and carried across reboots and counter resets. The history
  is kept in `~/.local/state/omarchy-net-speed/usage.json`, for 31 days.
- Settings for the refresh interval (500 to 5000 ms), the interface, and
  whether rates are shown in bytes or bits.
- `bin/net-speed`, the collector: Python 3 standard library only, no
  subprocesses, no network calls, and tests that run on made-up sysfs trees.
