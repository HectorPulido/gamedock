FROM fedora:43

# Keep the pinned repository definition in-tree.  A remote ADD makes every
# client-only rebuild depend on GitHub being available even when every package
# layer is already cached, which has repeatedly blocked DEV hotfixes with 503s.
COPY docker/client-runtime/xpra.repo /etc/yum.repos.d/xpra.repo

RUN dnf install -y --setopt=install_weak_deps=False \
        curl \
        nmap-ncat \
        pulseaudio \
        pulseaudio-utils \
        wine \
        wine-pulseaudio \
        wine-system-winefonts \
        xdotool \
        xorg-x11-server-Xvfb \
        xpra \
        xpra-audio-server \
    && dnf clean all \
    && useradd --uid 1000 --create-home --shell /bin/bash hector \
    && install -d -m 0700 -o hector -g hector /tmp/runtime-hector \
    && install -d -m 0755 -o hector -g hector /opt/starloco/client /var/log/starloco /wine-prefix

# Dofus.exe and the bundled standalone Flash projector are PE32 binaries.
# Fedora's Wine meta-package can resolve to WoW64-only in containers, so keep
# the native i686 loader and PulseAudio driver explicit.
RUN dnf install -y --setopt=install_weak_deps=False \
        wine-core.i686 \
        wine-pulseaudio.i686 \
    && dnf clean all

# The browser client and the X11 shadow implementation are weak dependencies
# of Xpra. They are both required by this runtime, so keep them explicit while
# leaving unrelated GPU extras disabled.
RUN dnf install -y --setopt=install_weak_deps=False \
        gobject-introspection \
        ImageMagick \
        xpra-html5 \
        xpra-x11 \
        xorg-x11-server-Xephyr \
    && dnf clean all

# Xpra 6.5 can leave an HTML shadow window's batch delay locked at 1000 ms
# after an unmap/remap cycle. Reconcile window idle state on every real input
# event so returning to the game cannot preserve that artificial latency.
COPY docker/client-runtime/patch-xpra-idle.py /tmp/patch-xpra-idle.py
RUN python3 /tmp/patch-xpra-idle.py && rm -f /tmp/patch-xpra-idle.py

COPY --chown=hector:hector starloco-client/resources/app/retroclient/ /opt/starloco/client/
# The stock loader already requests o11.swf. This merged library preserves all
# o11 exports and adds the recovered o13 Frigost objects without replacing the
# loader, so autologin and the browser runtime remain compatible.
COPY --chown=hector:hector starloco-client/resources/app/retroclient/clips/gfx/o11-frigost.swf /opt/starloco/client/clips/gfx/o11.swf
COPY --chown=hector:hector starloco-web/lang/ /opt/starloco/client/lang/
COPY --chown=hector:hector starloco-client/resources/app/mms.cfg /opt/starloco/runtime/mms.cfg
COPY docker/client-runtime/entrypoint.sh /usr/local/bin/starloco-client-runtime
COPY docker/client-runtime/control.sh /usr/local/bin/starloco-client-control
COPY docker/xpra/default-settings.txt /usr/share/xpra/www/default-settings.txt
COPY docker/xpra/audio-unlock.js /usr/share/xpra/www/js/audio-unlock.js
COPY docker/xpra/fit-screen.js /usr/share/xpra/www/js/fit-screen.js

RUN chmod +x /usr/local/bin/starloco-client-runtime /usr/local/bin/starloco-client-control \
    && sed -i '/<\/body>/i\    <script src="js/audio-unlock.js"></script>\n    <script src="js/fit-screen.js"></script>' /usr/share/xpra/www/index.html \
    && rm -f /usr/share/xpra/www/index.html.gz /usr/share/xpra/www/index.html.br

USER hector
ENV HOME=/home/hector
ENV DISPLAY=:0
ENV XDG_RUNTIME_DIR=/tmp/runtime-hector
ENV WINEPREFIX=/wine-prefix
ENV WINEARCH=win64
ENV WINEDEBUG=-all
ENV PULSE_SERVER=unix:/tmp/runtime-hector/pulse/native
# Xvfb and Xpra live in the same container, so MIT-SHM is available and
# avoids the much slower GTK full-screen capture fallback.
ENV XPRA_SHADOW_XSHM=1
ENV XPRA_XSHM=1

EXPOSE 6084

ENTRYPOINT ["/usr/local/bin/starloco-client-runtime"]
