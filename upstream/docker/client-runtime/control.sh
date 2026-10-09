#!/usr/bin/env bash
set -eu
runtime_dir=${XDG_RUNTIME_DIR:-/tmp/starloco-runtime}

case "${1:-}" in
    status)
        if [[ ! -f "$runtime_dir/starloco-ready" ]]; then
            echo STARTING
            exit 0
        fi
        windows_file="$runtime_dir/starloco-windows.tsv"
        if [[ ! -s "$windows_file" ]]; then
            echo "FAILED: no hero windows were registered"
            exit 1
        fi
        hero_count=0
        while IFS=$'\t' read -r player_id window_id nested_display projector_window _; do
            hero_count=$((hero_count + 1))
            if [[ ! "$player_id" =~ ^[0-9]+$ || ! "$window_id" =~ ^[0-9]+$ ||
                  ! "$nested_display" =~ ^:[0-9]+$ || ! "$projector_window" =~ ^[0-9]+$ ]]; then
                echo "FAILED: malformed hero window registration"
                exit 1
            fi
            if ! xdotool getwindowgeometry "$window_id" >/dev/null 2>&1 ||
               ! DISPLAY="$nested_display" xdotool getwindowgeometry "$projector_window" >/dev/null 2>&1; then
                echo "FAILED: hero $player_id no longer has a live game window"
                exit 1
            fi
        done <"$windows_file"
        if (( hero_count == 0 )); then
            echo "FAILED: no hero windows were registered"
            exit 1
        fi
        echo READY
        ;;
    focus)
        player_id=${2:?player id required}
        row=$(awk -F '\t' -v id="$player_id" '$1 == id { print; exit }' "$runtime_dir/starloco-windows.tsv" 2>/dev/null || true)
        [[ -n "$row" ]] || { echo "Unknown player: $player_id" >&2; exit 1; }
        IFS=$'\t' read -r _ window_id nested_display projector_window _ <<<"$row"
        if [[ -f "$runtime_dir/starloco-audio-loopback" ]]; then
            pactl unload-module "$(cat "$runtime_dir/starloco-audio-loopback")" >/dev/null 2>&1 || true
        fi
        pactl load-module module-loopback source="hero_${player_id}.monitor" sink=starloco \
            latency_msec=30 source_dont_move=true sink_dont_move=true >"$runtime_dir/starloco-audio-loopback"
        # Xvfb intentionally has no desktop window manager, so
        # `_NET_ACTIVE_WINDOW` cannot change the stacking order. Keep every
        # projector running, unmap the hidden heroes, and map/raise only the
        # requested one. This also makes Xpra stream exactly one game window.
        while IFS=$'\t' read -r listed_player listed_window _; do
            [[ -n "$listed_window" ]] || continue
            if [[ "$listed_player" == "$player_id" ]]; then
                xdotool windowmap "$listed_window" windowraise "$listed_window" >/dev/null 2>&1 || true
            else
                xdotool windowunmap "$listed_window" >/dev/null 2>&1 || true
            fi
        done <"$runtime_dir/starloco-windows.tsv"
        # Mapping and raising do not assign keyboard focus without a window
        # manager. Xpra can still route pointer events, which made clicks work
        # while every key was sent to PointerRoot. Focus the selected Flash
        # projector explicitly after the other windows have been unmapped.
        xdotool windowfocus --sync "$window_id" >/dev/null 2>&1 || true
        DISPLAY="$nested_display" xdotool windowfocus --sync "$projector_window" >/dev/null 2>&1 || true
        # Diagnostic focus nudge: Flash reliably accepts keyboard input after
        # a pointer click. Click the extreme lower-right pixel, away from the
        # usable game controls, shortly after swapping the visible hero.
        sleep 0.5
        DISPLAY="$nested_display" xdotool mousemove --sync --window "$projector_window" 799 599 click 1 >/dev/null 2>&1 || true
        ;;
    *)
        echo "usage: starloco-client-control {status|focus PLAYER_ID}" >&2
        exit 64
        ;;
esac
