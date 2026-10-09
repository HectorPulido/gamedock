#!/bin/sh
set -eu
exec openttd -c /data/openttd.cfg -r "${GAMEDOCK_RESOLUTION:-1280x720}" -v sdl -b 32bpp-anim -s null -m null
