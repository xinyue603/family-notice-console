# 家庭通知中控台 —— 运行镜像
# 镜像同时包含「主服务 main.py」与「钉钉机器人 ding_stream_bot.py」，
# 二者共享 /app/data 下的 SQLite 库与上传目录。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NOTIFY_DATA_DIR=/app/data

WORKDIR /app

# 先装依赖，利用层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷源码
COPY . .

# 数据持久化目录（docker-compose 挂载卷到此）
RUN mkdir -p /app/data

EXPOSE 8002

# 默认启动主服务；钉钉机器人请用 docker-compose 的 bot 服务或覆盖 command。
CMD ["sh", "-c", "python main.py"]
