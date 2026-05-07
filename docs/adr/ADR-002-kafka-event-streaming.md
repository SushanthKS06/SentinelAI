# ADR-002: Use Kafka for Event Streaming

**Status**: Accepted

**Date**: 2024-01-15

## Context

SentinelAI needs to process high-volume events from logs, metrics, traces, and deployments. We need a reliable, scalable event streaming platform.

## Decision

Use Apache Kafka as the primary event streaming platform.

## Consequences

**Positive**:
- High throughput (millions of events/sec)
- Durable message storage
- Replay capability for debugging
- Horizontal scalability

**Negative**:
- Requires ZooKeeper/Kraft for coordination
- Operational complexity
- Need for schema registry

## Notes

Topics: `logs`, `metrics`, `traces`, `deployments`, `incidents`, `alerts`
