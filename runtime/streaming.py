"""Validated streaming settings shared by the portal and desktop runtime."""

import math


def number(label, default, minimum, maximum, group, step=1, help=""):
    return dict(
        label=label,
        default=default,
        min=minimum,
        max=maximum,
        group=group,
        step=step,
        help=help,
        type="number",
    )


def choice(label, default, options, group, help=""):
    return dict(
        label=label,
        default=default,
        options=options,
        group=group,
        help=help,
        type="select",
    )


def toggle(label, default, group, help=""):
    return dict(label=label, default=default, group=group, help=help, type="boolean")


STREAMING_FIELDS = {
    "remote_pointer_marker": toggle(
        "Show remote pointer marker",
        False,
        "Viewer",
        "Show Xpra's remote pointer position for collaborative observation. The native browser cursor and mouse input remain enabled.",
    ),
    "viewer_scale": choice(
        "Default viewer size",
        "fit",
        ["fit", "original", "integer"],
        "Viewer",
        "Fit fills available space; integer uses whole-number enlargement when space allows.",
    ),
    "canvas_filter": choice(
        "Default canvas filter",
        "fsr",
        ["fsr", "smooth", "crisp"],
        "Viewer",
        "FSR 1 uses client-side EASU + RCAS after decoding, with Smooth fallback. Game and video resolution stay unchanged.",
    ),
    "restore_focus": toggle(
        "Return keyboard focus after header controls", True, "Viewer"
    ),
    "diagnostics_enabled": toggle(
        "Enable streaming diagnostics",
        True,
        "Diagnostics",
        "Capture counters are lightweight. Full statistics are requested only while the panel is open.",
    ),
    "metrics_interval": number(
        "Diagnostic sample interval (seconds)",
        2,
        1,
        10,
        "Diagnostics",
        help="Longer samples reduce diagnostic traffic and smooth fluctuating rates.",
    ),
    "quality": number(
        "Fixed quality",
        0,
        0,
        100,
        "Picture and motion",
        help="0 adapts automatically; 100 uses maximum quality where supported.",
    ),
    "min_quality": number("Minimum quality", 60, 0, 100, "Picture and motion"),
    "speed": number(
        "Fixed encoding speed",
        0,
        0,
        100,
        "Picture and motion",
        help="0 adapts automatically. Higher values favor faster encoding.",
    ),
    "min_speed": number("Minimum encoding speed", 80, 0, 100, "Picture and motion"),
    "refresh_rate": number(
        "Capture rate (Hz)",
        30,
        1,
        120,
        "Picture and motion",
        help="Capture target; actual frame rate also depends on the game and connection.",
    ),
    "auto_refresh_delay": number(
        "Clean image refresh delay (seconds)",
        0.25,
        0,
        10,
        "Picture and motion",
        0.01,
        "Delay before refreshing a lossy frame. 0 disables automatic refresh.",
    ),
    "bandwidth_mbps": number(
        "Bandwidth limit (Mbps)",
        0,
        0,
        1000,
        "Connection",
        0.1,
        "Adaptive encoding budget per viewer; 0 removes the fixed limit. This is not a strict network traffic shaper.",
    ),
    "bandwidth_detection": toggle("Adapt to available bandwidth", True, "Connection"),
    "compression_level": number(
        "Packet compression level",
        0,
        0,
        9,
        "Connection",
        help="0 avoids extra compression work on already encoded images.",
    ),
    "encoding": choice(
        "Preferred encoding",
        "auto",
        ["auto", "h264", "webp", "jpeg", "png", "rgb"],
        "Codecs",
        "Auto negotiates a codec supported by both the runtime and browser.",
    ),
    "encodings": choice(
        "Allowed encodings",
        "all",
        ["all", "h264,webp,jpeg", "webp,jpeg,png,rgb", "png,rgb"],
        "Codecs",
    ),
    "video_encoders": choice(
        "Video encoder",
        "all",
        ["all", "openh264", "x264", "vpx", "none"],
        "Codecs",
        "Explicit encoders require a runtime image containing that encoder.",
    ),
    "csc_modules": choice(
        "Color conversion", "all", ["all", "libyuv", "swscale", "none"], "Codecs"
    ),
    "video_scaling": toggle(
        "Allow encoder downscaling",
        False,
        "Codecs",
        "Keep off to preserve detail at the game's original resolution.",
    ),
    "xshm": toggle("Use shared-memory capture (XSHM)", True, "Capture and latency"),
    "idle_fix": toggle(
        "Restore low latency after inactivity", True, "Capture and latency"
    ),
    "batch_match_refresh": toggle(
        "Match batching to capture rate",
        True,
        "Capture and latency",
        "Recommended. Raises the effective minimum queue to one capture interval. "
        "Disable to use an independent minimum; lower delays may increase CPU and traffic.",
    ),
    "batch_min_delay": number(
        "Minimum frame queue (ms)", 5, 0, 1000, "Capture and latency"
    ),
    "batch_start_delay": number(
        "Initial frame queue (ms)", 10, 0, 1000, "Capture and latency"
    ),
    "batch_max_delay": number(
        "Maximum frame queue (ms)", 40, 1, 1000, "Capture and latency"
    ),
    "batch_expire_delay": number(
        "Frame queue expiration (ms)", 50, 1, 2000, "Capture and latency"
    ),
    "socket_nodelay": toggle(
        "Send TCP packets immediately", True, "Capture and latency"
    ),
    "socket_cork": toggle(
        "Combine TCP packets before sending", False, "Capture and latency"
    ),
}
# Saved Xpra profiles remain readable; these fields have no Selkies effect.
LEGACY_FIELDS = {
    'remote_pointer_marker', 'quality', 'min_quality', 'speed', 'min_speed',
    'auto_refresh_delay', 'bandwidth_detection', 'compression_level',
    'encoding', 'encodings', 'video_encoders', 'csc_modules', 'video_scaling',
    'xshm', 'idle_fix', 'batch_match_refresh', 'batch_min_delay',
    'batch_start_delay', 'batch_max_delay', 'batch_expire_delay',
    'socket_nodelay', 'socket_cork',
}
for key in LEGACY_FIELDS:
    STREAMING_FIELDS[key]['deprecated'] = True
STREAMING_FIELDS['bandwidth_mbps'].update(default=8, label='Video bitrate (Mbps)',
    help='Video encoding target, not a strict traffic shaper. Legacy 0 uses 8 Mbps.')
STREAMING_FIELDS.update({
    'video_codec': choice('Video codec', 'h264enc', ['h264enc', 'jpeg'], 'Video',
        'H.264 uses hardware when supported and falls back to software.'),
    'rate_control': choice('Video rate control', 'cbr', ['cbr', 'crf'], 'Video'),
    'video_crf': number('Video CRF', 25, 5, 50, 'Video',
        help='Lower values improve quality at greater bandwidth. Used in CRF mode.'),
    'jpeg_quality': number('JPEG quality', 80, 1, 100, 'Video'),
    'audio_enabled': toggle('Enable game audio', True, 'Audio'),
    'audio_bitrate': choice('Audio bitrate (kbps)', 128,
        [32, 48, 64, 96, 128, 192, 256, 320], 'Audio'),
})
# Select fields use string values, including Opus bitrate presets.
STREAMING_FIELDS['audio_bitrate']['default'] = '128'
STREAMING_FIELDS['audio_bitrate']['options'] = [str(x) for x in STREAMING_FIELDS['audio_bitrate']['options']]
STREAMING_DEFAULTS = {key: field["default"] for key, field in STREAMING_FIELDS.items()}
STREAMING_PRESETS = {
    'balanced': {**STREAMING_DEFAULTS},
    'sharp': {**STREAMING_DEFAULTS, 'bandwidth_mbps': 12, 'video_crf': 18, 'jpeg_quality': 95},
    'low_latency': {**STREAMING_DEFAULTS, 'refresh_rate': 24, 'bandwidth_mbps': 4},
}


def validate_streaming(value, complete=False):
    if not isinstance(value, dict) or set(value) - set(STREAMING_FIELDS):
        raise ValueError("Unknown or invalid streaming settings")
    for key, val in value.items():
        field = STREAMING_FIELDS[key]
        if field["type"] == "boolean":
            valid = type(val) is bool
        elif field["type"] == "select":
            valid = isinstance(val, str) and val in field["options"]
        else:
            valid = (
                type(val) in (int, float)
                and math.isfinite(val)
                and field["min"] <= val <= field["max"]
                and (field["step"] != 1 or type(val) is int)
            )
        if not valid:
            raise ValueError("Invalid streaming setting: " + key)
    result = {**STREAMING_DEFAULTS, **value} if complete else dict(value)
    # Check relationships only once inheritance has been resolved.
    if complete:
        if (
            not result["batch_min_delay"]
            <= result["batch_start_delay"]
            <= result["batch_max_delay"]
        ):
            raise ValueError("Frame queue must satisfy minimum <= initial <= maximum")
        for fixed, minimum in (("quality", "min_quality"), ("speed", "min_speed")):
            if result[fixed] and result[fixed] < result[minimum]:
                raise ValueError(f"{fixed} must be 0 (automatic) or at least {minimum}")
        allowed = result["encodings"].split(",")
        if (
            result["encoding"] != "auto"
            and "all" not in allowed
            and result["encoding"] not in allowed
        ):
            raise ValueError("Preferred encoding must be included in allowed encodings")
    return result


def selkies_environment(settings, size):
    """Translate validated admin settings into fixed Selkies backend limits."""
    import re
    if not isinstance(size, str) or not re.fullmatch(r"[0-9]{3,4}x[0-9]{3,4}", size):
        raise ValueError('Resolution must be WIDTHxHEIGHT')
    width, height = map(int, size.split('x'))
    if not (640 <= width <= 3840 and 480 <= height <= 2160):
        raise ValueError('Resolution out of bounds')
    cfg = validate_streaming(settings, complete=True)
    fps = cfg['refresh_rate']
    bitrate = round((cfg['bandwidth_mbps'] or 8) * 1000)
    return {
        'SELKIES_FRAMERATE': f'{fps}-{fps}',
        'SELKIES_VIDEO_BITRATE': f'{bitrate}-{bitrate}',
        'SELKIES_MANUAL_WIDTH': str(width),
        'SELKIES_MANUAL_HEIGHT': str(height),
        'SELKIES_ENABLE_RESIZE': 'false|locked',
        'SELKIES_UI_SHOW_SIDEBAR': 'false',
        'SELKIES_ENCODER': cfg['video_codec'],
        'SELKIES_RATE_CONTROL_MODE': cfg['rate_control'],
        'SELKIES_VIDEO_CRF': f"{cfg['video_crf']}-{cfg['video_crf']}",
        'SELKIES_JPEG_QUALITY': f"{cfg['jpeg_quality']}-{cfg['jpeg_quality']}",
        'SELKIES_VIDEO_STREAMING_MODE': 'true|locked',
        'SELKIES_AUDIO_ENABLED': ('true' if cfg['audio_enabled'] else 'false') + '|locked',
        'SELKIES_AUDIO_BITRATE': str(int(cfg['audio_bitrate']) * 1000),
        'SELKIES_MICROPHONE_ENABLED': 'false|locked',
        'SELKIES_WEBCAM_ENABLED': 'false|locked',
        'SELKIES_COMMAND_ENABLED': 'false|locked',
        'SELKIES_PRINTING_ENABLED': 'false|locked',
        'SELKIES_FILE_TRANSFERS': 'none',
        'SELKIES_ENABLE_BASIC_AUTH': 'false',
        'SELKIES_ALLOWED_ORIGINS': '*',
        'START_DOCKER': 'false',
    }


def runtime_options(settings):
    """Compatibility helper for callers; Xpra arguments are no longer emitted."""
    return [], selkies_environment(settings, '1280x720')
