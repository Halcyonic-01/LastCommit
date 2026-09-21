# The officer boundary only. The farmer PWA is static files on a CDN and needs no
# container; the speech services are deliberately not here (see README - they are
# GPU-class workloads and this image is meant to run on a small instance).
FROM python:3.12-slim

WORKDIR /app
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# Only what the server actually reads at runtime: itself, the shared composer, the
# Supabase wrapper, the rules the advisories cite, and the forecast it composes from.
COPY services/ services/
COPY src/ src/
COPY rules/ rules/
COPY schema/ schema/
COPY forecast/ forecast/

# A container must listen on every interface; the default 127.0.0.1 is for a laptop.
ENV BROADCAST_HOST=0.0.0.0 PORT=8787
EXPOSE 8787

# No shell form: this must receive SIGTERM directly so the host can stop it cleanly.
CMD ["python", "services/broadcast_server.py"]
