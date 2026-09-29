# SPDX-License-Identifier: MIT
# Lightweight image for the ntpstats UI / monitor / CLI.
#   docker build -t ntpstats .
#   docker run --rm -p 8123:8123 -v "$PWD:/data" ntpstats ui /data/peerstats --host 0.0.0.0 --no-browser
#   docker run --rm --cap-drop ALL ntpstats query --nts time.cloudflare.com
FROM python:3.12-slim
LABEL org.opencontainers.image.title="ntpstats" \
      org.opencontainers.image.source="https://github.com/thiagodefreitas/NetworkTime" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.authors="Thiago de Freitas <thiagodefreitas@gmail.com>"
WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN pip install --no-cache-dir ".[nts]" && useradd -m ntpstats
USER ntpstats
WORKDIR /data
EXPOSE 8123
ENTRYPOINT ["ntpstats"]
CMD ["--help"]
