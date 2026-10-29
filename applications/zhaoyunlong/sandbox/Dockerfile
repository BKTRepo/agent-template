FROM python:3.12-slim

# 容器负责运行 Claude Agent SDK，并提供常见交付文件的生成库；动态 Skill 定义和资源均在运行时以只读挂载目录提供。
RUN pip install --no-cache-dir \
        "claude-agent-sdk==0.2.96" \
        "openpyxl==3.1.5" \
        "python-docx>=1.1.0,<2.0.0" \
        "reportlab>=4.0.0,<5.0.0" \
    && useradd --create-home --uid 10001 sandbox

USER sandbox
WORKDIR /skill
ENTRYPOINT []
