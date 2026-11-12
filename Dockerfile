FROM python:3.13.5-slim-bookworm@sha256:a7cb177dc60dfa77b223192cd0d9e6ce1aac7cf9a569023d68e7c91b6371a718 AS builder
RUN apt-get update && apt-get install -y --no-install-recommends clang libc6-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /source
COPY q20 q20
COPY scripts scripts
COPY assets assets
COPY icon.svg icon.svg
COPY third_party third_party
COPY tests tests
RUN python scripts/build_crypto.py && python -m unittest discover -s tests -v

FROM python:3.13.5-slim-bookworm@sha256:a7cb177dc60dfa77b223192cd0d9e6ce1aac7cf9a569023d68e7c91b6371a718
WORKDIR /opt/q20
COPY q20 q20
COPY --from=builder /source/q20/_native q20/_native
COPY LICENSE NOTICE dependencies.lock.json /usr/share/doc/q20/
COPY third_party /usr/share/doc/q20/third_party
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
RUN mkdir /data && chown 1000:1000 /data
USER 1000:1000
STOPSIGNAL SIGTERM
ENTRYPOINT ["python", "-m", "q20"]
CMD ["start", "--data", "/data", "--listen", "0.0.0.0", "--port", "8080"]
