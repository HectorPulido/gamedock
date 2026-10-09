FROM fedora:43
COPY xpra.repo /etc/yum.repos.d/xpra.repo
RUN dnf install -y --setopt=install_weak_deps=False xpra xpra-html5 xpra-x11 xorg-x11-server-Xvfb xorg-x11-utils openbox xterm python3 && dnf clean all && useradd --uid 1000 --create-home player
COPY entrypoint.py /usr/local/bin/gamedock-runtime
RUN chmod 755 /usr/local/bin/gamedock-runtime && mkdir /data && chown player:player /data
USER player
ENV DISPLAY=:0 XDG_RUNTIME_DIR=/tmp/gamedock-runtime
EXPOSE 6084
ENTRYPOINT ["python3", "/usr/local/bin/gamedock-runtime"]
CMD ["xterm"]
