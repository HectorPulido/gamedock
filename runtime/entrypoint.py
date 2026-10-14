#!/usr/bin/env python3
"""Unprivileged GameDock desktop, audio and Selkies session supervisor."""

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from gpu import configured_gpu, prepare_command, configure_software, renderer_info
from streaming import validate_streaming
from selkies_policy import session_environment


def resolution(value):
    if not re.fullmatch(r'[0-9]{3,4}x[0-9]{3,4}', value):
        raise ValueError('Resolution must be WIDTHxHEIGHT')
    width, height = map(int, value.split('x'))
    if not (640 <= width <= 3840 and 480 <= height <= 2160):
        raise ValueError('Resolution out of bounds')
    return value


def display_arguments(size, gpu):
    args = ['Xvfb', os.environ.get('DISPLAY', ':0'), '-screen', '0', size + 'x24',
            '-dpi', '96', '-nolisten', 'tcp', '-noreset', '-ac',
            '+extension', 'GLX', '+extension', 'RANDR', '+extension', 'XFIXES',
            '+extension', 'XTEST', '-nocursor']
    if gpu['vendor'] in ('amd', 'intel'):
        args += ['-glamor', '-dri', gpu['device']]
    return args


def wait_ready(command, process, timeout=20):
    deadline = time.monotonic() + timeout
    while subprocess.run(command, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL).returncode:
        if process.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError(command[0] + ' failed to become ready')
        time.sleep(.1)


def main():
    size = resolution(os.environ.get('GAMEDOCK_RESOLUTION', '1280x720'))
    command = sys.argv[1:]
    if not command:
        raise ValueError('A game command is required')
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp/gamedock-runtime'))
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings = validate_streaming(json.loads(os.environ.get('GAMEDOCK_STREAMING', '{}')), complete=True)
    admin = os.environ.get("GAMEDOCK_ADMIN_SESSION") == "1"
    if admin:
        # Remove additional profile-level locks as well as the default policy.
        for key, value in list(os.environ.items()):
            if key.startswith("SELKIES_"):
                os.environ[key] = value.replace("|locked", "")
    os.environ.update(session_environment(settings, size, admin=admin))
    os.environ['PULSE_RUNTIME_PATH'] = str(runtime / 'pulse')
    (runtime / 'pulse').mkdir(mode=0o700, exist_ok=True)
    gpu = configured_gpu()
    configure_software(gpu)
    os.environ['SELKIES_USE_CPU'] = ('true' if gpu['vendor'] == 'none' else 'false') + ('' if admin else '|locked')
    children = []

    def start(args, **kwargs):
        child = subprocess.Popen(args, **kwargs)
        children.append(child)
        return child

    def stop(*_):
        raise SystemExit(0)

    # Existing optional uinput mode starts only its input helper as root, then
    # drops to UID 1000. The normal runtime needs no root or Linux capabilities.
    root_input = os.getuid() == 0 and os.environ.get('GAMEDOCK_UINPUT') == '1'
    if root_input:
        os.chown(runtime, 1000, 1000)
        os.chown(runtime / 'pulse', 1000, 1000)
        start(['/usr/bin/python3', '/usr/local/bin/gamepad.py'])
        os.setgroups([gid for gid in os.getgroups() if gid != 0])
        os.setgid(1000)
        os.setuid(1000)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        display = start(display_arguments(size, gpu))
        wait_ready(['xdpyinfo'], display)
        if gpu['vendor'] in ('amd', 'intel'):
            probe = subprocess.run(['glxinfo', '-B'], capture_output=True, text=True, timeout=30)
            if probe.returncode:
                raise RuntimeError('GPU OpenGL check failed: ' + probe.stderr[-2000:])
            info = renderer_info(probe.stdout, gpu['vendor'])
            info.update(device=gpu['device'], mode='dri3')
            # Match the selected render node rather than silently using card 0.
            index = int(re.search(r'renderD([0-9]+)$', gpu['device'])[1]) - 128
            os.environ['SELKIES_GPU_ID'] = str(index)
        else:
            command, info = prepare_command(command, gpu)
            # NVIDIA Container Toolkit exposes only the requested GPU; Selkies
            # addresses it by its container-local encoder index, never a UUID.
            os.environ['SELKIES_GPU_ID'] = '-1' if gpu['vendor'] == 'none' else '0'
        (runtime / 'gpu.json').write_text(json.dumps(info))
        print('GameDock graphics: ' + json.dumps(info), flush=True)
        pulse = start(['pulseaudio', '--daemonize=no', '--exit-idle-time=-1',
                       '--log-target=stderr', '--disallow-exit', '--disable-shm'])
        wait_ready(['pactl', 'info'], pulse)
        for args in (
            ['load-module', 'module-null-sink', 'sink_name=output', 'sink_properties=device.description=GameDock'],
            ['set-default-sink', 'output'], ['set-default-source', 'output.monitor']):
            subprocess.run(['pactl'] + args, check=True, stdout=subprocess.DEVNULL)
        rc = runtime / 'openbox.xml'
        rc.write_text('<openbox_config xmlns="http://openbox.org/3.4/rc"><applications><application class="*"><decor>no</decor><maximized>yes</maximized></application></applications></openbox_config>')
        start(['openbox', '--config-file', str(rc)])
        if not root_input:
            start(['/usr/bin/python3', '/usr/local/bin/gamepad.py'])
        start(['selkies', '--addr=127.0.0.1', '--port=8082'])
        start([sys.executable, '/usr/local/bin/selkies_gateway.py'])
        game = start(command, cwd='/data')
        (runtime / 'game.json').write_text(json.dumps({'pid': game.pid}))
        (runtime / 'stream-processes.json').write_text(json.dumps([child.pid for child in children if child is not game]))
        while all(child.poll() is None for child in children):
            time.sleep(.25)
        return next((child.returncode for child in children if child.returncode is not None), 1)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    sys.exit(main())
