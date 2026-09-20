FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY clients ./clients
RUN python -m pip install --no-cache-dir '.[interop]' \
    && groupadd --gid 10001 oac \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin oac

COPY docs/spec.en.md /app/spec.en.md
COPY scripts /app/scripts

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD ["python", "-c", "from urllib.request import urlopen; assert urlopen('http://127.0.0.1:8080/.well-known/oac.json', timeout=3).status == 200"]

ENTRYPOINT ["oac-node"]
