#!/bin/sh
# Wi-Fi watch, part 4: reconnect automatically when Wi-Fi is down (run each minute from pi's crontab).
# Added 2026-10-23. The unisoc driver corrupts its keys after a failed roam, wpa_supplicant then
# reports WRONG_KEY and NetworkManager gives up for good ("no-secrets"). NM never retries by itself.
# PINNED is the home Wi-Fi profile, pinned to one BSSID to stop the roaming; FALLBACK is an unpinned
# copy (autoconnect off) used only if the pinned access point stays unreachable.
#   down 2 min  -> nmcli con up $PINNED
#   down 6+ min -> alternate the pinned and unpinned profiles
#   every 10 min down -> also toggle the Wi-Fi radio first
# Never reboots, so a running print is never touched.
# The profile names live in wifi-recover.conf next to this script (PINNED=..., FALLBACK=...), so
# the network name stays off the public repo.
# Remove: delete this script's line from `crontab -e`, rm /home/pi/wifi-watch/wifi-recover.*,
#   and optionally: nmcli con modify $PINNED 802-11-wireless.bssid ""; nmcli con delete $FALLBACK
LOG=/home/pi/printer_data/logs/wifi-watch.log
COUNT_FILE=/home/pi/wifi-watch/.wifi-recover.count
PINNED=wifi
FALLBACK=wifi-any
[ -f /home/pi/wifi-watch/wifi-recover.conf ] && . /home/pi/wifi-watch/wifi-recover.conf

exec 9>/tmp/wifi-recover.lock
flock -n 9 || exit 0

log() {
    echo "$(date '+%F %T') RECOVER $*" >> "$LOG"
    sync "$LOG"
}

state=$(nmcli -g GENERAL.STATE device show wlan0 2>/dev/null | cut -d' ' -f1)
gw=$(ip -4 route show default dev wlan0 | awk '{print $3; exit}')
if [ "$state" = "100" ] && [ -n "$gw" ] && ping -c2 -W2 "$gw" >/dev/null 2>&1; then
    if [ -s "$COUNT_FILE" ]; then
        log "Wi-Fi back after $(cat "$COUNT_FILE") min down (active: $(nmcli -g GENERAL.CONNECTION device show wlan0))"
        rm -f "$COUNT_FILE"
    fi
    exit 0
fi

n=$(( $(cat "$COUNT_FILE" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$COUNT_FILE"
[ "$n" -lt 2 ] && exit 0

profile=$PINNED
[ "$n" -ge 6 ] && [ $((n % 2)) -eq 1 ] && profile=$FALLBACK
if [ $((n % 10)) -eq 0 ]; then
    log "down $n min: toggling Wi-Fi radio"
    nmcli radio wifi off
    sleep 3
    nmcli radio wifi on
    sleep 5
fi
out=$(nmcli --wait 45 connection up "$profile" 2>&1 | tail -1)
log "down $n min (nm state ${state:-?}): nmcli con up $profile -> $out"
