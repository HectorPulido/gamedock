#!/usr/bin/env bash
set -Eeuo pipefail

# The HTML5 viewer is interactive game input, not a bandwidth-oriented remote
# desktop.  Xpra's adaptive defaults may batch a full-screen Flash window for
# 100ms or more after observing WAN latency.  Cap that queue and favour
# immediate TCP delivery so clicks and combat turns are not held behind a
# second buffering layer.
export XPRA_BATCH_MIN_DELAY="${XPRA_BATCH_MIN_DELAY:-5}"
export XPRA_BATCH_START_DELAY="${XPRA_BATCH_START_DELAY:-10}"
export XPRA_BATCH_MAX_DELAY="${XPRA_BATCH_MAX_DELAY:-40}"
export XPRA_BATCH_EXPIRE_DELAY="${XPRA_BATCH_EXPIRE_DELAY:-50}"
export XPRA_SOCKET_NODELAY="${XPRA_SOCKET_NODELAY:-1}"
export XPRA_SOCKET_CORK="${XPRA_SOCKET_CORK:-0}"

: "${LOGIN_HOST:=login}"
: "${LOGIN_PORT:=450}"
: "${GAME_ASSETS_PORT:=18080}"
: "${XPRA_PORT:=6084}"
: "${AUTOLOGIN_ENABLED:=0}"
: "${AUTOLOGIN_USER:=}"
: "${AUTOLOGIN_PASSWORD:=}"
: "${AUTOLOGIN_SERVER_SLOT:=1}"
: "${AUTOLOGIN_CHARACTER_SLOT:=0}"
: "${DEFAULT_LANGUAGE:=es}"
: "${HERO_LAUNCHES_B64:=}"

client_dir=/opt/starloco/client
log_dir=/var/log/starloco
pulse_sink=starloco
flash_roaming="$WINEPREFIX/drive_c/users/hector/AppData/Roaming/Macromedia/Flash Player"
display_number=${DISPLAY#:}

if [[ ! "$display_number" =~ ^[0-9]+$ ]]; then
    echo "DISPLAY must use a numeric local display, got: $DISPLAY" >&2
    exit 64
fi

declare -a child_pids=()
declare -a service_pids=()
cleanup_started=0

cleanup() {
    local pid attempt any_running
    (( cleanup_started == 0 )) || return 0
    cleanup_started=1
    rm -f "${XDG_RUNTIME_DIR:-/tmp}/starloco-launches.tsv"
    for pid in "${child_pids[@]:-}"; do
        [[ -n "$pid" ]] || continue
        kill "$pid" 2>/dev/null || true
    done
    pkill -TERM -x Xephyr 2>/dev/null || true
    wineserver64 -k 2>/dev/null || true
    for attempt in $(seq 1 25); do
        any_running=0
        for pid in "${child_pids[@]:-}"; do
            [[ -n "$pid" ]] || continue
            kill -0 "$pid" 2>/dev/null && any_running=1
        done
        (( any_running == 0 )) && break
        sleep 0.2
    done
    for pid in "${child_pids[@]:-}"; do
        [[ -n "$pid" ]] || continue
        kill -KILL "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait_until() {
    local description=$1 timeout_seconds=$2 interval=$3
    shift 3
    local deadline=$((SECONDS + timeout_seconds))
    until "$@"; do
        if (( SECONDS >= deadline )); then
            echo "Timed out waiting for ${description}" >&2
            return 1
        fi
        sleep "$interval"
    done
}

login_ready() { nc -z "$LOGIN_HOST" "$LOGIN_PORT"; }
pulse_ready() { pactl info >/dev/null 2>&1; }
assets_ready() { curl -fsS "http://127.0.0.1:${GAME_ASSETS_PORT}/config.xml" >/dev/null; }
xpra_ready() { curl -fsS "http://127.0.0.1:${XPRA_PORT}/" >/dev/null; }

urlencode() {
    local value=${1-}
    local output=""
    local char hex index
    LC_ALL=C
    for ((index = 0; index < ${#value}; index++)); do
        char=${value:index:1}
        case "$char" in
            [a-zA-Z0-9.~_-]) output+="$char" ;;
            *)
                printf -v hex '%%%02X' "'$char"
                output+="$hex"
                ;;
        esac
    done
    printf '%s' "$output"
}

mkdir -p "$log_dir" "$XDG_RUNTIME_DIR" "$WINEPREFIX"
chmod 700 "$XDG_RUNTIME_DIR"

# `docker restart` preserves the container filesystem but kills PulseAudio.
# Its stale runtime PID/socket would make the next daemon invocation report
# "Daemon already running" and, under `set -e`, restart the whole container.
rm -rf "$XDG_RUNTIME_DIR/pulse"

# Docker restarts preserve the container filesystem. Remove only this
# display's stale X lock/socket before starting a new Xvfb process.
rm -f "/tmp/.X${display_number}-lock" "/tmp/.X11-unix/X${display_number}"

sed -i \
    -e "s#<connserver name=\"Dofus\"[^>]*/>#<connserver name=\"Dofus\" ip=\"${LOGIN_HOST}\" port=\"${LOGIN_PORT}\"/>#" \
    -e "s#<dataserver url=\"[^\"]*\" priority=\"3\" */>#<dataserver url=\"http://127.0.0.1:${GAME_ASSETS_PORT}/\" priority=\"3\" />#" \
    "$client_dir/config.xml"

echo "Waiting for StarLoco login at ${LOGIN_HOST}:${LOGIN_PORT}..."
wait_until "StarLoco login at ${LOGIN_HOST}:${LOGIN_PORT}" 180 2 login_ready

Xvfb "$DISPLAY" -screen 0 800x600x24 -nolisten tcp -ac -noreset \
    >"$log_dir/xvfb.log" 2>&1 &
child_pids+=("$!")
service_pids+=("$!")

wait_until "Xvfb display $DISPLAY" 20 0.2 test -S "/tmp/.X11-unix/X${display_number}"

pulseaudio --daemonize=yes --exit-idle-time=-1 --log-target="file:$log_dir/pulseaudio.log"
wait_until "PulseAudio" 20 0.2 pulse_ready

if ! pactl list short sinks | awk '{print $2}' | grep -qx "$pulse_sink"; then
    pactl load-module module-null-sink \
        sink_name="$pulse_sink" \
        rate=44100 \
        channels=2 \
        sink_properties=device.description=StarLoco >/dev/null
fi
pactl set-default-sink "$pulse_sink"
pactl set-default-source "${pulse_sink}.monitor"

python3 -c "import http.server, os, sys
class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory='$client_dir', **kwargs)
    def end_headers(self):
        self.send_header('Cache-Control', 'public, max-age=86400')
        super().end_headers()
    def translate_path(self, path):
        clean = path.split('?')[0]
        if clean.endswith('.swf'):
            base = os.path.basename(clean)
            if 'undefined' in base:
                base = base.split('undefined')[-1]
            candidate = os.path.join('$client_dir', 'data', 'maps', base)
            if os.path.exists(candidate):
                return candidate
        if clean.startswith('/lang/versions_') and not clean.startswith('/lang/versions_es'):
            return os.path.join('$client_dir', 'lang', 'versions_es.txt')
        if clean.startswith('/lang/swf/') and '_en_' in clean:
            cand = os.path.join('$client_dir', 'lang', 'swf', os.path.basename(clean).replace('_en_', '_es_'))
            if os.path.exists(cand):
                return cand
        return super().translate_path(path)
http.server.ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()
" "$GAME_ASSETS_PORT" \
    >"$log_dir/assets.log" 2>&1 &
child_pids+=("$!")
service_pids+=("$!")

wait_until "client asset server" 20 0.2 assets_ready

xpra shadow "$DISPLAY" \
    "--bind-tcp=0.0.0.0:${XPRA_PORT},auth=none" \
    --html=on \
    --daemon=no \
    --mdns=no \
    --pulseaudio=no \
    --speaker=on \
    --speaker-codec=mp3 \
    "--audio-source=pulse:device=${pulse_sink}.monitor" \
    --microphone=off \
    --notifications=no \
    --system-tray=no \
    --commands=no \
    --shell=no \
    --start-new-commands=no \
    --file-transfer=no \
    --open-files=no \
    --open-url=no \
    --printing=no \
    --clipboard=no \
    --webcam=no \
    --resize-display=no \
    "--bandwidth-limit=${XPRA_BANDWIDTH_LIMIT:-6Mbps}" \
    "--bandwidth-detection=${XPRA_BANDWIDTH_DETECTION:-yes}" \
    --encoding=auto \
    --encodings=h264,webp,jpeg \
    --video-encoders=openh264 \
    --csc-modules=libyuv \
    --compression-level=0 \
    --min-speed=90 \
    --min-quality=30 \
    --auto-refresh-delay=0.25 \
    --refresh-rate=20 \
    >"$log_dir/xpra.log" 2>&1 &
child_pids+=("$!")
service_pids+=("$!")

wait_until "Xpra HTML endpoint" 30 0.2 xpra_ready

wine_kernel="$WINEPREFIX/drive_c/windows/system32/kernel32.dll"
if [[ ! -s "$WINEPREFIX/system.reg" || ! -e "$wine_kernel" ]]; then
    echo "Initializing or repairing the Wine prefix..."
    # A host reboot can interrupt wineboot after system.reg is written but
    # before the Windows runtime exists. This volume contains only derivable
    # client state, so rebuild an incomplete prefix instead of reusing it.
    find "$WINEPREFIX" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    wine64 wineboot.exe --init >"$log_dir/wineboot.log" 2>&1
    wineserver64 -w
    [[ -e "$wine_kernel" ]] || {
        echo "Wine prefix initialization did not create kernel32.dll" >&2
        exit 1
    }
fi

# The bundled 32-bit Flash projector reads the policy from SysWOW64 on a
# 64-bit Wine prefix. Install it in both locations so this also works if the
# base image changes Wine architecture later. LocalStorageLimit=6 suppresses
# Flash's unusable storage-permission panel and lets Dofus persist its LSOs.
for flash_system_dir in \
    "$WINEPREFIX/drive_c/windows/system32/Macromed/Flash" \
    "$WINEPREFIX/drive_c/windows/syswow64/Macromed/Flash"; do
    mkdir -p "$flash_system_dir/FlashPlayerTrust"
    cp /opt/starloco/runtime/mms.cfg "$flash_system_dir/mms.cfg"
    printf '%s\n' 'Z:\\opt\\starloco\\client' >"$flash_system_dir/FlashPlayerTrust/starloco.cfg"
done

mkdir -p "$flash_roaming/#Security/FlashPlayerTrust"
printf '%s\n' 'Z:\\opt\\starloco\\client' \
    >"$flash_roaming/#Security/FlashPlayerTrust/starloco.cfg"

# Dofus asks Flash for unlimited LSO storage. Flash 10's Allow button opens
# Adobe's retired online settings manager instead of completing the request.
# Seed the exact global permission files produced by the known-good native
# client so the dialog cannot block a fresh or recreated Docker client.
python3 - "$flash_roaming/macromedia.com/support/flashplayer/sys" <<'PY'
import base64
import pathlib
import sys

files = {
    "#local/settings.sol": "AL8AAABmVENTTwAEAAAAAAAObG9jYWwvc2V0dGluZ3MAAAAAAAVhbGxvdwEAAAAGYWx3YXlzAQAAAAthbGxvd3NlY3VyZQEAAAAMYWx3YXlzc2VjdXJlAQAAAAZrbGltaXQAwAAAAAAAAAAA",
    "settings.sol": "AL8AAAIWVENTTwAEAAAAAAAIc2V0dGluZ3MAAAAAAARnYWluAEBJAAAAAAAAAAAPZWNob3N1cHByZXNzaW9uAQAAABFkZWZhdWx0bWljcm9waG9uZQIAAAAADWRlZmF1bHRjYW1lcmECAAAAAAxkZWZhdWx0YXVkaW8CAAAAAA1kZWZhdWx0a2xpbWl0AEBZAAAAAAAAAAANZGVmYXVsdGFsd2F5cwEAAAAQY3Jvc3Nkb21haW5BbGxvdwEAAAARY3Jvc3Nkb21haW5BbHdheXMBAAAAGnNlY3VyZUNyb3NzRG9tYWluQ2FjaGVTaXplAL/wAAAAAAAAAAAYYWxsb3dUaGlyZFBhcnR5TFNPQWNjZXNzAQEAAAx0cnVzdGVkUGF0aHMDAAAJAAAOc2FmZWZ1bGxzY3JlZW4BAAAAEWRpc2FsbG93UDJQVXBsaW5rAQAAABhhdXRob3JpemVkRmVhdHVyZXNFeHBpcnkAAAAAAAAAAAAAAA5sYXN0VGltZVBsYXllZABB2qToveYs4AAAB2RvbWFpbnMDAAVsb2NhbAEBAAkxMjcuMC4wLjEBAQAACQAABXBhbmVsAD/wAAAAAAAAAAARZGVidWdnZXJMb2NhbGhvc3QBAQAAD2RlYnVnZ2VyTWFjaGluZQIAAAAAEGRlYnVnZ2VyRG9udFNob3cBAQAAEXdpbmRvd2xlc3NEaXNhYmxlAQAA",
}
root = pathlib.Path(sys.argv[1])
for relative, encoded in files.items():
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(encoded))
PY

set_default_language() {
    local target_wine_prefix=${1:-$WINEPREFIX}
    local target_flash_roaming="$target_wine_prefix/drive_c/users/hector/AppData/Roaming/Macromedia/Flash Player"
    local language_file
    [[ "$DEFAULT_LANGUAGE" =~ ^[a-z]{2}$ ]] || {
        echo "DEFAULT_LANGUAGE must be a two-letter code" >&2
        return 1
    }
    # The projector stores LANGUAGE as a two-byte AMF string at offset 111.
    # Config.xml controls a fresh prefix, while this patch also corrects old
    # persistent Wine volumes that previously saved another language.
    while IFS= read -r language_file; do
        printf '%s' "$DEFAULT_LANGUAGE" | dd of="$language_file" bs=1 seek=111 conv=notrunc status=none
    done < <(find "$target_flash_roaming/#SharedObjects" -type f \
        -path '*/localhost/opt/starloco/client/loader.swf/ANKLANGSO_0.sol' \
        -print 2>/dev/null || true)
}

set_default_language

disable_colorful_tactic() {
    local target_wine_prefix=${1:-$WINEPREFIX}
    local target_flash_roaming="$target_wine_prefix/drive_c/users/hector/AppData/Roaming/Macromedia/Flash Player"

    # Frigost's imported subareas use five-digit custom IDs. The Retro client
    # builds coloured-tactical asset IDs by prefixing the subarea number, but
    # those generated assets do not exist for custom subareas and the whole
    # battlefield is consequently rendered black. Keep every other saved
    # option intact and flip only the AMF boolean stored after this exact key;
    # the generic tactical tiles (1666x) then work on every map.
    python3 - "$target_flash_roaming/#SharedObjects" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
marker = b"\x00\x0eColorfulTactic\x01"
for path in root.rglob("ANKOPTIONSSO.sol") if root.exists() else ():
    data = bytearray(path.read_bytes())
    position = data.find(marker)
    if position < 0:
        continue
    value_position = position + len(marker)
    if value_position >= len(data) or data[value_position] not in (0, 1):
        continue
    if data[value_position] != 0:
        data[value_position] = 0
        path.write_bytes(data)
PY
}

disable_colorful_tactic

isolate_flash_profile() {
    local target_wine_prefix=$1
    local target_flash_roaming="$target_wine_prefix/drive_c/users/hector/AppData/Roaming/Macromedia/Flash Player"
    local private_copy="${target_flash_roaming}.starloco-private"

    [[ -d "$target_flash_roaming" ]] || return 0

    # The surrounding Wine prefix is a cheap hard-link clone. Flash, unlike
    # Wine's registry writer, updates several .sol files in place. Leaving
    # this directory linked makes concurrent heroes overwrite one another's
    # login state, so detach only this small mutable subtree before Dofus runs.
    rm -rf -- "$private_copy"
    cp -a --reflink=auto -- "$target_flash_roaming" "$private_copy"
    rm -rf -- "$target_flash_roaming"
    mv -- "$private_copy" "$target_flash_roaming"
}

has_default_language() {
    local target_wine_prefix=${1:-$WINEPREFIX}
    local target_flash_roaming="$target_wine_prefix/drive_c/users/hector/AppData/Roaming/Macromedia/Flash Player"
    local language_file language_code
    language_file=$(find "$target_flash_roaming/#SharedObjects" -type f \
        -path '*/localhost/opt/starloco/client/loader.swf/ANKLANGSO_0.sol' \
        -print -quit 2>/dev/null || true)
    [[ -n "$language_file" ]] || return 1
    language_code=$(dd if="$language_file" bs=1 skip=111 count=2 2>/dev/null || true)
    [[ "$language_code" == "$DEFAULT_LANGUAGE" ]]
}

screen_state() {
    local window_id=${1:-root}
    local target_display=${2:-$DISPLAY}
    local screenshot="/tmp/starloco-autologin-state-${target_display#:}.png"
    # Each hero runs on its own nested X server. Capture that root window
    # directly so concurrent autologins never inspect another hero's screen.
    timeout 10 import -display "$target_display" -window root "$screenshot" >/dev/null 2>&1 || return 1
    python3 - "$screenshot" <<'PY'
import sys
from PIL import Image

image = Image.open(sys.argv[1]).convert("RGB")

def pixel(x, y):
    return image.getpixel((x, y))

def orange(value):
    red, green, blue = value
    return red > 200 and 70 < green < 180 and blue < 45

def light(value):
    return min(value) > 200

def dark(value):
    return max(value) < 90

def game_hud(value):
    """Match the parchment-coloured strip used only by the in-game HUD."""
    red, green, blue = value
    return 175 <= red <= 235 and 165 <= green <= 225 and 125 <= blue <= 205

# Fixed 800x600 projector coordinates. These test controls unique to each
# screen instead of depending on arbitrary startup delays.
# Sample the orange body, not the white "Play" glyph at the button centre.
# Once Flash resumes a cached session it can skip the character screen and
# land directly on the map. Recognise the broad parchment HUD before looking
# for login controls; otherwise a perfectly working client eventually times
# out and the container kills it. The centre is deliberately omitted because
# it contains the minimap/heart and changes between exploration and combat.
hud_samples = (20, 100, 200, 300, 500, 600, 700)
if sum(game_hud(pixel(x, 510)) for x in hud_samples) >= 5:
    print("in_game")
elif orange(pixel(345, 472)) and orange(pixel(410, 472)):
    print("character")
# The character creation form itself is the terminal state for creator
# sessions. It has a white name input and an orange Accept button.
elif light(pixel(375, 497)) and orange(pixel(575, 492)):
    print("creator_form")
# The preloader has its own configuration/server chooser before it loads the
# login SWF. Its OK button is at a different position from every later view.
elif orange(pixel(684, 192)):
    print("loader")
# A server-selection race can affect both new accounts and existing heroes.
# Its "Elige un servidor" modal overlaps the connection-lost button samples,
# so recognize this more specific state before the generic handoff error.
elif orange(pixel(345, 334)) and orange(pixel(335, 415)):
    print("creator_server_error")
# A failed login-to-game handoff leaves the original login controls visible
# underneath a modal, so this must be detected before the generic login state.
elif orange(pixel(345, 346)) and orange(pixel(455, 346)):
    print("connection_lost")
# Modal backgrounds leave the ordinary username/password controls visible.
elif light(pixel(167, 220)) and light(pixel(167, 283)) and orange(pixel(164, 346)):
    print("login")
elif orange(pixel(335, 415)):
    print("creator_server_picker")
# The first visit opens a server description card with a white OK button and
# an orange border. It must be confirmed before the normal Select button works.
elif light(pixel(620, 404)) and orange(pixel(640, 404)):
    print("creator_server_confirm")
# After choosing the server, the left-hand create button becomes orange.
elif orange(pixel(150, 465)):
    print("creator_ready")
elif dark(pixel(548, 462)):
    print("server")
else:
    print("unknown")
PY
}

run_autologin() {
    local login_user=${1:-$AUTOLOGIN_USER}
    local login_password=${2:-$AUTOLOGIN_PASSWORD}
    local window_id=${3:-root}
    local selected_character_slot=${4:-$AUTOLOGIN_CHARACTER_SLOT}
    local target_display=${5:-$DISPLAY}
    local target_wine_prefix=${6:-$WINEPREFIX}
    local handoff_delay_seconds=${7:-0}
    local attempt state server_x character_x language_x creator_server_confirmed=0
    local character_submit_attempt=-100 login_submit_attempt=-100
    local connection_retry_count=0 server_handoff_delayed=0 login_submitted=0
    local -a slot_x=(0 120 248 376 504 632)

    server_x=${slot_x[$AUTOLOGIN_SERVER_SLOT]:-120}
    character_x=${slot_x[$selected_character_slot]:-120}
    case "$DEFAULT_LANGUAGE" in
        es) language_x=93 ;;
        fr) language_x=122 ;;
        en) language_x=151 ;;
        de) language_x=209 ;;
        pt) language_x=238 ;;
        it) language_x=267 ;;
        nl) language_x=296 ;;
        *) language_x=93 ;;
    esac

    for attempt in $(seq 1 350); do
        if (( attempt > 1 )); then
            sleep 0.1
        fi
        DISPLAY="$target_display" xdotool windowmap "$window_id" windowraise "$window_id" >/dev/null 2>&1 || true
        DISPLAY="$target_display" xdotool windowfocus --sync "$window_id" >/dev/null 2>&1 || true
        state=$(screen_state "$window_id" "$target_display" 2>/dev/null || true)

        case "$state" in
            in_game)
                echo "Autologin reached the game"
                return 0
                ;;
            connection_lost)
                if (( connection_retry_count >= 2 )); then
                    echo "Autologin failed after retrying rejected launch tickets" >&2
                    return 1
                fi
                connection_retry_count=$((connection_retry_count + 1))
                echo "Autologin retrying a rejected launch ticket (${connection_retry_count}/2)" >&2
                DISPLAY="$target_display" xdotool mousemove 400 346 click 1 >/dev/null 2>&1 || true
                sleep 2
                ;;
            creator_form)
                if [[ "$selected_character_slot" == "0" ]]; then
                    return 0
                fi
                ;;
            loader)
                DISPLAY="$target_display" xdotool mousemove 684 192 click 1 >/dev/null 2>&1 || true
                ;;
            creator_server_error)
                creator_server_confirmed=0
                DISPLAY="$target_display" xdotool mousemove 345 334 click 1 >/dev/null 2>&1 || true
                ;;
            creator_server_picker)
                DISPLAY="$target_display" xdotool mousemove 335 420 click 1 >/dev/null 2>&1 || true
                ;;
            creator_server_confirm)
                DISPLAY="$target_display" xdotool mousemove 620 409 click 1 >/dev/null 2>&1 || true
                creator_server_confirmed=1
                ;;
            creator_ready)
                if [[ "$selected_character_slot" == "0" ]]; then
                    DISPLAY="$target_display" xdotool mousemove 150 465 click 1 >/dev/null 2>&1 || true
                    sleep 3
                    return 0
                fi
                ;;
            login)
                # Select the configured flag when the persistent LSO differs.
                # The client can overwrite its LSO after startup, so this is authoritative
                # for both fresh and persistent Wine volumes. Escape must not
                # be used here because it opens the main menu.
                if (( attempt < 10 )) && ! has_default_language "$target_wine_prefix"; then
                    set_default_language "$target_wine_prefix"
                    DISPLAY="$target_display" xdotool mousemove "$language_x" 408 click 1 >/dev/null 2>&1 || true
                    sleep 0.5
                    continue
                fi
                if [[ "$login_submitted" == "1" ]]; then
                    if (( attempt - login_submit_attempt < 30 )); then
                        continue
                    fi
                    login_submitted=0
                fi

                DISPLAY="$target_display" xdotool mousemove 167 220 click 1 key --clearmodifiers ctrl+a \
                    type --delay 20 -- "$login_user" >/dev/null 2>&1 || true
                DISPLAY="$target_display" xdotool mousemove 167 283 click 1 key --clearmodifiers ctrl+a \
                    type --delay 20 -- "$login_password" >/dev/null 2>&1 || true
                DISPLAY="$target_display" xdotool mousemove 164 346 click 1 >/dev/null 2>&1 || true
                login_submitted=1
                login_submit_attempt=$attempt
                ;;
            server)
                if [[ "$selected_character_slot" == "0" ]]; then
                    if [[ "$creator_server_confirmed" == "1" ]]; then
                        DISPLAY="$target_display" xdotool mousemove 548 462 click 1 >/dev/null 2>&1 || true
                    else
                        DISPLAY="$target_display" xdotool mousemove 120 334 click 1 >/dev/null 2>&1 || true
                        sleep 0.2
                        DISPLAY="$target_display" xdotool mousemove 548 462 click 1 >/dev/null 2>&1 || true
                    fi
                fi
                # Server selection for heroes is handled directly by ActionScript in ChooseServer.init
                ;;
            character)
                if [[ "$selected_character_slot" == "0" ]]; then
                    DISPLAY="$target_display" xdotool mousemove 557 492 click 1 >/dev/null 2>&1 || true
                    continue
                fi
                # Character selection is handled directly by ActionScript in ChooseCharacter.init
                character_submit_attempt=$attempt
                ;;
        esac
    done

    echo "Autologin timed out before reaching the game" >&2
    return 1
}

configure_first_run() {
    # Native projector autologin is driven by the screen state so it also
    # survives slower starts and modal dialogs after a Docker restart.
    if [[ "$AUTOLOGIN_ENABLED" == "1" || "$AUTOLOGIN_ENABLED" == "true" ]]; then
        run_autologin
    fi
}

if [[ -z "$HERO_LAUNCHES_B64" && ( "$AUTOLOGIN_ENABLED" == "1" || "$AUTOLOGIN_ENABLED" == "true" ) ]]; then
    if [[ -z "$AUTOLOGIN_USER" || -z "$AUTOLOGIN_PASSWORD" ]]; then
        echo "AUTOLOGIN_ENABLED requires AUTOLOGIN_USER and AUTOLOGIN_PASSWORD" >&2
        exit 64
    fi
    echo "Autologin enabled for account: ${AUTOLOGIN_USER}"
else
    echo "Autologin disabled"
fi

echo "Dockerized StarLoco client ready on port ${XPRA_PORT}"
cd "$client_dir"

launch_single_client() {
    local player_id=$1 login_user=$2 login_password=$3 display_name=$4 character_slot=${5:-1} position=${6:-0}
    local nested_number=$((10 + position)) nested_display=":$((10 + position))"
    local nested_window="" projector_window="" xephyr_pid attempt
    local hero_root="$WINEPREFIX/.starloco-heroes"
    local hero_prefix="$hero_root/${player_id}"
    local hero_sink="hero_${player_id}"
    if ! pactl list short sinks | awk '{print $2}' | grep -qx "$hero_sink"; then
        pactl load-module module-null-sink sink_name="$hero_sink" rate=44100 channels=2 \
            sink_properties="device.description=Hero-${player_id}" >/dev/null
    fi
    rm -f "/tmp/.X${nested_number}-lock" "/tmp/.X11-unix/X${nested_number}"
    DISPLAY="$DISPLAY" Xephyr "$nested_display" -screen 800x600 -nolisten tcp -ac -noreset \
        -name "StarLoco Hero ${player_id}" >>"$log_dir/xephyr-${player_id}.log" 2>&1 &
    xephyr_pid=$!
    for attempt in $(seq 1 75); do
        [[ -S "/tmp/.X11-unix/X${nested_number}" ]] && break
        sleep 0.2
    done
    [[ -S "/tmp/.X11-unix/X${nested_number}" ]] || {
        echo "No nested X display appeared for hero ${display_name}" >&2
        return 1
    }
    # Xephyr does not expose _NET_WM_PID in this headless setup, so searching
    # by its process id returns nothing even though the window is present.
    # Its display-qualified title is deterministic and unique per hero.
    nested_window=$(timeout 15 xdotool search --sync --name "Xephyr on ${nested_display}" 2>/dev/null | tail -1 || true)
    [[ -n "$nested_window" ]] || {
        echo "No parent X11 window appeared for hero ${display_name}" >&2
        return 1
    }

    # Wine assigns every process sharing a prefix to the same wineserver and
    # therefore to the display of the first hero. A hard-link clone gives each
    # hero an independent prefix identity without copying the 1.6 GB base.
    # Wine replaces registry files atomically when writing them, so subsequent
    # per-hero changes naturally detach from the shared inodes.
    install -d -m 0700 "$hero_root"
    rm -rf -- "$hero_prefix"
    install -d -m 0700 "$hero_prefix"
    find "$WINEPREFIX" -mindepth 1 -maxdepth 1 ! -name '.starloco-heroes' \
        -exec cp -al -- '{}' "$hero_prefix"/ \;
    isolate_flash_profile "$hero_prefix"
    set_default_language "$hero_prefix"
    disable_colorful_tactic "$hero_prefix"
    printf 'accountToken=%s&password=%s&characterId=%s&serverId=%s\n' \
        "$login_user" "$login_password" "${player_id:-0}" "${AUTOLOGIN_SERVER_SLOT:-601}" \
        | tee "$hero_prefix/drive_c/starloco-auth.txt" >"$hero_prefix/drive_c/auth.txt"
    DISPLAY="$nested_display" PULSE_SINK="$hero_sink" WINEPREFIX="$hero_prefix" \
        wine64 ./Dofus.exe >>"$log_dir/dofus-${player_id}.log" 2>&1 &
    for attempt in $(seq 1 300); do
        sleep 0.05
        projector_window=$(DISPLAY="$nested_display" xdotool search --onlyvisible --name 'Dofus Retro' 2>/dev/null | tail -1 || true)
        [[ -n "$projector_window" ]] && break
    done
    if [[ -z "$projector_window" ]]; then
        echo "No X11 window appeared for hero ${display_name}" >&2
        return 1
    fi
    printf '%s\t%s\t%s\t%s\t%s\n' "$player_id" "$nested_window" "$nested_display" "$projector_window" "$display_name" \
        >>"$XDG_RUNTIME_DIR/starloco-windows.tsv"
    DISPLAY="$nested_display" xdotool windowfocus --sync "$projector_window" >/dev/null 2>&1 || true

    echo "Autologin starting for hero: ${display_name}"
    run_autologin "$login_user" "$login_password" "$projector_window" "$character_slot" "$nested_display" "$hero_prefix" "$position"
    echo "Autologin completed for hero: ${display_name}"

    # Once every hero is ready, the normal focus command maps the leader.
    xdotool windowunmap "$nested_window" >/dev/null 2>&1 || true
}

if [[ -n "$HERO_LAUNCHES_B64" ]]; then
    declare -a launch_pids=()
    launch_failed=0
    leader_player=""
    launches_file="$XDG_RUNTIME_DIR/starloco-launches.tsv"
    : >"$XDG_RUNTIME_DIR/starloco-windows.tsv"
    rm -f "$XDG_RUNTIME_DIR/starloco-ready"
    umask 077
    python3 - "$HERO_LAUNCHES_B64" >"$launches_file" <<'PY'
import base64, json, sys

value = sys.argv[1]
value += "=" * (-len(value) % 4)
launches = json.loads(base64.urlsafe_b64decode(value))
if not isinstance(launches, list) or not launches:
    raise ValueError("at least one hero launch is required")
for item in launches:
    if not isinstance(item, dict):
        raise ValueError("each hero launch must be an object")
    safe = lambda v: str(v).replace("\t", " ").replace("\n", " ")
    print("\t".join((safe(item["playerId"]), safe(item["username"]), safe(item["password"]), safe(item["name"]), safe(item.get("characterSlot", 1)), safe(item.get("position", 0)))))
PY
    while IFS=$'\t' read -r player_id login_user login_password display_name character_slot position; do
        [[ -n "$leader_player" ]] || leader_player=$player_id
        launch_single_client "$player_id" "$login_user" "$login_password" "$display_name" "$character_slot" "$position" &
        launch_pids+=("$!")
    done <"$launches_file"
    rm -f "$launches_file"
    for launch_pid in "${launch_pids[@]}"; do
        wait "$launch_pid" || launch_failed=1
    done
    [[ "$launch_failed" == "0" ]] || {
        echo "At least one hero failed to start" >&2
        exit 1
    }
    touch "$XDG_RUNTIME_DIR/starloco-ready"
    [[ -n "$leader_player" ]] && /usr/local/bin/starloco-client-control focus "$leader_player" >/dev/null 2>&1 || true
    while sleep 5; do
        for service_pid in "${service_pids[@]}"; do
            if ! kill -0 "$service_pid" 2>/dev/null; then
                echo "A required graphical service exited after startup" >&2
                exit 1
            fi
        done
        if ! /usr/local/bin/starloco-client-control status >/dev/null; then
            echo "A hero window exited after startup" >&2
            exit 1
        fi
    done
else
    configure_first_run &
    child_pids+=("$!")
    while true; do
        wine64 ./Dofus.exe >>"$log_dir/dofus.log" 2>&1 || true
        echo "$(date -Iseconds) Dofus exited; restarting in 2 seconds" >>"$log_dir/dofus.log"
        sleep 2
    done
fi