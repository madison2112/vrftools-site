FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY templates/ ./templates/
COPY dsbx_dat_mapping.json .
COPY web/ ./web/

# Optional: NetworkSetting XML templates for AE-C400A / EW-C50
# Extract from your empty config .dat files and place them here:
#   templates/NetworkSetting-AE-C400A.xml
#   templates/NetworkSetting-EW-C50.xml

WORKDIR /app/web

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 5050

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,json,sys; r=urllib.request.urlopen('http://localhost:5050/status',timeout=4); sys.exit(0 if json.loads(r.read()).get('ok') else 1)"

CMD ["gunicorn", "--bind", "0.0.0.0:5050", "--workers", "2", "--timeout", "60", "wsgi:application"]
