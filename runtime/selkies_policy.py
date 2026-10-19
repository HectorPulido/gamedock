"""Runtime presentation policy for portal-authenticated administrator sessions.

The marker is assigned by the portal, never inferred from a username or player
volume. Native controls remain limited by devices and features in the image.
"""
try:
    from .streaming import selkies_environment, validate_streaming
except ImportError:
    from streaming import selkies_environment, validate_streaming


def session_environment(settings, size, admin=False):
    env = selkies_environment(settings, size)
    if not admin:
        return env
    cfg = validate_streaming(settings, complete=True)
    bitrate = round((cfg['bandwidth_mbps'] or 8) * 1000)
    codecs = ['h264enc', 'h265enc', 'vp8enc', 'vp9enc', 'av1enc', 'jpeg']
    preferred = cfg['video_codec']
    codecs.remove(preferred)
    # Selkies enums accept an ordered comma-separated allowed list. Ranges
    # accept INITIAL,MIN-MAX, preserving the profile's initial value.
    env = {key: value.replace('|locked', '') for key, value in env.items()}
    env.update({
        'SELKIES_UI_SHOW_SIDEBAR': 'true',
        'SELKIES_ENABLE_RESIZE': 'true',
        'SELKIES_MANUAL_RESOLUTION': 'true',
        'SELKIES_MANUAL_WIDTH': size.split('x')[0],
        'SELKIES_MANUAL_HEIGHT': size.split('x')[1],
        'SELKIES_FRAMERATE': f"{cfg['refresh_rate']},1-240",
        'SELKIES_VIDEO_BITRATE': f'{bitrate},100-1000000',
        'SELKIES_VIDEO_CRF': f"{cfg['video_crf']},5-50",
        'SELKIES_JPEG_QUALITY': f"{cfg['jpeg_quality']},1-100",
        'SELKIES_ENCODER': ','.join([preferred] + codecs),
        'SELKIES_RATE_CONTROL_MODE': cfg['rate_control'] + ',' + ('crf' if cfg['rate_control'] == 'cbr' else 'cbr'),
        'SELKIES_FILE_TRANSFERS': 'upload,download',
        'SELKIES_COMMAND_ENABLED': 'true',
        'SELKIES_PRINTING_ENABLED': 'true',
        # Devices are requested only when the administrator enables them.
        'SELKIES_MICROPHONE_ENABLED': 'false',
        'SELKIES_WEBCAM_ENABLED': 'false',
    })
    return env
