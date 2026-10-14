ARG BASE_IMAGE=gamedock-runtime:local
FROM ${BASE_IMAGE}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends openttd openttd-opengfx && rm -rf /var/lib/apt/lists/*
COPY launch.sh /usr/local/bin/launch-openttd
RUN chmod 755 /usr/local/bin/launch-openttd
USER 1000:1000
ENV XDG_CONFIG_HOME=/data/config XDG_DATA_HOME=/data/data
CMD ["/usr/local/bin/launch-openttd"]
