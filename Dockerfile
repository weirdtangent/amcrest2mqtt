FROM python:3-alpine

RUN python -m venv /usr/src/app
# Enable venv
ENV PATH="/usr/src/app/venv/bin:$PATH"

RUN python3 -m ensurepip

# Upgrade pip and setuptools
RUN pip3 install --upgrade pip setuptools

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip3 install --no-cache-dir --upgrade -r requirements.txt

COPY . .

RUN mkdir /config
RUN touch /config/config.yaml

ARG USER_ID=1000
ARG GROUP_ID=1000

RUN addgroup -g $GROUP_ID appuser && \
    adduser -u $USER_ID -G appuser --disabled-password --gecos "" appuser
RUN chown appuser:appuser /config/*
RUN chmod 0664 /config/*    

USER appuser

ENTRYPOINT [ "python", "-u", "./app.py" ]
CMD [ "-c", "/config" ]
