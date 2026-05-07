"""SentinelAI AI Orchestration Service.

Orchestrates multi-agent AI workflows for incident investigation,
root cause analysis, and remediation generation using LangGraph.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from enum import Enum

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from sentinelai.config import settings
from sentinelai.database import db_manager
from sentinelai.logging import get_logger, setup_logging
from sentinelai.metrics import metrics
from sentinelai.tracing import init_tracing, traced

logger = get_logger(__name__)
setup_logging("ai-orchestration")
init_tracing("ai-orchestration")

router = APIRouter(prefix="/api/v1/ai", tags=["AI"])


# =============================================================================
# Agent Types
# =============================================================================


class AgentType(str, Enum):
    """AI Agent types."""
    LOG_ANALYSIS = "log_analysis"
    METRICS_ANALYSIS = "metrics_analysis"
    TRACE_ANALYSIS = "trace_analysis"
    DEPLOYMENT_DIFF = "deployment_diff"
    ROOT_CAUSE = "root_cause"
    INCIDENT_TIMELINE = "incident_timeline"
    REMEDIATION = "remediation"
    INCIDENT_SUMMARIZER = "incident_summarizer"


class InvestigationStatus(str, Enum):
    """Investigation status."""
    PENDING = "pending"
    RUNNING = "completed"
    COMPLETED = "completed"
    FAILED = "failed"


# =============================================================================
# State Management
# =============================================================================


class InvestigationState(dict):
    """State for investigation workflow."""

    def __init__(self):
        super().__init__()
        self["incident_id"] = ""
        self["tenant_id"] = ""
        self["status"] = InvestigationStatus.PENDING
        self["logs"] = []
        self["metrics"] = {}
        self["traces"] = []
        self["deployments"] = []
        self["analysis_results"] = {}
        self["root_cause"] = ""
        self["remediation"] = []
        self["summary"] = ""
        self["confidence"] = 0.0
        self["errors"] = []


# =============================================================================
# LLM Client
# =============================================================================


class LLMClient:
    """Unified LLM client supporting multiple providers."""

    def __init__(self):
        self.provider = settings.ai_provider
        self.model = settings.ai_model
        self._client = None

    async def initialize(self):
        """Initialize the LLM client."""
        if self.provider == "vllm":
            try:
                from litellm import acompletion
                self._client = acompletion
            except ImportError:
                logger.warning("litellm not available, using mock client")
        elif self.provider == "openai":
            try:
                import openai
                self._client = openai.AsyncOpenAI()
            except ImportError:
                logger.warning("openai not available, using mock client")

    async def generate(
        self,
        messages: list[dict[str, str]],
        temperature: float = None,
        max_tokens: int = None,
    ) -> str:
        """Generate text using LLM."""
        if self._client is None:
            await self.initialize()

        temperature = temperature or settings.ai_temperature
        max_tokens = max_tokens or settings.ai_max_tokens

        try:
            if self.provider == "vllm":
                response = await self._client(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content
            elif self.provider == "openai":
                response = await self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content
            else:
                return self._mock_generate(messages)
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            metrics.ai_requests_total.labels(
                model=self.model,
                provider=self.provider,
                status="error",
            ).inc()
            raise

    async def _mock_generate(self, messages: list[dict[str, str]]) -> str:
        """Mock generation for testing."""
        return "This is a mock response from the AI system."


# Global LLM client
llm_client = LLMClient()


# =============================================================================
# Agent Implementations
# =============================================================================


class BaseAgent:
    """Base class for AI agents."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Analyze context and return results."""
        raise NotImplementedError


class LogAnalysisAgent(BaseAgent):
    """Agent for analyzing logs."""

    def __init__(self):
        super().__init__(
            name="Log Analysis Agent",
            description="Analyzes logs to find patterns, errors, and anomalies",
        )

    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Analyze logs for the incident."""
        logs = context.get("logs", [])
        query = context.get("query", "Analyze these logs for errors and anomalies")

        if not logs:
            return {
                "agent": self.name,
                "findings": [],
                "summary": "No logs provided for analysis",
            }

        # Build prompt
        prompt = f"""
You are a log analysis expert. Analyze the following logs for errors, anomalies, and patterns.

Query: {query}

Logs:
{chr(10).join([str(log) for log in logs[:100]])}

Provide:
1. Key errors found
2. Patterns or trends
3. Anomalies or unusual behavior
4. Suggested root cause categories
"""

        start_time = datetime.now(timezone.utc)
        try:
            response = await llm_client.generate(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
            )

            metrics.ai_request_duration.labels(
                model=settings.ai_model,
                operation="log_analysis",
            ).observe((datetime.now(timezone.utc) - start_time).total_seconds())

            return {
                "agent": self.name,
                "findings": response,
                "logs_analyzed": len(logs),
                "error_count": sum(1 for l in logs if "error" in str(l.get("level", "")).lower()),
            }
        except Exception as e:
            logger.error(f"Log analysis failed: {e}")
            return {
                "agent": self.name,
                "error": str(e),
                "findings": [],
            }


class MetricsAnalysisAgent(BaseAgent):
    """Agent for analyzing metrics."""

    def __init__(self):
        super().__init__(
            name="Metrics Analysis Agent",
            description="Analyzes metrics to identify performance issues and anomalies",
        )

    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Analyze metrics for the incident."""
        metrics_data = context.get("metrics", {})

        if not metrics_data:
            return {
                "agent": self.name,
                "findings": [],
                "summary": "No metrics provided for analysis",
            }

        # Analyze each metric
        findings = []
        for metric_name, points in metrics_data.items():
            if not points:
                continue

            values = [p.get("value", 0) for p in points]
            if values:
                avg = sum(values) / len(values)
                max_val = max(values)
                min_val = min(values)

                findings.append({
                    "metric": metric_name,
                    "avg": avg,
                    "max": max_val,
                    "min": min_val,
                    "data_points": len(values),
                })

        # Build prompt for AI analysis
        prompt = f"""
You are a metrics analysis expert. Analyze the following metrics for anomalies and performance issues.

Metrics:
{chr(10).join([f"- {f}" for f in findings])}

Provide:
1. Metrics that are outside normal ranges
2. Correlation between different metrics
3. Potential causes of the anomalies
"""

        try:
            response = await llm_client.generate(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
            )

            return {
                "agent": self.name,
                "findings": response,
                "metrics_analyzed": len(findings),
            }
        except Exception as e:
            logger.error(f"Metrics analysis failed: {e}")
            return {
                "agent": self.name,
                "error": str(e),
                "findings": [],
            }


class TraceAnalysisAgent(BaseAgent):
    """Agent for analyzing distributed traces."""

    def __init__(self):
        super().__init__(
            name="Trace Analysis Agent",
            description="Analyzes distributed traces to identify latency and error patterns",
        )

    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Analyze traces for the incident."""
        traces = context.get("traces", [])

        if not traces:
            return {
                "agent": self.name,
                "findings": [],
                "summary": "No traces provided for analysis",
            }

        # Analyze trace structure
        error_traces = [t for t in traces if t.get("status_code", 0) >= 400]
        slow_traces = [t for t in traces if t.get("duration_ms", 0) > 1000]

        prompt = f"""
You are a distributed tracing expert. Analyze the following traces for issues.

Total traces: {len(traces)}
Error traces: {len(error_traces)}
Slow traces: {len(slow_traces)}

Sample traces:
{chr(10).join([str(t) for t in traces[:10]])}

Provide:
1. Services with errors
2. Slow operations
3. Trace patterns indicating issues
"""

        try:
            response = await llm_client.generate(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
            )

            return {
                "agent": self.name,
                "findings": response,
                "traces_analyzed": len(traces),
                "error_count": len(error_traces),
                "slow_count": len(slow_traces),
            }
        except Exception as e:
            logger.error(f"Trace analysis failed: {e}")
            return {
                "agent": self.name,
                "error": str(e),
                "findings": [],
            }


class RootCauseAgent(BaseAgent):
    """Agent for determining root cause."""

    def __init__(self):
        super().__init__(
            name="Root Cause Agent",
            description="Determines root cause from analysis results",
        )

    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Determine root cause from all analysis."""
        analysis_results = context.get("analysis_results", {})

        # Gather all findings
        all_findings = []
        for agent_name, result in analysis_results.items():
            if isinstance(result, dict) and "findings" in result:
                all_findings.append(f"### {agent_name}\n{result['findings']}")

        prompt = f"""
You are a Site Reliability Engineer specializing in root cause analysis.
Based on the following analysis from multiple agents, determine the most likely root cause.

Analysis Results:
{chr(10).join(all_findings)}

Provide:
1. Primary root cause (most likely)
2. Supporting evidence
3. Confidence level (0-100%)
4. Alternative hypotheses
"""

        try:
            response = await llm_client.generate(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
            )

            # Extract confidence (simple parsing)
            confidence = 0.7
            if "confidence" in response.lower():
                import re
                match = re.search(r"(\d+)%", response)
                if match:
                    confidence = int(match.group(1)) / 100

            return {
                "agent": self.name,
                "root_cause": response,
                "confidence": confidence,
            }
        except Exception as e:
            logger.error(f"Root cause analysis failed: {e}")
            return {
                "agent": self.name,
                "error": str(e),
                "root_cause": "Unable to determine root cause",
                "confidence": 0.0,
            }


class RemediationAgent(BaseAgent):
    """Agent for generating remediation steps."""

    def __init__(self):
        super().__init__(
            name="Remediation Agent",
            description="Generates remediation steps for incidents",
        )

    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Generate remediation suggestions."""
        root_cause = context.get("root_cause", "")
        incident_type = context.get("incident_type", "general")

        prompt = f"""
You are a Site Reliability Engineer specializing in incident remediation.
Generate actionable remediation steps for the following root cause.

Root Cause: {root_cause}
Incident Type: {incident_type}

Provide:
1. Immediate mitigation steps
2. Long-term fix suggestions
3. Rollback procedures if applicable
4. Verification steps
5. Risk assessment for each step
"""

        try:
            response = await llm_client.generate(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2500,
            )

            # Parse steps (simplified)
            steps = []
            for line in response.split("\n"):
                if line.strip().startswith(("1.", "2.", "3.", "4.", "5.")):
                    steps.append({"step": line, "auto_executable": False})

            return {
                "agent": self.name,
                "remediation": steps or [{"step": response, "auto_executable": False}],
                "raw_response": response,
            }
        except Exception as e:
            logger.error(f"Remediation generation failed: {e}")
            return {
                "agent": self.name,
                "error": str(e),
                "remediation": [],
            }


class IncidentSummarizerAgent(BaseAgent):
    """Agent for generating incident summaries."""

    def __init__(self):
        super().__init__(
            name="Incident Summarizer Agent",
            description="Generates comprehensive incident summaries",
        )

    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Generate incident summary."""
        incident = context.get("incident", {})
        analysis_results = context.get("analysis_results", {})
        root_cause = context.get("root_cause", "")
        remediation = context.get("remediation", [])

        prompt = f"""
You are a technical writer specializing in incident reports.
Generate a comprehensive incident summary.

Incident:
- Title: {incident.get('title', 'N/A')}
- Severity: {incident.get('severity', 'N/A')}
- Status: {incident.get('status', 'N/A')}
- Started: {incident.get('started_at', 'N/A')}

Root Cause Analysis:
{root_cause}

Remediation Steps:
{chr(10).join([str(r) for r in remediation[:5]])}

Provide a summary including:
1. What happened
2. Impact
3. Root cause
4. Resolution
5. Lessons learned
"""

        try:
            response = await llm_client.generate(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
            )

            return {
                "agent": self.name,
                "summary": response,
            }
        except Exception as e:
            logger.error(f"Summarization failed: {e}")
            return {
                "agent": self.name,
                "error": str(e),
                "summary": "Unable to generate summary",
            }


# =============================================================================
# Agent Registry
# =============================================================================


class AgentRegistry:
    """Registry for all AI agents."""

    def __init__(self):
        self.agents: dict[AgentType, BaseAgent] = {
            AgentType.LOG_ANALYSIS: LogAnalysisAgent(),
            AgentType.METRICS_ANALYSIS: MetricsAnalysisAgent(),
            AgentType.TRACE_ANALYSIS: TraceAnalysisAgent(),
            AgentType.ROOT_CAUSE: RootCauseAgent(),
            AgentType.REMEDIATION: RemediationAgent(),
            AgentType.INCIDENT_SUMMARIZER: IncidentSummarizerAgent(),
        }

    def get_agent(self, agent_type: AgentType) -> BaseAgent:
        """Get agent by type."""
        return self.agents.get(agent_type)

    def get_all_agents(self) -> list[BaseAgent]:
        """Get all registered agents."""
        return list(self.agents.values())


agent_registry = AgentRegistry()


# =============================================================================
# Investigation Workflow
# =============================================================================


class InvestigationWorkflow:
    """LangGraph-based investigation workflow."""

    def __init__(self):
        self.graph = None
        self._build_graph()

    def _build_graph(self):
        """Build the LangGraph workflow."""
        workflow = StateGraph(InvestigationState)

        # Add nodes
        workflow.add_node("collect_logs", self._collect_logs)
        workflow.add_node("collect_metrics", self._collect_metrics)
        workflow.add_node("collect_traces", self._collect_traces)
        workflow.add_node("analyze_logs", self._analyze_logs)
        workflow.add_node("analyze_metrics", self._analyze_metrics)
        workflow.add_node("analyze_traces", self._analyze_traces)
        workflow.add_node("determine_root_cause", self._determine_root_cause)
        workflow.add_node("generate_remediation", self._generate_remediation)
        workflow.add_node("generate_summary", self._generate_summary)

        # Define edges
        workflow.set_entry_point("collect_logs")
        workflow.add_edge("collect_logs", "collect_metrics")
        workflow.add_edge("collect_metrics", "collect_traces")
        workflow.add_edge("collect_traces", "analyze_logs")
        workflow.add_edge("analyze_logs", "analyze_metrics")
        workflow.add_edge("analyze_metrics", "analyze_traces")
        workflow.add_edge("analyze_traces", "determine_root_cause")
        workflow.add_edge("determine_root_cause", "generate_remediation")
        workflow.add_edge("generate_remediation", "generate_summary")
        workflow.add_edge("generate_summary", END)

        self.graph = workflow.compile()

    async def _collect_logs(self, state: InvestigationState) -> InvestigationState:
        """Collect logs for investigation."""
        # This would query the log service
        state["logs"] = []
        return state

    async def _collect_metrics(self, state: InvestigationState) -> InvestigationState:
        """Collect metrics for investigation."""
        # This would query the metrics service
        state["metrics"] = {}
        return state

    async def _collect_traces(self, state: InvestigationState) -> InvestigationState:
        """Collect traces for investigation."""
        # This would query the trace service
        state["traces"] = []
        return state

    async def _analyze_logs(self, state: InvestigationState) -> InvestigationState:
        """Analyze logs using Log Analysis Agent."""
        agent = agent_registry.get_agent(AgentType.LOG_ANALYSIS)
        result = await agent.analyze({"logs": state.get("logs", [])})
        state["analysis_results"]["logs"] = result
        return state

    async def _analyze_metrics(self, state: InvestigationState) -> InvestigationState:
        """Analyze metrics using Metrics Analysis Agent."""
        agent = agent_registry.get_agent(AgentType.METRICS_ANALYSIS)
        result = await agent.analyze({"metrics": state.get("metrics", {})})
        state["analysis_results"]["metrics"] = result
        return state

    async def _analyze_traces(self, state: InvestigationState) -> InvestigationState:
        """Analyze traces using Trace Analysis Agent."""
        agent = agent_registry.get_agent(AgentType.TRACE_ANALYSIS)
        result = await agent.analyze({"traces": state.get("traces", [])})
        state["analysis_results"]["traces"] = result
        return state

    async def _determine_root_cause(self, state: InvestigationState) -> InvestigationState:
        """Determine root cause using Root Cause Agent."""
        agent = agent_registry.get_agent(AgentType.ROOT_CAUSE)
        result = await agent.analyze({
            "analysis_results": state.get("analysis_results", {}),
        })
        state["root_cause"] = result.get("root_cause", "")
        state["confidence"] = result.get("confidence", 0.0)
        return state

    async def _generate_remediation(self, state: InvestigationState) -> InvestigationState:
        """Generate remediation using Remediation Agent."""
        agent = agent_registry.get_agent(AgentType.REMEDIATION)
        result = await agent.analyze({
            "root_cause": state.get("root_cause", ""),
        })
        state["remediation"] = result.get("remediation", [])
        return state

    async def _generate_summary(self, state: InvestigationState) -> InvestigationState:
        """Generate summary using Incident Summarizer Agent."""
        agent = agent_registry.get_agent(AgentType.INCIDENT_SUMMARIZER)
        result = await agent.analyze({
            "incident": state.get("incident", {}),
            "analysis_results": state.get("analysis_results", {}),
            "root_cause": state.get("root_cause", ""),
            "remediation": state.get("remediation", []),
        })
        state["summary"] = result.get("summary", "")
        state["status"] = InvestigationStatus.COMPLETED
        return state

    async def run(self, incident_id: str, tenant_id: str) -> InvestigationState:
        """Run the investigation workflow."""
        state = InvestigationState()
        state["incident_id"] = incident_id
        state["tenant_id"] = tenant_id
        state["status"] = InvestigationStatus.RUNNING

        try:
            result = await self.graph.ainvoke(state)
            return result
        except Exception as e:
            logger.error(f"Investigation workflow failed: {e}")
            state["status"] = InvestigationStatus.FAILED
            state["errors"].append(str(e))
            return state


# Global workflow
investigation_workflow = InvestigationWorkflow()


# =============================================================================
# Request/Response Models
# =============================================================================


class InvestigationRequest(BaseModel):
    """Investigation request."""
    incident_id: str
    include_logs: bool = True
    include_traces: bool = True
    include_metrics: bool = True
    include_deployments: bool = True


class InvestigationResponse(BaseModel):
    """Investigation response."""
    incident_id: str
    status: str
    root_cause: str
    confidence: float
    remediation: list[dict[str, Any]]
    summary: str
    analysis_results: dict[str, Any]


class AgentAnalysisRequest(BaseModel):
    """Single agent analysis request."""
    agent_type: AgentType
    context: dict[str, Any]


# =============================================================================
# API Endpoints
# =============================================================================


@router.post("/investigate")
@traced
async def run_investigation(
    request: InvestigationRequest,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Run full AI investigation on an incident."""
    # Start investigation in background
    result = await investigation_workflow.run(request.incident_id, tenant_id)

    return {
        "incident_id": request.incident_id,
        "status": result.get("status", "pending"),
        "root_cause": result.get("root_cause", ""),
        "confidence": result.get("confidence", 0.0),
    }


@router.post("/analyze")
@traced
async def run_agent_analysis(
    request: AgentAnalysisRequest,
) -> dict[str, Any]:
    """Run a specific agent's analysis."""
    agent = agent_registry.get_agent(request.agent_type)

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {request.agent_type} not found",
        )

    result = await agent.analyze(request.context)

    metrics.ai_requests_total.labels(
        model=settings.ai_model,
        provider=settings.ai_provider,
        status="success",
    ).inc()

    return result


@router.get("/agents")
@traced
async def list_agents() -> list[dict[str, Any]]:
    """List all available AI agents."""
    return [
        {
            "name": agent.name,
            "description": agent.description,
            "type": agent_type.value,
        }
        for agent_type, agent in agent_registry.agents.items()
    ]


@router.post("/remediation")
@traced
async def generate_remediation(
    incident_id: str,
    root_cause: str = Query(...),
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Generate remediation suggestions for an incident."""
    agent = agent_registry.get_agent(AgentType.REMEDIATION)
    result = await agent.analyze({
        "root_cause": root_cause,
        "incident_type": "general",
    })

    return {
        "incident_id": incident_id,
        "remediation": result.get("remediation", []),
    }


@router.post("/summarize")
@traced
async def generate_summary(
    incident_id: str,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Generate incident summary."""
    # Get incident data (would fetch from database)
    incident = {
        "id": incident_id,
        "title": "Sample Incident",
        "severity": "high",
        "status": "investigating",
    }

    agent = agent_registry.get_agent(AgentType.INCIDENT_SUMMARIZER)
    result = await agent.analyze({
        "incident": incident,
        "analysis_results": {},
        "root_cause": "Sample root cause",
        "remediation": [],
    })

    return {
        "incident_id": incident_id,
        "summary": result.get("summary", ""),
    }


@router.get("/models")
@traced
async def list_models() -> dict[str, Any]:
    """List available AI models."""
    return {
        "current_model": settings.ai_model,
        "provider": settings.ai_provider,
        "max_tokens": settings.ai_max_tokens,
        "temperature": settings.ai_temperature,
    }


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    from fastapi import FastAPI as FastAPIBase
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPIBase(
        title="SentinelAI AI Orchestration",
        description="Multi-agent AI orchestration for incident investigation",
        version=settings.app_version,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "sentinelai.ai_orchestration.main:app",
        host="0.0.0.0",
        port=8006,
        reload=settings.app_debug,
    )
