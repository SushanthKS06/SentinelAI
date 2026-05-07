# Configuration Guide

This guide covers all configuration options available in SentinelAI.

## Environment Variables

### Application

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_NAME` | Application name | SentinelAI |
| `APP_ENV` | Environment (development/staging/production) | development |
| `APP_VERSION` | Application version | 0.1.0 |
| `APP_DEBUG` | Enable debug mode | true |
| `APP_HOST` | Host to bind to | 0.0.0.0 |
| `APP_PORT` | Port to bind to | 8000 |

### Database (PostgreSQL)

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_HOST` | Database host | localhost |
| `POSTGRES_PORT` | Database port | 5432 |
| `POSTGRES_DB` | Database name | sentinelai |
| `POSTGRES_USER` | Database user | sentinelai |
| `POSTGRES_PASSWORD` | Database password | - |
| `POSTGRES_POOL_SIZE` | Connection pool size | 20 |
| `POSTGRES_MAX_OVERFLOW` | Max overflow connections | 10 |
| `POSTGRES_POOL_TIMEOUT` | Pool timeout (seconds) | 30 |

### Redis

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_HOST` | Redis host | localhost |
| `REDIS_PORT` | Redis port | 6379 |
| `REDIS_DB` | Redis database number | 0 |
| `REDIS_PASSWORD` | Redis password | - |
| `REDIS_MAX_CONNECTIONS` | Max connections | 50 |
| `REDIS_SSL` | Enable SSL | false |

### Kafka

| Variable | Description | Default |
|----------|-------------|---------|
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka brokers | localhost:9092 |
| `KAFKA_CLIENT_ID` | Client identifier | sentinelai |
| `KAFKA_CONSUMER_GROUP` | Consumer group | sentinelai-consumers |
| `KAFKA_SECURITY_PROTOCOL` | Security protocol | PLAINTEXT |
| `KAFKA_SASL_MECHANISM` | SASL mechanism | - |
| `KAFKA_SASL_USERNAME` | SASL username | - |
| `KAFKA_SASL_PASSWORD` | SASL password | - |

### ClickHouse

| Variable | Description | Default |
|----------|-------------|---------|
| `CLICKHOUSE_HOST` | ClickHouse host | localhost |
| `CLICKHOUSE_PORT` | ClickHouse port | 9000 |
| `CLICKHOUSE_DATABASE` | Database name | sentinelai |
| `CLICKHOUSE_USER` | User | default |
| `CLICKHOUSE_PASSWORD` | Password | - |
| `CLICKHOUSE_COMPRESSION` | Compression | lz4 |

### Qdrant (Vector Database)

| Variable | Description | Default |
|----------|-------------|---------|
| `QDRANT_HOST` | Qdrant host | localhost |
| `QDRANT_PORT` | Qdrant REST port | 6333 |
| `QDRANT_GRPC_PORT` | Qdrant gRPC port | 6334 |
| `QDRANT_API_KEY` | API key | - |
| `QDRANT_COLLECTION_NAME` | Collection name | sentinelai_vectors |
| `QDRANT_DISTANCE` | Distance metric | cosine |

### vLLM (LLM Inference)

| Variable | Description | Default |
|----------|-------------|---------|
| `VLLM_HOST` | vLLM host | localhost |
| `VLLM_PORT` | vLLM port | 8000 |
| `VLLM_API_KEY` | API key | EMPTY |
| `VLLM_MODEL` | Model name | llama-3-8b-instruct |
| `VLLM_MAX_TOKENS` | Max tokens | 4096 |
| `VLLM_TEMPERATURE` | Temperature | 0.7 |
| `VLLM_TOP_P` | Top P | 0.9 |
| `VLLM_TOP_K` | Top K | 50 |

### Security

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Application secret key | - |
| `JWT_SECRET_KEY` | JWT signing key | - |
| `JWT_ALGORITHM` | JWT algorithm | HS256 |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access token expiry | 30 |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token expiry | 7 |
| `JWT_RESET_PASSWORD_EXPIRE_MINUTES` | Reset token expiry | 15 |
| `JWT_VERIFICATION_EXPIRE_HOURS` | Verification token expiry | 24 |

### CORS

| Variable | Description | Default |
|----------|-------------|---------|
| `CORS_ORIGINS` | Allowed origins | http://localhost:3000 |
| `CORS_ALLOW_CREDENTIALS` | Allow credentials | true |
| `CORS_ALLOW_METHODS` | Allowed methods | * |
| `CORS_ALLOW_HEADERS` | Allowed headers | * |

### Logging

| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Log level | INFO |
| `LOG_FORMAT` | Log format (json/text) | json |
| `LOG_FILE` | Log file path | - |

### Observability

| Variable | Description | Default |
|----------|-------------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint | - |
| `OTEL_SERVICE_NAME` | Service name | sentinelai |
| `OTEL_TRACE_SAMPLE_RATE` | Trace sample rate | 1.0 |

## Configuration File

You can also use a YAML configuration file:

```yaml
# config.yaml
app:
  name: SentinelAI
  env: production
  debug: false

database:
  host: postgres.example.com
  port: 5432
  name: sentinelai
  user: sentinelai
  password: ${POSTGRES_PASSWORD}

redis:
  host: redis.example.com
  port: 6379

kafka:
  bootstrap_servers:
    - kafka.example.com:9092

logging:
  level: INFO
  format: json
```

## Production Considerations

1. **Secrets Management** - Use a secrets manager (HashiCorp Vault, AWS Secrets Manager)
2. **SSL/TLS** - Enable TLS for all connections
3. **Rate Limiting** - Configure appropriate rate limits
4. **Monitoring** - Set up OpenTelemetry export
5. **Backup** - Configure database backups
