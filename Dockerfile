FROM python:3.12-slim

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

EXPOSE 8000

ENV APP_VERSION=1.0.0
ENV APP_ENV=production

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]