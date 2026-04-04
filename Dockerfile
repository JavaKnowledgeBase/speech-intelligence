# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

# Install deps into an isolated prefix so the final stage stays lean
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.13-slim

LABEL org.opencontainers.image.title="TalkBuddy AI"
LABEL org.opencontainers.image.description="Agentic speech therapy platform — tablet/TV optimised"
LABEL org.opencontainers.image.version="0.8.0"

# Non-root user for medical / compliance contexts
RUN addgroup --system talkbuddy && adduser --system --ingroup talkbuddy talkbuddy

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/

# Ensure static files are readable
RUN chown -R talkbuddy:talkbuddy /app

USER talkbuddy

EXPOSE 8000

# Uvicorn: 1 worker per container — scale horizontally via docker-compose/k8s.
# Use --proxy-headers so X-Forwarded-For is respected behind nginx / ALB.
CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*", \
     "--log-level", "info"]
