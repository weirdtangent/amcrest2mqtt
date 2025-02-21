FROM python:3.9-alpine AS base
FROM base AS builder

RUN python3 -m ensurepip

# Upgrade pip and setuptools
RUN pip3 install --upgrade pip setuptools

RUN mkdir /install
WORKDIR /install

COPY requirements.txt /
RUN pip3 install --no-warn-script-location --prefix=/install -r /requirements.txt

FROM base
STOPSIGNAL SIGINT
COPY --from=builder /install /usr/local
COPY src /app
COPY VERSION /app
WORKDIR /app

ARG USER_ID=1000
ARG GROUP_ID=1000

RUN addgroup -g $GROUP_ID appuser && \
    adduser -u $USER_ID -G appuser --disabled-password --gecos "" appuser

USER appuser

CMD [ "python", "-u", "/app/amcrest2mqtt.py" ]
