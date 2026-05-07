# ADR-003: Use vLLM for LLM Inference

**Status**: Accepted

**Date**: 2024-01-15

## Context

SentinelAI requires LLM inference for root cause analysis, remediation suggestions, and natural language queries. We need a high-performance, cost-effective inference solution.

## Decision

Use vLLM for LLM inference with the following configuration:
- Model: Llama 3 8B Instruct (configurable)
- Backend: vLLM with PagedAttention
- Deployment: Single GPU or multi-GPU setup

## Consequences

**Positive**:
- 2-4x throughput vs HuggingFace
- Reduced memory usage with PagedAttention
- OpenAI-compatible API
- Support for various model architectures

**Negative**:
- Requires GPU hardware
- Limited to supported model architectures
- Cold start time for new requests

## Notes

Can be swapped for other backends (OpenAI, Anthropic) via configuration.
