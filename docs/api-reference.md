# API Reference

SentinelAI provides REST APIs, gRPC services, and WebSocket endpoints for interacting with the platform.

## Base URL

- REST: `http://localhost:8000`
- WebSocket: `ws://localhost:8000/ws`
- gRPC: `localhost:50051`

## Authentication

All API requests require a Bearer token in the Authorization header:

```bash
Authorization: Bearer <your-token>
```

## REST Endpoints

### Incidents

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/incidents` | List all incidents |
| POST | `/api/v1/incidents` | Create a new incident |
| GET | `/api/v1/incidents/{id}` | Get incident by ID |
| PUT | `/api/v1/incidents/{id}` | Update an incident |
| DELETE | `/api/v1/incidents/{id}` | Delete an incident |
| POST | `/api/v1/incidents/{id}/acknowledge` | Acknowledge incident |
| POST | `/api/v1/incidents/{id}/resolve` | Resolve incident |
| GET | `/api/v1/incidents/{id}/timeline` | Get incident timeline |
| POST | `/api/v1/incidents/{id}/comments` | Add comment to incident |

#### Example: Create Incident

```bash
POST /api/v1/incidents
Content-Type: application/json

{
  "title": "High CPU usage on production",
  "description": "CPU usage exceeded 90% threshold",
  "severity": "high",
  "source": "alert",
  "labels": ["production", "cpu"]
}
```

### Alerts

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/alerts` | List all alerts |
| POST | `/api/v1/alerts` | Create an alert |
| GET | `/api/v1/alerts/{id}` | Get alert by ID |
| PUT | `/api/v1/alerts/{id}` | Update an alert |
| POST | `/api/v1/alerts/{id}/acknowledge` | Acknowledge alert |
| POST | `/api/v1/alerts/{id}/suppress` | Suppress alert |

### Metrics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/metrics` | Query metrics data |
| POST | `/api/v1/metrics` | Ingest metrics |
| GET | `/api/v1/metrics/query` | Query time series |
| GET | `/api/v1/metrics/anomalies` | Get detected anomalies |

### Logs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/logs` | Query logs |
| POST | `/api/v1/logs/ingest` | Ingest logs |
| GET | `/api/v1/logs/search` | Full-text search |
| GET | `/api/v1/logs/aggregate` | Log aggregation |

### Traces

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/traces` | Query traces |
| GET | `/api/v1/traces/{id}` | Get trace by ID |
| GET | `/api/v1/traces/spans` | Query spans |
| GET | `/api/v1/traces/dependencies` | Service dependency graph |

### Services

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/services` | List all services |
| POST | `/api/v1/services` | Register a service |
| GET | `/api/v1/services/{id}` | Get service details |
| PUT | `/api/v1/services/{id}` | Update service |
| GET | `/api/v1/services/{id}/health` | Service health status |

### Deployments

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/deployments` | List deployments |
| POST | `/api/v1/deployments` | Create deployment |
| GET | `/api/v1/deployments/{id}` | Get deployment details |
| GET | `/api/v1/deployments/impact/{service_id}` | Deployment impact analysis |

### AI & Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/ai/rca` | Root cause analysis |
| POST | `/api/v1/ai/remediation` | Get remediation suggestions |
| POST | `/api/v1/ai/correlate` | Correlate events |
| GET | `/api/v1/ai/insights` | Get AI insights |

### Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/analytics/incidents` | Incident analytics |
| GET | `/api/v1/analytics/mttr` | Mean time to recovery |
| GET | `/api/v1/analytics/mttd` | Mean time to detect |
| GET | `/api/v1/analytics/alerts` | Alert analytics |

### Users

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/users` | List users |
| POST | `/api/v1/users` | Create user |
| GET | `/api/v1/users/{id}` | Get user |
| PUT | `/api/v1/users/{id}` | Update user |
| DELETE | `/api/v1/users/{id}` | Delete user |

### Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/login` | User login |
| POST | `/api/v1/auth/logout` | User logout |
| POST | `/api/v1/auth/refresh` | Refresh token |
| GET | `/api/v1/auth/me` | Current user info |

## WebSocket Events

Connect to `ws://localhost:8000/ws` for real-time updates.

### Event Types

| Event | Description |
|-------|-------------|
| `incident.created` | New incident created |
| `incident.updated` | Incident updated |
| `alert.firing` | Alert started firing |
| `alert.resolved` | Alert resolved |
| `metric.anomaly` | Anomaly detected |
| `deployment.status` | Deployment status change |

### Example Subscription

```javascript
const ws = new WebSocket('ws://localhost:8000/ws');
ws.onopen = () => {
  ws.send(JSON.stringify({
    action: 'subscribe',
    events: ['incident.created', 'alert.firing']
  }));
};
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data);
};
```

## Data Models

### Incident Severity

- `critical` - Critical severity
- `high` - High severity
- `medium` - Medium severity
- `low` - Low severity
- `info` - Informational

### Incident Status

- `open` - Newly created
- `investigating` - Under investigation
- `identified` - Root cause identified
- `monitoring` - Being monitored
- `resolved` - Resolved
- `closed` - Closed

### Alert State

- `firing` - Currently firing
- `acknowledged` - Acknowledged
- `suppressed` - Suppressed
- `resolved` - Resolved

## Rate Limits

| Endpoint | Limit |
|----------|-------|
| API (general) | 1000 req/min |
| Metrics ingestion | 10000 req/min |
| Log ingestion | 5000 req/min |

## Error Responses

```json
{
  "error": "Not Found",
  "message": "The requested resource was not found",
  "status_code": 404
}
```

## OpenAPI Documentation

Full OpenAPI specs available at:
- Swagger UI: `/api/docs`
- ReDoc: `/api/redoc`
