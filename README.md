# Magneto X local mods

Changes made on the printer (192.168.1.187, stock Magneto OS v1.1.3) that are not from Peopoly.
Copies live here so they can be re-applied if an update overwrites them.

SSH: `ssh -o IdentitiesOnly=yes -i ~/.ssh/magneto_x pi@192.168.1.187`

## KlipperScreen notifications (2026-10-23)

The stock popup was a modal `Gtk.Popover` re-created for every message, with no rate limit. A
fault line toggling 5×/s (`[gcode_button kill_switch]` → `M118 X or Y motion is blocked.`) made
every tap on the screen just close a popup.

`klipperscreen/ks_includes/notifications.py` replaces it for every popup type (echo, warning,
error, KlipperScreen's own messages):

- non-modal: taps outside the toast reach the screen; tapping the toast dismisses it
- a repeat of the message on screen bumps a `×N` counter (no new popup, no screen wake)
- the toast changes message at most every 2 s, unless a more severe message arrives
- errors are never dropped; a dismissed error that keeps arriving pops again every 60 s
- ≥10 messages in 5 s shows a "message flood N/s" banner that stays up while it lasts
- everything goes to `KlipperScreen.log`: first occurrence at once, repeats as summaries

`klipperscreen/screen.py.patch` makes `show_popup_message` / `close_popup_message` delegate to it.

Install (KlipperScreen on the printer is a zip install, not git):

```
scp klipperscreen/ks_includes/notifications.py pi@192.168.1.187:KlipperScreen/ks_includes/
ssh pi@192.168.1.187 'cd KlipperScreen && patch -p1' < klipperscreen/screen.py.patch
curl -X POST "http://192.168.1.187:7125/machine/services/restart?service=KlipperScreen"
```

Rollback: on the printer, `cp KlipperScreen/screen.py.bak-20261023 KlipperScreen/screen.py`,
delete `KlipperScreen/ks_includes/notifications.py`, restart KlipperScreen as above.
Full pre-patch copy: `~/KlipperScreen-backup-20261023.tar.gz`.

## Wi-Fi recovery (2026-10-23)

The Unisoc driver corrupts its keys after a failed roam between access points; wpa_supplicant
then reports a wrong password and NetworkManager gives up for good.

- The home Wi-Fi profile is pinned to the BSSID of one 5 GHz access point so it never roams:
  `nmcli con modify <profile> 802-11-wireless.bssid <AP BSSID>`
- An unpinned copy with autoconnect off is the fallback:
  `nmcli con clone <profile> <profile>-any && nmcli con modify <profile>-any connection.autoconnect no`
- `wifi/wifi-recover.sh` runs every minute from pi's crontab and reconnects after 2 minutes down.
  It reads the two profile names from `~/wifi-watch/wifi-recover.conf` on the printer
  (`PINNED=<profile>` and `FALLBACK=<profile>-any`), which is deliberately not in this repo.
  Its header has the removal steps. It logs `RECOVER` lines to `printer_data/logs/wifi-watch.log`.

## License

Everything here is MIT (see `LICENSE`) except `klipperscreen/`. That folder modifies
[KlipperScreen](https://github.com/KlipperScreen/KlipperScreen), which is licensed under the GNU
Affero General Public License v3.0, so `screen.py.patch` and `ks_includes/notifications.py` are
distributed under AGPL-3.0 too. `klipperscreen/LICENSE` is a copy of
[KlipperScreen's license](https://github.com/KlipperScreen/KlipperScreen/blob/master/LICENSE).
