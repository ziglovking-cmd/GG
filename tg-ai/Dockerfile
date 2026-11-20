FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/tmp/data
ENV PORT=8080

RUN mkdir -p /tmp/data
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .

EXPOSE 8080
CMD ["python", "bot.py"]
