FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVAL_WARNING_PCT=3.0 \
    EVAL_CRITICAL_PCT=8.0 \
    EVAL_DRIFT_WINDOW=7 \
    EVAL_DRIFT_MIN_PASS=0.90 \
    EVAL_DRIFT_PCT=5.0

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY prompts ./prompts
COPY golden_dataset ./golden_dataset

RUN mkdir -p /app/runs /app/reports \
    && useradd --create-home runner \
    && chown -R runner:runner /app

USER runner

VOLUME ["/app/runs", "/app/reports"]

ENTRYPOINT ["python", "-m", "src.cli"]
CMD ["--runs-dir", "runs", "--report-dir", "reports"]