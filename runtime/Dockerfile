FROM fedora:43
COPY xpra.repo /etc/yum.repos.d/xpra.repo
RUN dnf install -y --setopt=install_weak_deps=False xpra xpra-html5 xpra-x11 gobject-introspection xorg-x11-server-Xvfb xdpyinfo openbox xterm liberation-mono-fonts python3 && dnf clean all && useradd --uid 1000 --create-home player
COPY entrypoint.py /usr/local/bin/gamedock-runtime
RUN chmod 755 /usr/local/bin/gamedock-runtime && mkdir /data && chown player:player /data && mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix && printf 'XTerm*renderFont: true\nXTerm*faceName: Liberation Mono\n' > /home/player/.Xdefaults && chown player:player /home/player/.Xdefaults
USER player
ENV HOME=/home/player DISPLAY=:0 XDG_RUNTIME_DIR=/tmp/gamedock-runtime
EXPOSE 6084
ENTRYPOINT ["python3", "/usr/local/bin/gamedock-runtime"]
CMD ["xterm"]
