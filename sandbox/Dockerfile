# ============================================================
# Gryag Sandbox — Locked-Down Code Execution Environment
# ============================================================
# This container has ZERO network access and read-only mounts.
# It receives Python code via stdin and returns output via stdout.
# ============================================================

FROM python:3.12-slim

# Install common scientific/utility packages for code execution
RUN pip install --no-cache-dir \
    matplotlib \
    numpy \
    pandas \
    sympy \
    pillow \
    requests==0 2>/dev/null || true

# Drop to a non-root user for additional safety
RUN useradd --create-home --shell /bin/bash sandbox
USER sandbox
WORKDIR /home/sandbox

# The entrypoint reads Python code from stdin and executes it
COPY entrypoint.sh /entrypoint.sh

ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]
