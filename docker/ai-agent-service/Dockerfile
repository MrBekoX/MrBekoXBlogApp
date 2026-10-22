# AI agent servisi (Python worker) imajı.
#
# Build bağlamı DEPO KÖKÜDÜR (canonical yazar profili src/content altında):
#   docker build -f docker/ai-agent-service/Dockerfile -t blogapp-ai-agent:local .
#
# Canonical profil (src/content/author-profile) imaja birebir kopyalanır ve
# AGENT_PROFILE_DIR ile bağlanır; çalışma zamanı cwd'ye veya geliştirici
# dosya yoluna bağlı değildir. Backend imajı aynı commit'ten derlenmelidir
# (profil revision/hash uyumu; bkz. src/content/author-profile/README.md).
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AGENT_PROFILE_DIR=/srv/content/author-profile

WORKDIR /srv/ai-agent-service

COPY src/services/ai-agent-service/pyproject.toml ./
COPY src/services/ai-agent-service/app ./app
COPY src/services/ai-agent-service/migrations ./migrations
RUN pip install .

COPY src/content/author-profile /srv/content/author-profile

RUN groupadd -g 1001 agent && useradd -u 1001 -g agent -s /usr/sbin/nologin agent \
    && chown -R agent:agent /srv
USER agent

CMD ["python", "-m", "app.service_main"]
