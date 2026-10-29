# Reviewer sandbox images for the AI CLIs that read files with shell commands
# (Codex, Antigravity). One image per CLI, built as separate targets:
#
#   docker build -f docker/reviewer.Dockerfile --target codex -t quantum-oss-triage-reviewer-codex:dev docker
#   docker build -f docker/reviewer.Dockerfile --target agy   -t quantum-oss-triage-reviewer-agy:dev docker
#
# A container holds the CLI and nothing else. At run time the harness mounts
# the read-only review copy, a per-call output folder and a harness-owned home
# that contains only that CLI's sign-in (see harness/adapters/sandbox.py). No
# personal configuration, no other credentials, no Docker socket.
#
# reviewer-seccomp.json is seccomp-default-moby.json (Docker's default profile,
# moby/profiles) with one added rule allowing the namespace syscalls that the
# CLI's own command sandbox (bubblewrap) needs, and the clone flag filters
# removed. Nothing else differs.
FROM debian:bookworm-slim AS base
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git ripgrep procps \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 1000 --create-home --home-dir /home/qot --shell /bin/sh qot
ENV HOME=/home/qot

FROM base AS codex
ARG TARGETARCH
ARG NODE_VERSION=22.20.0
ARG CODEX_VERSION=0.164.0
RUN set -eux; \
    case "$TARGETARCH" in arm64) N=arm64 ;; amd64) N=x64 ;; *) exit 1 ;; esac; \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${N}.tar.gz" \
      | tar -xz -C /usr/local --strip-components=1; \
    npm install -g "@openai/codex@${CODEX_VERSION}"; \
    npm cache clean --force; \
    codex --version
USER qot
WORKDIR /review

FROM base AS agy
ARG TARGETARCH
# From the release manifest at
# https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/linux_<arch>.json
ARG AGY_VERSION=1.4.7
ARG AGY_BUILD=1.4.7-5900205422411776
ARG AGY_SHA512_ARM64=6a9fa0df6300633404571f66ec7924098cc70a9f23ac55c3659139bbcbdd2ea5301fe1ef728d4c064fac65104ea14a2b74421f320a82e5bcf218c482b58e3a16
ARG AGY_SHA512_AMD64=beda760587589f5827b0b516c3ec2c5bd5cd2e91eb0e2533807ba1e990a27dcd63aef0191e0b76fb60feab0d16eaa8210fb79842c34dd4809e257e1712edd152
RUN set -eux; \
    case "$TARGETARCH" in \
      arm64) P=linux-arm; F=cli_linux_arm64.tar.gz; S=$AGY_SHA512_ARM64 ;; \
      amd64) P=linux-x64; F=cli_linux_x64.tar.gz;   S=$AGY_SHA512_AMD64 ;; \
      *) exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/agy.tgz "https://storage.googleapis.com/antigravity-public/antigravity-cli/${AGY_BUILD}/${P}/${F}"; \
    echo "$S  /tmp/agy.tgz" | sha512sum -c -; \
    tar -xzf /tmp/agy.tgz -C /usr/local/bin antigravity; \
    mv /usr/local/bin/antigravity /usr/local/bin/agy; \
    rm /tmp/agy.tgz; \
    agy --version
USER qot
WORKDIR /review
