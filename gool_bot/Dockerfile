FROM python:3.9-slim

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install the Chromium browser and Linux dependencies required by Playwright.
# Keeping this in the image makes the runtime self-contained on Northflank.
RUN python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Application code
COPY . .

ENV HF_HOME=/tmp/huggingface \
    PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
