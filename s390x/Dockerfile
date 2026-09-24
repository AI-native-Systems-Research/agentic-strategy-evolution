# syntax=docker/dockerfile:1
ARG UBI_IMAGE=registry.access.redhat.com/ubi10/ubi:latest
FROM --platform=linux/s390x ${UBI_IMAGE}

LABEL name="nous" \
      version="0.5.0" \
      summary="Nous framework (s390x UBI 10 + Conda + Claude Code)" \
      architecture="s390x"

ARG CONDA_INSTALLER_URL=https://repo.anaconda.com/miniconda/Miniconda3-py312_25.1.1-2-Linux-s390x.sh
ARG CONDA_INSTALLER_SHA256=55c681937c27e13a8ed818d1fec182e623e0308fffc1b10605896dac15f90077

ENV CONDA_ROOT=/opt/conda
ENV CONDA_ENV=/opt/conda/envs/nous
ENV PATH=/opt/conda/envs/nous/bin:/opt/conda/bin:${PATH}
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER 0

# Native s390x system prerequisites + build toolchain for compiling Python wheels
RUN set -eux; \
    dnf -y update; \
    dnf -y install --nodocs --allowerasing \
        bash \
        bzip2 \
        ca-certificates \
        coreutils \
        curl \
        findutils \
        gzip \
        shadow-utils \
        tar \
        git \
        grep \
        sed \
        gawk \
        util-linux \
        gcc \
        gcc-c++ \
        gcc-gfortran \
        openssl-devel \
        zlib-devel \
        libffi-devel \
        libxml2-devel \
        cmake \
        rust \
        cargo \
        llvm \
        llvm-devel \
        clang \
        pkgconf-pkg-config \
        nodejs \
        nodejs-npm; \
    npm install -g @anthropic-ai/claude-code@2.1.112; \
    npm cache clean --force; \
    dnf clean all; \
    rm -rf /var/cache/dnf

# Download and verify Conda installer for s390x
RUN set -eux; \
    curl -fsSL "${CONDA_INSTALLER_URL}" -o /tmp/miniconda-s390x.sh; \
    echo "${CONDA_INSTALLER_SHA256}  /tmp/miniconda-s390x.sh" | sha256sum --check --strict -; \
    chmod 0755 /tmp/miniconda-s390x.sh; \
    /bin/bash /tmp/miniconda-s390x.sh -b -p "${CONDA_ROOT}"; \
    rm -f /tmp/miniconda-s390x.sh; \
    "${CONDA_ROOT}/bin/conda" --version; \
    "${CONDA_ROOT}/bin/python" -c \
        "import platform; assert platform.machine() == 's390x', platform.machine()"

# Create dedicated Conda environment from environment.yml
COPY environment.yml /tmp/environment.yml
RUN set -eux; \
    export PKG_CONFIG_PATH="${CONDA_ROOT}/lib/pkgconfig:/usr/lib64/pkgconfig"; \
    export OPENSSL_DIR="${CONDA_ROOT}"; \
    export OPENSSL_LIB_DIR="${CONDA_ROOT}/lib"; \
    export OPENSSL_INCLUDE_DIR="${CONDA_ROOT}/include"; \
    export OPENSSL_STATIC=0; \
    export LLVMLITE_SKIP_LLVM_VERSION_CHECK=1; \
    export LLVMLITE_SHARED=1; \
    export CMAKE_PREFIX_PATH="/usr;/usr/lib64"; \
    sed -i '/find_package(ZLIB/d' /usr/lib64/cmake/llvm/LLVMConfig.cmake 2>/dev/null || true; \
    sed -i 's/ZLIB::ZLIB//g' /usr/lib64/cmake/llvm/LLVMExports.cmake 2>/dev/null || true; \
    sed -i 's/zstd::libzstd_shared//g' /usr/lib64/cmake/llvm/LLVMExports.cmake 2>/dev/null || true; \
    sed -i 's/zstd::libzstd_static//g' /usr/lib64/cmake/llvm/LLVMExports.cmake 2>/dev/null || true; \
    "${CONDA_ROOT}/bin/conda" env create \
        --file /tmp/environment.yml \
        --prefix "${CONDA_ENV}"; \
    "${CONDA_ROOT}/bin/conda" clean --all --yes; \
    rm -f /tmp/environment.yml; \
    find "${CONDA_ROOT}" -type f -name '*.pyc' -delete

# Copy and install local orchestrator/nous package into the Conda environment
COPY pyproject.toml /tmp/nous-src/
COPY orchestrator /tmp/nous-src/orchestrator
COPY prompts /tmp/nous-src/prompts
RUN set -eux; \
    "${CONDA_ENV}/bin/pip" install --no-deps -e /tmp/nous-src; \
    find "${CONDA_ROOT}" -type f -name '*.pyc' -delete

# Create non-root user
RUN set -eux; \
    groupadd --gid 1001 app; \
    useradd \
        --uid 1001 \
        --gid 1001 \
        --home-dir /home/app \
        --create-home \
        --shell /bin/bash \
        app; \
    mkdir -p /workspace /opt/app-root/src/campaigns /tmp/nous-src; \
    chown -R app:app /workspace /home/app /opt/app-root /tmp/nous-src; \
    chmod -R g=u "${CONDA_ROOT}" /opt/app-root/src/campaigns /tmp/nous-src

USER 1001:1001
WORKDIR /workspace

RUN git config --global --add safe.directory '*'

# Runtime configuration
ENV NOUS_CAMPAIGN_PARENT=/opt/app-root/src/campaigns

CMD ["nous", "--help"]
