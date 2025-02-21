FROM python:3.9-alpine AS base
FROM base AS builder

RUN mkdir /install
WORKDIR /install

COPY requirements.txt /
RUN pip install --no-warn-script-location --prefix=/install -r /requirements.txt

FROM base
STOPSIGNAL SIGINT
COPY --from=builder /install /usr/local
COPY src /app
COPY VERSION /app
WORKDIR /app

ARG USER_ID=1000
ARG GROUP_ID=1000

RUN addgroup --gid $GROUP_ID appuser && \
    adduser --uid $USER_ID --gid $GROUP_ID --disabled-password --gecos "" appuser

USER appuser

CMD [ "python", "-u", "/app/amcrest2mqtt.py" ]
