# Deployment on Railway

This service is a Telegram control bot that also exposes a FastAPI health endpoint. Deploy it as a single Railway service from this repository.

## Required variables

Set `HOST_BOT_TOKEN` to the token of the control bot and `ADMIN_IDS` to a comma-separated list of Telegram user IDs with administrator access. For the default SQLite deployment, set `DATABASE_PATH=/app/data/hosting.db` and `BOTS_DIR=/app/data/uploaded_bots`.

## Persistent storage

Attach one Railway Volume mounted at `/app/data`. Do not run multiple replicas with the same control-bot token. The volume is required because the SQLite database and uploaded bot files are runtime data.

## Port and health check

Railway supplies `PORT`; the application listens on it and exposes `GET /health`. The repository includes `railway.json` and `infra/docker/Dockerfile`, so no custom start command is required.

## Security

Never commit `.env`, Telegram tokens, databases, uploaded bot archives, or logs. This project executes uploaded Python code on the same host; use it only with trusted users unless stronger container or VM isolation is added.
