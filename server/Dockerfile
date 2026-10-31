# syntax=docker/dockerfile:1
# Official coturn Debian variant builds coturn 4.18.0 from source on trixie-slim.
# Do not replace this with Debian's older vulnerable coturn 4.6.1 package.
ARG COTURN_BASE=coturn/coturn:4.18.0-r0-debian@sha256:bbefd3e1fdfdc0d58770fe01b581fd8b00d9f3a5580d00acb77cf719a6bc78e3
FROM ${COTURN_BASE}
USER root
# The upstream binary has a file capability for low ports. Recreate its inode
# without that xattr so cap_drop=ALL plus no-new-privileges can execute it.
# TLS 443 is mapped by Docker to the unprivileged container TLS port 5349.
RUN cp /usr/bin/turnserver /usr/bin/turnserver.nocap \
 && mv /usr/bin/turnserver.nocap /usr/bin/turnserver
COPY entrypoint.sh healthcheck.sh /opt/ts3-relay/
COPY denied-peers.conf /opt/ts3-relay/
RUN chmod 0555 /opt/ts3-relay/entrypoint.sh /opt/ts3-relay/healthcheck.sh && chmod 0444 /opt/ts3-relay/denied-peers.conf
USER 65534:65534
WORKDIR /tmp
EXPOSE 21113/tcp 21113/udp 5349/tcp 49160-49200/udp
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["/opt/ts3-relay/healthcheck.sh"]
ENTRYPOINT ["/opt/ts3-relay/entrypoint.sh"]
CMD []

