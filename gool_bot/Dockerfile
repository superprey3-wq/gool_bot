FROM python:3.12-slim

WORKDIR /app

# Keep production Python aligned with the GitHub audit runtime.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV HF_HOME=/tmp/huggingface

CMD ["python", "main.py"]
