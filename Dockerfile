# builder stage -----------------------------------------------------------------------------------
FROM python:3-slim AS builder

RUN apt-get update && \
    apt-get install -y apt-transport-https && \
    apt-get -y upgrade && \
    apt-get install --no-install-recommends -y build-essential && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN python3 -m ensurepip
RUN pip3 install --upgrade pip setuptools

WORKDIR /usr/src/app

COPY requirements.txt .
RUN python3 -m venv .venv
RUN .venv/bin/pip3 install --no-cache-dir --upgrade -r requirements.txt

# production stage --------------------------------------------------------------------------------
FROM python:3-slim AS production

RUN apt-get update && \
    apt-get install -y apt-transport-https && \
    apt-get install -y --no-install-recommends dnsmasq && \
    apt-get -y upgrade && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN echo '' >> /etc/dnsmasq.conf
# See https://github.com/nicolasff/docker-cassandra/issues/8
RUN echo 'user=root' >> /etc/dnsmasq.conf


WORKDIR /usr/src/app

COPY . .
COPY --from=builder /usr/src/app/.venv .venv

RUN mkdir /config
RUN touch /config/config.yaml

ARG USER_ID=1000
ARG GROUP_ID=1000

RUN addgroup --gid $GROUP_ID appuser && \
    adduser --uid $USER_ID --gid $GROUP_ID --disabled-password --gecos "" appuser

RUN chown -R appuser:appuser .
RUN chown appuser:appuser /config/*
RUN chmod 0664 /config/*    

RUN echo ''%${GROUP_ID}' ALL=NOPASSWD:/usr/sbin/service dnsmasq *' >> /etc/sudoers

USER appuser

ENV PATH="/usr/src/app/.venv/bin:$PATH"

CMD ["/bin/sh", "-c", "sudo service dnsmasq start && python3 ./app.py -c /config"]
