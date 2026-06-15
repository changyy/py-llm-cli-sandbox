# Sandbox image for llm-cli-sandbox.
# Claude Code runs here as a NON-ROOT user — the agent is isolated from the host
# and only sees the mounted /workspace.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    bash \
    bash-completion \
    ca-certificates \
    curl \
    git \
    jq \
    nano \
    net-tools \
    procps \
    unzip \
    vim \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Non-root user. UID/GID are build args so they can be matched to the host user
# on Linux (avoids root-owned files in the mounted workspace).
ARG USER_NAME=lab
ARG USER_UID=1000
ARG USER_GID=1000
# ubuntu:24.04 ships a default `ubuntu` user at 1000:1000 — remove it so our
# sandbox user can claim that UID/GID (which matches the host user on Linux).
RUN (userdel -r ubuntu 2>/dev/null || true) \
    && (groupdel ubuntu 2>/dev/null || true) \
    && groupadd -g ${USER_GID} ${USER_NAME} \
    && useradd -m -u ${USER_UID} -g ${USER_GID} -s /bin/bash ${USER_NAME}

USER ${USER_NAME}
ENV HOME=/home/${USER_NAME}
ENV PATH="${HOME}/.local/bin:${PATH}"

# Claude Code CLI, installed for the non-root user. Pre-seed onboarding so the
# first run does not block on the setup wizard.
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && echo '{"hasCompletedOnboarding": true}' > ${HOME}/.claude.json

WORKDIR /workspace

ENTRYPOINT ["/entrypoint.sh"]
CMD ["/bin/bash"]
