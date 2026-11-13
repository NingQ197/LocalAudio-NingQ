# syntax=docker/dockerfile:1
ARG DEBIAN_BASE=debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2
FROM ${DEBIAN_BASE} AS build
RUN apt-get update \
 && apt-get upgrade -y \
 && apt-get install -y --no-install-recommends build-essential pkg-config libssl-dev libevent-dev ca-certificates patch \
 && rm -rf /var/lib/apt/lists/*
# Source and base are pinned; Debian security packages are refreshed at build.
ADD --checksum=sha256:28d55294ac596fbd129b293a85e7bb1c5dc4bd15b7fb55c500f355149e5f4e28 https://github.com/coturn/coturn/archive/refs/tags/4.18.0.tar.gz /tmp/coturn.tar.gz
RUN mkdir /build \
 && tar -xzf /tmp/coturn.tar.gz -C /build --strip-components=1
WORKDIR /build
COPY coturn-own-ula.patch /tmp/coturn-own-ula.patch
RUN printf '%s\n' 'c3582728b2b221e7c8713eef0e6b638edc4919507c587f882c8e01e795ad36c3  /tmp/coturn-own-ula.patch' | sha256sum -c - \
 && patch --batch --forward --fuzz=0 -p1 < /tmp/coturn-own-ula.patch
# Credentials are read from configuration into memory. No database backend,
# database client, systemd integration or optional metrics server is needed.
RUN TURN_NO_SQLITE=1 TURN_NO_PQ=1 TURN_NO_MYSQL=1 TURN_NO_MONGO=1 TURN_NO_HIREDIS=1 TURN_NO_SYSTEMD=1 TURN_NO_PROMETHEUS=1 ./configure --prefix=/usr \
 && make -j2 \
 && strip bin/turnserver bin/turnutils_stunclient

# Debian util-linux inherits lastlog2 -> SQLite even without coturn DB support.
# This single-service runtime does not use those tools. Require an exact purge
# plan; retain the independent login/mount packages and every other component.
FROM ${DEBIAN_BASE}
RUN apt-get update \
 && apt-get upgrade -y \
 && apt-get install -y --no-install-recommends libevent-2.1-7t64 libevent-core-2.1-7t64 libevent-extra-2.1-7t64 libevent-openssl-2.1-7t64 libevent-pthreads-2.1-7t64 openssl hostname mawk \
 && apt-get -s purge util-linux liblastlog2-2 libsqlite3-0 > /tmp/runtime-purge-plan \
 && planned=$(awk '$1 == "Remv" || $1 == "Purg" { sub(/:.*/, "", $2); print $2 }' /tmp/runtime-purge-plan | sort -u) \
 && expected=$(printf '%s\n' liblastlog2-2 libsqlite3-0 util-linux | sort) \
 && [ "$planned" = "$expected" ] \
 && apt-get purge -y --allow-remove-essential util-linux liblastlog2-2 libsqlite3-0 \
 && rm -f /tmp/runtime-purge-plan \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /build/bin/turnserver /build/bin/turnutils_stunclient /usr/bin/
COPY --from=build /build/LICENSE /usr/share/doc/coturn/LICENSE
COPY entrypoint.sh healthcheck.sh denied-peers.conf ipv6.awk THIRD_PARTY_NOTICES.txt /opt/ts3-relay/
RUN for tool in sh hostname awk mkdir chmod head cat fold sort wc id rm cmp grep find openssl dpkg-query ldd; do command -v "$tool" >/dev/null || exit 1; done \
 && chmod 0555 /opt/ts3-relay/entrypoint.sh /opt/ts3-relay/healthcheck.sh \
 && chmod 0444 /opt/ts3-relay/denied-peers.conf /opt/ts3-relay/ipv6.awk /opt/ts3-relay/THIRD_PARTY_NOTICES.txt \
 && find /usr -xdev -perm /6000 -exec chmod a-s {} +
USER 65534:65534
WORKDIR /tmp
EXPOSE 21113/tcp 21113/udp 5349/tcp 49160-49200/udp
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["/opt/ts3-relay/healthcheck.sh"]
ENTRYPOINT ["/opt/ts3-relay/entrypoint.sh"]
CMD []
