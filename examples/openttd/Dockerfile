FROM gamedock-runtime:local
USER root
RUN dnf install -y --setopt=install_weak_deps=False openttd openttd-opengfx && dnf clean all
COPY launch.sh /usr/local/bin/launch-openttd
RUN chmod 755 /usr/local/bin/launch-openttd
USER player
ENV XDG_CONFIG_HOME=/data/config XDG_DATA_HOME=/data/data
CMD ["/usr/local/bin/launch-openttd"]
