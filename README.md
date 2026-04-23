# TaskScheduler
 
Cloud-Based Distributed Task Scheduling and Reminder Service
 
## Team
 
| Name | GitHub Username |
|------|-----------------|
| Tiya | tiyasaini3 |
 
## Prerequisites
 
- Docker Desktop (or Docker Engine + Compose v2)
- Git
## Deploy with Docker Compose
 
This is the recommended way to run the full service stack (Postgres, Redis, API, Worker) locally.
 
```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/task-scheduler.git
cd task-scheduler
 
# 2. Build and start all services
docker-compose up --build
```
 
Once running:
 
- Dashboard: http://localhost:8000
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health
To stop all services:
 
```bash
docker-compose down
```
 
To run in the background:
 
```bash
docker-compose up --build -d
docker-compose logs -f api worker
```
 
## Deploy Locally (without Docker)
 
You still need Postgres and Redis available. The easiest way is to spin up just those two services via Docker:
 
```bash
docker-compose up -d postgres redis
```
 
Then in your terminal:
 
```bash
# Install dependencies
pip install -r requirements.txt
 
# Set environment variables
export DATABASE_URL="postgresql://taskuser:taskpass@localhost:5433/taskdb"
export REDIS_HOST=localhost
export REDIS_PORT=6379
 
# Start the API
uvicorn app.main:app --reload --port 8000
 
# In a second terminal, start the worker
python -m worker.worker
```
 
## Environment Variables
 
All variables have defaults set in `docker-compose.yml`. Override them as needed.
 
| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://taskuser:taskpass@postgres:5432/taskdb` | PostgreSQL connection string |
| `REDIS_HOST` | `redis` | Redis hostname |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_QUEUE_NAME` | `reminders` | Redis list name for the job queue |
| `QUEUE_BACKEND` | `redis` | Set to `sqs` to use AWS SQS |
| `STORAGE_BACKEND` | `local` | Set to `s3` to write logs to AWS S3 |
| `LOCAL_LOG_DIR` | `/tmp/task_logs` | Directory for local audit logs |
| `WORKER_MAX_RETRIES` | `3` | Retry attempts before dead-letter queue |
| `WORKER_POLL_INTERVAL` | `2` | Seconds between queue polls |
 
## Running Tests
 
No running Postgres or Redis is needed. The test suite uses SQLite in-memory and mocks all external dependencies.
 
```bash
pip install -r requirements.txt
pytest tests/ -v
```
