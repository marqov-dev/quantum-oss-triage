# Disposable worker image for quantum-oss-triage.
#
# Workers clone, build and run other people's code. The image holds tools only:
# no credentials, no agent CLIs, no network at run time unless a stage asks for
# it (dependency install, osv-scanner database fetch). See docs/METHOD.md.
#
# Build:  docker build -f docker/worker.Dockerfile -t quantum-oss-triage-worker:dev .
FROM python:3.12-slim

ARG TARGETARCH
ARG GITLEAKS_VERSION=8.30.1
ARG OSV_SCANNER_VERSION=2.7.0
ARG LYCHEE_VERSION=0.24.2

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git \
 && rm -rf /var/lib/apt/lists/*

# Static binaries from each project's own GitHub release.
RUN set -eux; \
    case "$TARGETARCH" in \
      arm64) GL=arm64; OSV=arm64; LY=aarch64 ;; \
      amd64) GL=x64;   OSV=amd64; LY=x86_64 ;; \
      *) echo "unsupported arch $TARGETARCH"; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${GL}.tar.gz" \
      | tar -xz -C /usr/local/bin gitleaks; \
    curl -fsSL -o /usr/local/bin/osv-scanner \
      "https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/osv-scanner_linux_${OSV}"; \
    chmod +x /usr/local/bin/osv-scanner; \
    curl -fsSL "https://github.com/lycheeverse/lychee/releases/download/lychee-v${LYCHEE_VERSION}/lychee-${LY}-unknown-linux-gnu.tar.gz" \
      | tar -xz -C /usr/local/bin --strip-components=1 "lychee-${LY}-unknown-linux-gnu/lychee"

# Python scanners and the test runner. Versions are recorded per run by
# qot-scan-versions, so an unpinned install is still traceable.
RUN pip install --no-cache-dir ruff bandit semgrep zizmor pytest

# Semgrep's open Python rules, fetched at build time so scans run offline.
RUN mkdir -p /opt/semgrep \
 && curl -fsSL -o /opt/semgrep/python.yml https://semgrep.dev/c/p/python \
 && curl -fsSL -o /opt/semgrep/secrets.yml https://semgrep.dev/c/p/secrets

# Build tools for the dependency stage, added after the scanner layers so a
# rebuild reuses those layers and the scanner versions do not change.
# Compilers and CMake let projects with C, C++ or Cython extensions build.
ARG RUST_VERSION=1.91.1
ARG RUSTUP_VERSION=1.28.2
ARG UV_VERSION=0.11.7
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential cmake ninja-build pkg-config \
 && rm -rf /var/lib/apt/lists/*
# A pinned Rust toolchain for maturin and setuptools-rust projects. It is the
# only toolchain: RUSTUP_TOOLCHAIN overrides a repository's rust-toolchain.toml
# and RUSTUP_AUTO_INSTALL=0 stops rustup downloading another one at run time.
ENV RUSTUP_HOME=/opt/rustup PATH=/opt/cargo/bin:$PATH
RUN set -eux; \
    case "$TARGETARCH" in arm64) RA=aarch64 ;; amd64) RA=x86_64 ;; *) exit 1 ;; esac; \
    curl -fsSL -o /tmp/rustup-init \
      "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/${RA}-unknown-linux-gnu/rustup-init"; \
    chmod +x /tmp/rustup-init; \
    CARGO_HOME=/opt/cargo /tmp/rustup-init -y --no-modify-path --profile minimal --default-toolchain "${RUST_VERSION}"; \
    rm /tmp/rustup-init; \
    chmod -R a+rX /opt/rustup /opt/cargo; \
    CARGO_HOME=/opt/cargo rustc --version
# uv reads a repository's uv.lock, so its pinned versions install as locked.
RUN pip install --no-cache-dir "uv==${UV_VERSION}"

COPY docker/qot-scan-versions /usr/local/bin/qot-scan-versions
RUN chmod +x /usr/local/bin/qot-scan-versions

# Run as nobody. The harness also passes --user 65534:65534.
USER 65534:65534
ENV HOME=/tmp \
    CARGO_HOME=/tmp/cargo \
    RUSTUP_TOOLCHAIN=${RUST_VERSION} \
    RUSTUP_AUTO_INSTALL=0 \
    SEMGREP_SEND_METRICS=off \
    SEMGREP_ENABLE_VERSION_CHECK=0 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
