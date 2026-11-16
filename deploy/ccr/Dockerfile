FROM docker.m.daocloud.io/library/python:3.12-slim-bookworm AS dependencies
ARG NODE_VERSION=24.15.0
RUN python -c "import sys, tarfile, urllib.request; version = sys.argv[1]; url = f'https://nodejs.org/dist/v{version}/node-v{version}-linux-x64.tar.xz'; urllib.request.urlretrieve(url, '/tmp/node.tar.xz'); tarfile.open('/tmp/node.tar.xz').extractall('/opt', filter='data')" "${NODE_VERSION}" \
    && mv "/opt/node-v${NODE_VERSION}-linux-x64" /opt/node \
    && rm /tmp/node.tar.xz
ENV PATH="/opt/node/bin:${PATH}"
WORKDIR /opt/ccr
RUN npm install --omit=dev --no-audit --no-fund --save-exact @musistudio/claude-code-router@3.1.3 \
    && node -e "const DB = require('better-sqlite3'); new DB(':memory:').close()"

FROM docker.m.daocloud.io/library/python:3.12-slim-bookworm
ENV HOME=/data NODE_ENV=production
WORKDIR /opt/ccr
COPY --from=dependencies /opt/node/bin/node /usr/local/bin/node
COPY --from=dependencies /opt/ccr/node_modules ./node_modules
COPY entrypoint.cjs ./entrypoint.cjs
EXPOSE 3456 3458
ENTRYPOINT ["node", "/opt/ccr/entrypoint.cjs"]
