# Getting Started with SentinelAI

This guide will help you set up SentinelAI for local development or production deployment.

## Prerequisites

- Docker 24.0+
- Kubernetes 1.28+ (for production)
- PostgreSQL 15+
- Redis 7+
- Kafka 3.6+
- ClickHouse 23.8+
- Python 3.11+
- Node.js 18+

## Local Development Setup

### 1. Clone the Repository

```bash
git clone https://github.com/sentinelai/sentinelai.git
cd sentinelai
```

### 2. Start Infrastructure

```bash
docker-compose -f infrastructure/docker-compose.yml up -d
```

This starts:
- PostgreSQL (port 5432)
- Redis (port 6379)
- Kafka (port 9092)
- ClickHouse (port 8123)
- Qdrant (port 6333)

### 3. Configure Environment

Copy the example environment file and adjust as needed:

```bash
cp .env.example .env
```

### 4. Start Backend Services

```bash
make dev
```

Or manually:

```bash
cd backend
pip install -e .
uvicorn sentinelai.api_gateway.main:app --reload
```

### 5. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

### 6. Verify Installation

- API: http://localhost:8000/api/docs
- Frontend: http://localhost:3000
- Grafana: http://localhost:3000 (admin/admin)

## Production Deployment

### Kubernetes Deployment

```bash
kubectl apply -f kubernetes/manifests/
```

### Helm Chart

```bash
helm install sentinelai charts/sentinelai
```

## Next Steps

- [Configuration Guide](configuration.md) - Customize your setup
- [Architecture Overview](architecture.md) - Understand the system design
- [API Reference](api-reference.md) - Explore available endpoints
