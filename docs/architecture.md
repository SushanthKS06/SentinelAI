# Architecture Overview

SentinelAI is designed as a distributed, microservices-based platform for autonomous site reliability engineering.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SentinelAI Platform                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │   Frontend  │  │  WebSocket  │  │    gRPC     │  │   REST API  │       │
│  │   (Next.js) │  │   Gateway   │  │   Gateway   │  │   Gateway   │       │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘       │
│         │                │                │                │               │
│  ┌──────┴────────────────┴────────────────┴────────────────┴──────┐       │
│  │                      API Gateway Service                        │       │
│  │              (Rate Limiting, Auth, Routing, Caching)            │       │
│  └─────────────────────────────┬───────────────────────────────────┘       │
│                                │                                            │
│  ┌─────────────────────────────┴───────────────────────────────────┐       │
│  │                    Service Mesh / Event Bus                     │       │
│  │                    (Kafka + Redis + gRPC)                       │       │
│  └─────────────────────────────┬───────────────────────────────────┘       │
│                                │                                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ Auth     │ │Incident  │ │  Log     │ │ Metrics  │ │  Trace   │        │
│  │ Service  │ │Intelligence│ │Processing│ │Processing│ │Correlation│        │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
│                                                                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │Deployment│ │   AI     │ │Multi-Agent│ │Notification│ │Evaluation│        │
│  │Analysis  │ │Orchestrat│ │Coordination│ │ Service  │ │ Service  │        │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
│                                                                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │Analytics │ │  Memory  │ │  Vector  │ │ Streaming│ │  ML      │        │
│  │ Service  │ │ Context  │ │Retrieval │ │ Pipeline │ │Pipeline  │        │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────┐      │
│  │                    Data Layer (PostgreSQL + Redis +              │      │
│  │                    ClickHouse + Kafka + Qdrant + vLLM)          │      │
│  └──────────────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Core Services

### API Gateway
- Request routing and load balancing
- Authentication and authorization
- Rate limiting and throttling
- Request/response transformation
- Caching layer

### Incident Intelligence
- Incident lifecycle management
- Timeline tracking
- AI-powered root cause analysis
- Remediation suggestions
- Alert deduplication

### Log Processing
- Log ingestion via multiple sources
- Parsing and normalization
- Full-text search with ClickHouse
- Log aggregation and grouping

### Metrics Processing
- Time-series data storage
- Query language support
- Anomaly detection
- Alert rule evaluation

### Trace Correlation
- Distributed tracing aggregation
- Service dependency mapping
- Latency analysis
- Trace search and filtering

### Deployment Analysis
- Deployment event tracking
- Change impact analysis
- Rollback detection
- Deployment correlation

### AI Orchestration
- Workflow orchestration
- Multi-agent coordination
- Context management
- Prompt engineering

### Multi-Agent Coordination
- Specialized agent teams
- Task distribution
- Result aggregation
- Agent communication

### Notification Service
- Multi-channel notifications
- Escalation policies
- On-call scheduling
- Alert routing

### Analytics Service
- Incident metrics
- MTTR/MTTD tracking
- Trend analysis
- Custom dashboards

### Memory Context
- Hierarchical memory
- Semantic retrieval
- Temporal context
- Session management

### Vector Retrieval
- Semantic search
- Hybrid retrieval (BM25 + vector)
- Reranking
- Knowledge base queries

### Streaming Pipeline
- Real-time event processing
- Event transformation
- Event routing
- Backpressure handling

## Data Layer

### PostgreSQL
- Primary data store
- User management
- Incident records
- Configuration data
- Transactional operations

### Redis
- Session storage
- Caching layer
- Real-time metrics
- Pub/sub messaging

### ClickHouse
- Log storage and search
- Analytics queries
- Time-series aggregations

### Kafka
- Event streaming
- Service communication
- Event sourcing
- Message persistence

### Qdrant
- Vector embeddings storage
- Semantic search
- Similarity matching

### vLLM
- LLM inference
- AI-powered analysis
- Text generation

## Technology Stack

### Backend
- Python 3.11+
- FastAPI
- SQLAlchemy
- Pydantic

### Frontend
- Next.js 14+
- React
- TypeScript
- TailwindCSS

### Infrastructure
- Docker
- Kubernetes
- Terraform
- Helm

### Observability
- OpenTelemetry
- Prometheus
- Grafana
- Jaeger

## Design Principles

1. **Microservices Architecture** - Loose coupling, independent scaling
2. **Event-Driven** - Async communication via Kafka
3. **Observability First** - Built-in tracing and metrics
4. **AI-Native** - Core SRE functions powered by AI
5. **Cloud-Native** - Designed for Kubernetes

## Security

- JWT-based authentication
- Role-based access control (RBAC)
- API key management
- Audit logging
- TLS encryption
