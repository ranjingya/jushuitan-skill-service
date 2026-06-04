FROM python:3.14-slim

ENV TZ=Asia/Shanghai

RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ uv

WORKDIR /app

COPY pyproject.toml ./
COPY uv.lock ./

RUN uv sync --frozen -i https://mirrors.aliyun.com/pypi/simple/

COPY main.py ./
COPY gunicorn.py ./
COPY core ./core
COPY flows ./flows

EXPOSE 5011

CMD ["./.venv/bin/gunicorn", "-c", "gunicorn.py", "main:app"]
