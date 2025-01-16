FROM debian:bookworm

ENV DEBIAN_FRONTEND=noninteractive
COPY requirements.txt /requirements.txt

RUN apt-get update -q=2 && \
    apt-get -qq install --no-install-recommends iproute2 auto-apt-proxy >/dev/null && \
    apt-get -qq install --no-install-recommends >/dev/null \
        fail2ban \
        gettext \
        gcc \
        git \
        libdbd-pg-perl \
        libldap2-dev \
        libpq-dev \
        libsasl2-dev \
        libyaml-dev \
        moreutils \
        openssh-client \
        postgresql-client \
        python3-dev \
        python3-pip \
        python3-psycopg2 \
        python3-venv \
        unzip \
        wget && \
    python3 -m venv /venv/ && . /venv/bin/activate && \
    pip install -r /requirements.txt && \
    pip install \
        build \
        django-auth-ldap \
        django-storages[s3] \
        sentry-sdk[django] && \
    pip install --no-dependencies squad-linaro-plugins

# Make sure python virtual environment is always on
ENV PATH="/venv/bin:$PATH"

# Prepare the environment
COPY . /squad-build/

ENV SQUAD_STATIC_DIR=/app/static

RUN cd /squad-build && ./scripts/git-build && \
    pip3 install --no-dependencies ./dist/squad*.whl && \
    mkdir -p /app/static && \
    useradd -d /app squad && \
    python3 -m squad.frontend && \
    squad-admin collectstatic --noinput --verbosity 0 && \
    chown -R squad:squad /app && \
    cd /app

# Clean environment
RUN rm -rf /squad-build && \
    apt-get remove -y \
        gcc \
        git \
        libpq-dev \
        libsasl2-dev \
        libyaml-dev \
        python3-dev \
        libsasl2-dev && \
    apt-get clean && \
    apt-get autoremove -y && \
    . /venv/bin/activate && pip uninstall -y build && pip cache purge

USER squad
