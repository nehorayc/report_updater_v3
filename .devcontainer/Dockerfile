FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        fonts-noto-core \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
