FROM python:3.12-slim

# 容器仅负责运行 Claude Agent SDK；动态 Skill 定义和资源均在运行时以只读挂载目录提供。
RUN pip install --no-cache-dir "claude-agent-sdk==0.2.96" \
    && useradd --create-home --uid 10001 sandbox

USER sandbox
WORKDIR /skill
ENTRYPOINT []
