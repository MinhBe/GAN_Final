FROM python:3.12-alpine
WORKDIR /app
COPY backend.py /app/backend.py
USER 65534:65534
EXPOSE 8080
CMD ["python", "/app/backend.py"]
