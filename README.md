# SentinelAI - Autonomous AI Reliability Engineer

## Overview

SentinelAI is an autonomous AI reliability engineer for distributed cloud-native systems. It acts as an intelligent on-call SRE capable of real-time monitoring, incident detection, anomaly detection, root cause analysis, and automated remediation.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SentinelAI Platform                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Frontend  │  │  WebSocket  │  │    gRPC     │  │   REST API  │         │
│  │   (Next.js) │  │   Gateway   │  │   Gateway   │  │   Gateway   │         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                │                │
│  ┌──────┴────────────────┴────────────────┴────────────────┴──────┐         │
│  │                      API Gateway Service                       │         │
│  │              (Rate Limiting, Auth, Routing, Caching)           │         │
│  └─────────────────────────────┬──────────────────────────────────┘         │
│                                │                                            │
│  ┌─────────────────────────────┴───────────────────────────────────┐        │
│  │                    Service Mesh / Event Bus                     │        │
│  │                    (Kafka + Redis + gRPC)                       │        │
│  └─────────────────────────────┬───────────────────────────────────┘        │
│                                │                                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ Auth     │ │Incident  │ │  Log     │ │ Metrics  │ │  Trace   │           │
│  │ Service  │ │Intelligence│Processing│ │Processing│ │Correlation│          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│                                                                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │Deployment│ │   AI     │ │Multi-Agent│ │Notification│ │Evaluation│        │
│  │Analysis  │ │Orchestrat│ │Coordination│ │ Service  │ │ Service  │         │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│                                                                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │Analytics │ │  Memory  │ │  Vector  │ │ Streaming│ │  ML      │           │
│  │ Service  │ │ Context  │ │Retrieval │ │ Pipeline │ │Pipeline  │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │                    Data Layer (PostgreSQL + Redis +              │       │
│  │                    ClickHouse + Kafka + Qdrant + vLLM)           │       │
│  └──────────────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Features

### Core Capabilities
- **Real-time Monitoring**: Ingest and process logs, metrics, traces, and deployment events
- **Incident Detection**: Automatic anomaly detection with ML-powered analysis
- **Root Cause Analysis**: AI-driven RCA with multi-agent coordination
- **Remediation Suggestions**: Context-aware AI-generated fix recommendations
- **Alert Deduplication**: Intelligent alert grouping to reduce alert fatigue

### AI/ML Features
- **Multi-Agent Architecture**: Specialized agents for logs, metrics, traces, deployments
- **RAG Pipeline**: Hybrid retrieval with BM25 + vector search + reranking
- **Context Engineering**: Hierarchical memory with semantic and temporal retrieval
- **Anomaly Detection**: Unsupervised ML models for CPU, memory, latency, traffic

### Observability
- **OpenTelemetry**: Distributed tracing, metrics collection
- **Prometheus + Grafana**: Real-time dashboards, p95/p99 latency tracking
- **Structured Logging**: JSON logging with correlation IDs

## Quick Start

### Prerequisites
- Docker 24.0+
- Kubernetes 1.28+
- PostgreSQL 15+
- Redis 7+
- Kafka 3.6+
- ClickHouse 23.8+

### Local Development

```bash
# Clone the repository
git clone https://github.com/sentinelai/sentinelai.git
cd sentinelai

# Start infrastructure
docker-compose -f infrastructure/docker-compose.yml up -d

# Start backend services
make dev

# Start frontend
cd frontend && npm run dev
```

### Production Deployment

```bash
# Deploy to Kubernetes
kubectl apply -f kubernetes/manifests/

# Or use Helm
helm install sentinelai charts/sentinelai
```

## Project Structure

```
sentinelai/
├── backend/                    # Backend microservices
│   ├── api-gateway/           # API Gateway service
│   ├── auth-service/          # Authentication service
│   ├── incident-intelligence/ # Incident management
│   ├── log-processing/        # Log ingestion & processing
│   ├── metrics-processing/    # Metrics pipeline
│   ├── trace-correlation/     # Distributed tracing
│   ├── deployment-analysis/   # Deployment correlation
│   ├── ai-orchestration/      # AI workflow orchestration
│   ├── multi-agent/           # Multi-agent coordination
│   ├── notification-service/  # Alert notifications
│   ├── evaluation-service/    # AI evaluation
│   ├── analytics-service/     # Analytics & reporting
│   ├── memory-context/        # Memory & context service
│   ├── vector-retrieval/      # Vector search service
│   └── streaming-pipeline/    # Event streaming
├── frontend/                   # Next.js frontend
├── ml/                         # ML models & anomaly detection
├── infrastructure/             # Infrastructure as Code
│   ├── docker/                # Docker configurations
│   ├── kubernetes/            # K8s manifests
│   ├── helm/                  # Helm charts
│   └── terraform/             # Terraform modules
├── .github/                    # CI/CD workflows
├── docs/                       # Documentation
└── tests/                      # Test suites
```

## API Documentation

### REST API
- OpenAPI docs available at `/api/docs`
- Swagger UI at `/api/redoc`

### gRPC Services
- Proto definitions in `proto/`
- gRPC reflection enabled

### WebSocket
- Real-time updates at `/ws`
- Event streaming for incidents, alerts, metrics

## Configuration

Environment variables are configured via `.env` files. See `.env.example` for available options.

## Monitoring

Access Grafana dashboards:
- Service health: `http://localhost:3000/d/service-health`
- AI metrics: `http://localhost:3000/d/ai-metrics`
- Anomaly detection: `http://localhost:3000/d/anomalies`

## Documentation

- [Getting Started](docs/getting-started.md) - Quick start guide
- [Architecture](docs/architecture.md) - System design overview
- [API Reference](docs/api-reference.md) - API endpoints and usage
- [Configuration](docs/configuration.md) - Configuration options

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.

## Architecture Decision Records

See [docs/adr/](docs/adr/) for architectural decisions and tradeoffs.
