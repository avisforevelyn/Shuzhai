FROM python:3.12-slim
WORKDIR /app
COPY server.py vault_api.py ./
COPY static ./static
ENV SHUZHAI_HOST=0.0.0.0 SHUZHAI_PORT=8790 SHUZHAI_DATA=/app/data
VOLUME ["/app/data"]
EXPOSE 8790
CMD ["python3", "server.py"]
