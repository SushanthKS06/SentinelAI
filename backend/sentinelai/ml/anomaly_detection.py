"""SentinelAI ML Anomaly Detection Module.

Provides unsupervised anomaly detection for metrics including:
- CPU spikes
- Memory leaks
- Latency spikes
- Traffic anomalies
- Error rate anomalies
- Deployment regressions
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from scipy import stats
from scipy.signal import find_peaks

from sentinelai.config import settings
from sentinelai.logging import get_logger, setup_logging

logger = get_logger(__name__)


# =============================================================================
# Anomaly Types
# =============================================================================


class AnomalyType:
    """Anomaly type constants."""
    CPU_SPIKE = "cpu_spike"
    MEMORY_LEAK = "memory_leak"
    LATENCY_SPIKE = "latency_spike"
    TRAFFIC_ANOMALY = "traffic_anomaly"
    ERROR_RATE = "error_rate"
    DEPLOYMENT_REGRESSION = "deployment_regression"


# =============================================================================
# Base Anomaly Detector
# =============================================================================


class BaseAnomalyDetector:
    """Base class for anomaly detection algorithms."""

    def __init__(self, threshold: float = None):
        self.threshold = threshold or settings.ml_anomaly_threshold
        self.scaler = StandardScaler()
        self._is_fitted = False

    def fit(self, data: np.ndarray) -> "BaseAnomalyDetector":
        """Fit the detector on normal data."""
        raise NotImplementedError

    def predict(self, data: np.ndarray) -> np.ndarray:
        """Predict anomalies (1 = normal, -1 = anomaly)."""
        raise NotImplementedError

    def score(self, data: np.ndarray) -> np.ndarray:
        """Return anomaly scores."""
        raise NotImplementedError


# =============================================================================
# Isolation Forest Detector
# =============================================================================


class IsolationForestDetector(BaseAnomalyDetector):
    """Isolation Forest based anomaly detection."""

    def __init__(self, contamination: float = 0.1, **kwargs):
        super().__init__(**kwargs)
        self.contamination = contamination
        self.model = IsolationForest(
            contamination=contamination,
            random_state=42,
            n_estimators=100,
        )

    def fit(self, data: np.ndarray) -> "IsolationForestDetector":
        """Fit the model."""
        if len(data.shape) == 1:
            data = data.reshape(-1, 1)
        self.scaler.fit(data)
        scaled_data = self.scaler.transform(data)
        self.model.fit(scaled_data)
        self._is_fitted = True
        return self

    def predict(self, data: np.ndarray) -> np.ndarray:
        """Predict anomalies."""
        if not self._is_fitted:
            raise ValueError("Model not fitted")
        if len(data.shape) == 1:
            data = data.reshape(-1, 1)
        scaled_data = self.scaler.transform(data)
        return self.model.predict(scaled_data)

    def score(self, data: np.ndarray) -> np.ndarray:
        """Return anomaly scores (-1 to 1, higher = more anomalous)."""
        if not self._is_fitted:
            raise ValueError("Model not fitted")
        if len(data.shape) == 1:
            data = data.reshape(-1, 1)
        scaled_data = self.scaler.transform(data)
        return self.model.score_samples(scaled_data)


# =============================================================================
# Statistical Anomaly Detector
# =============================================================================


class StatisticalDetector(BaseAnomalyDetector):
    """Statistical anomaly detection using z-scores and IQR."""

    def __init__(self, method: str = "zscore", threshold: float = 3.0, **kwargs):
        super().__init__(**kwargs)
        self.method = method
        self.threshold = threshold
        self.mean = None
        self.std = None
        self.q1 = None
        self.q3 = None
        self.iqr = None

    def fit(self, data: np.ndarray) -> "StatisticalDetector":
        """Calculate statistics."""
        self.mean = np.mean(data)
        self.std = np.std(data)
        self.q1 = np.percentile(data, 25)
        self.q3 = np.percentile(data, 75)
        self.iqr = self.q3 - self.q1
        self._is_fitted = True
        return self

    def predict(self, data: np.ndarray) -> np.ndarray:
        """Predict using statistical thresholds."""
        if not self._is_fitted:
            raise ValueError("Model not fitted")

        if self.method == "zscore":
            z_scores = np.abs((data - self.mean) / (self.std + 1e-10))
            return np.where(z_scores > self.threshold, -1, 1)
        elif self.method == "iqr":
            lower = self.q1 - 1.5 * self.iqr
            upper = self.q3 + 1.5 * self.iqr
            return np.where((data < lower) | (data > upper), -1, 1)
        return np.ones_like(data)

    def score(self, data: np.ndarray) -> np.ndarray:
        """Return z-scores as anomaly scores."""
        if not self._is_fitted:
            raise ValueError("Model not fitted")
        return np.abs((data - self.mean) / (self.std + 1e-10))


# =============================================================================
# Time Series Anomaly Detector
# =============================================================================


class TimeSeriesDetector(BaseAnomalyDetector):
    """Time series specific anomaly detection."""

    def __init__(self, window_size: int = 10, **kwargs):
        super().__init__(**kwargs)
        self.window_size = window_size
        self.history = []

    def fit(self, data: np.ndarray) -> "TimeSeriesDetector":
        """Build baseline from historical data."""
        # Use rolling statistics
        self.scaler.fit(data.reshape(-1, 1))
        self._is_fitted = True
        return self

    def predict(self, data: np.ndarray) -> np.ndarray:
        """Detect anomalies in time series."""
        if len(data) < self.window_size:
            return np.ones(len(data))

        predictions = []
        for i in range(len(data)):
            if i < self.window_size:
                predictions.append(1)
                continue

            window = data[max(0, i - self.window_size):i]
            mean = np.mean(window)
            std = np.std(window) + 1e-10

            z_score = abs(data[i] - mean) / std
            predictions.append(-1 if z_score > self.threshold else 1)

        return np.array(predictions)

    def score(self, data: np.ndarray) -> np.ndarray:
        """Return rolling z-scores."""
        if len(data) < self.window_size:
            return np.zeros(len(data))

        scores = []
        for i in range(len(data)):
            if i < self.window_size:
                scores.append(0)
                continue

            window = data[max(0, i - self.window_size):i]
            mean = np.mean(window)
            std = np.std(window) + 1e-10
            scores.append(abs(data[i] - mean) / std)

        return np.array(scores)


# =============================================================================
# Change Point Detection
# =============================================================================


class ChangePointDetector:
    """Detect change points in time series."""

    def __init__(self, threshold: float = None):
        self.threshold = threshold or settings.ml_change_point_threshold

    def detect(self, data: np.ndarray) -> list[int]:
        """Detect change points using CUSUM-like algorithm."""
        if len(data) < 3:
            return []

        # Calculate cumulative sum
        mean = np.mean(data)
        cusum = np.cumsum(data - mean)

        # Find peaks in CUSUM
        peaks, properties = find_peaks(cusum, height=self.threshold * len(data))

        return peaks.tolist()


# =============================================================================
# Anomaly Detection Pipeline
# =============================================================================


class AnomalyDetectionPipeline:
    """Complete anomaly detection pipeline."""

    def __init__(self):
        self.detectors = {
            AnomalyType.CPU_SPIKE: IsolationForestDetector(contamination=0.05),
            AnomalyType.MEMORY_LEAK: TimeSeriesDetector(window_size=20),
            AnomalyType.LATENCY_SPIKE: StatisticalDetector(method="zscore", threshold=2.5),
            AnomalyType.TRAFFIC_ANOMALY: IsolationForestDetector(contamination=0.1),
            AnomalyType.ERROR_RATE: StatisticalDetector(method="iqr"),
        }
        self.change_point_detector = ChangePointDetector()

    def detect_cpu_spikes(self, values: np.ndarray, timestamps: list[datetime]) -> list[dict[str, Any]]:
        """Detect CPU spikes."""
        detector = self.detectors[AnomalyType.CPU_SPIKE]
        if len(values) < 20:
            return []

        # Fit on historical data
        detector.fit(values[:-10])

        # Predict on recent data
        recent_values = values[-10:]
        scores = detector.score(recent_values)

        anomalies = []
        for i, (value, score) in enumerate(zip(recent_values, scores)):
            if score < -0.5:  # Anomaly threshold
                anomalies.append({
                    "type": AnomalyType.CPU_SPIKE,
                    "timestamp": timestamps[len(timestamps) - 10 + i].isoformat(),
                    "value": float(value),
                    "score": float(score),
                    "severity": "high" if score < -0.8 else "medium",
                })

        return anomalies

    def detect_memory_leaks(self, values: np.ndarray, timestamps: list[datetime]) -> list[dict[str, Any]]:
        """Detect memory leaks using trend analysis."""
        if len(values) < 30:
            return []

        # Calculate rolling trend
        window = 10
        trends = []
        for i in range(window, len(values)):
            window_data = values[i - window:i]
            slope = np.polyfit(range(window), window_data, 1)[0]
            trends.append(slope)

        # Detect consistent positive trends
        anomalies = []
        if np.mean(trends[-5:]) > 0.1:  # Consistent upward trend
            anomalies.append({
                "type": AnomalyType.MEMORY_LEAK,
                "timestamp": timestamps[-1].isoformat(),
                "trend": float(np.mean(trends[-5:])),
                "severity": "high" if np.mean(trends[-5:]) > 0.2 else "medium",
            })

        return anomalies

    def detect_latency_spikes(self, values: np.ndarray, timestamps: list[datetime]) -> list[dict[str, Any]]:
        """Detect latency spikes."""
        detector = self.detectors[AnomalyType.LATENCY_SPIKE]
        if len(values) < 20:
            return []

        detector.fit(values[:-10])
        recent_values = values[-10:]
        scores = detector.score(recent_values)

        anomalies = []
        for i, (value, score) in enumerate(zip(recent_values, scores)):
            if score > 2.5:
                anomalies.append({
                    "type": AnomalyType.LATENCY_SPIKE,
                    "timestamp": timestamps[len(timestamps) - 10 + i].isoformat(),
                    "value": float(value),
                    "score": float(score),
                    "severity": "critical" if score > 4 else "high" if score > 3 else "medium",
                })

        return anomalies

    def detect_traffic_anomalies(self, values: np.ndarray, timestamps: list[datetime]) -> list[dict[str, Any]]:
        """Detect traffic anomalies."""
        detector = self.detectors[AnomalyType.TRAFFIC_ANOMALY]
        if len(values) < 20:
            return []

        detector.fit(values[:-10])
        recent_values = values[-10:]
        scores = detector.score(recent_values)

        anomalies = []
        for i, (value, score) in enumerate(zip(recent_values, scores)):
            if score < -0.5:
                anomalies.append({
                    "type": AnomalyType.TRAFFIC_ANOMALY,
                    "timestamp": timestamps[len(timestamps) - 10 + i].isoformat(),
                    "value": float(value),
                    "score": float(score),
                    "severity": "high" if score < -0.8 else "medium",
                })

        return anomalies

    def detect_error_rate_anomalies(self, values: np.ndarray, timestamps: list[datetime]) -> list[dict[str, Any]]:
        """Detect error rate anomalies."""
        detector = self.detectors[AnomalyType.ERROR_RATE]
        if len(values) < 20:
            return []

        detector.fit(values)
        scores = detector.predict(values)

        anomalies = []
        for i, (value, pred) in enumerate(zip(values, scores)):
            if pred == -1:
                anomalies.append({
                    "type": AnomalyType.ERROR_RATE,
                    "timestamp": timestamps[i].isoformat(),
                    "value": float(value),
                    "severity": "critical" if value > 10 else "high" if value > 5 else "medium",
                })

        return anomalies

    def detect_all(self, metric_name: str, values: list[float], timestamps: list[datetime]) -> list[dict[str, Any]]:
        """Run all detectors based on metric type."""
        if not values or len(values) < 20:
            return []

        values_array = np.array(values)

        # Map metric name to detector
        if "cpu" in metric_name.lower():
            return self.detect_cpu_spikes(values_array, timestamps)
        elif "memory" in metric_name.lower():
            return self.detect_memory_leaks(values_array, timestamps)
        elif "latency" in metric_name.lower() or "response_time" in metric_name.lower():
            return self.detect_latency_spikes(values_array, timestamps)
        elif "request" in metric_name.lower() or "traffic" in metric_name.lower():
            return self.detect_traffic_anomalies(values_array, timestamps)
        elif "error" in metric_name.lower():
            return self.detect_error_rate_anomalies(values_array, timestamps)
        else:
            # Run all detectors
            all_anomalies = []
            all_anomalies.extend(self.detect_cpu_spikes(values_array, timestamps))
            all_anomalies.extend(self.detect_latency_spikes(values_array, timestamps))
            return all_anomalies


# Global pipeline instance
anomaly_pipeline = AnomalyDetectionPipeline()


# =============================================================================
# Forecasting (Simple)
# =============================================================================


class TimeSeriesForecaster:
    """Simple time series forecasting."""

    def __init__(self, horizon: int = None):
        self.horizon = horizon or settings.ml_forecasting_horizon

    def forecast(self, values: list[float], periods: int = None) -> list[float]:
        """Simple linear extrapolation."""
        periods = periods or self.horizon

        if len(values) < 5:
            return [np.mean(values)] * periods

        # Fit linear trend
        x = np.arange(len(values))
        slope, intercept = np.polyfit(x, values, 1)

        # Extrapolate
        future_x = np.arange(len(values), len(values) + periods)
        predictions = slope * future_x + intercept

        return predictions.tolist()

    def detect_trend(self, values: list[float]) -> dict[str, Any]:
        """Detect trend in time series."""
        if len(values) < 5:
            return {"trend": "unknown", "slope": 0}

        x = np.arange(len(values))
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, values)

        trend = "stable"
        if slope > 0.1:
            trend = "increasing"
        elif slope < -0.1:
            trend = "decreasing"

        return {
            "trend": trend,
            "slope": float(slope),
            "r_squared": float(r_value ** 2),
            "p_value": float(p_value),
        }


# Global forecaster
forecaster = TimeSeriesForecaster()


# =============================================================================
# Alert Deduplication
# =============================================================================


class AlertDeduplicator:
    """Deduplicate similar alerts."""

    def __init__(self, time_window_minutes: int = 5):
        self.time_window = timedelta(minutes=time_window_minutes)
        self._alert_cache: dict[str, list[datetime]] = {}

    def is_duplicate(
        self,
        fingerprint: str,
        timestamp: datetime,
    ) -> bool:
        """Check if alert is a duplicate."""
        if fingerprint not in self._alert_cache:
            self._alert_cache[fingerprint] = []
            return False

        # Check if any alert in the window
        for prev_time in self._alert_cache[fingerprint]:
            if abs((timestamp - prev_time).total_seconds()) < self.time_window.total_seconds():
                return True

        return False

    def add_alert(self, fingerprint: str, timestamp: datetime):
        """Add alert to cache."""
        if fingerprint not in self._alert_cache:
            self._alert_cache[fingerprint] = []

        self._alert_cache[fingerprint].append(timestamp)

        # Clean old entries
        cutoff = timestamp - timedelta(hours=24)
        self._alert_cache[fingerprint] = [
            t for t in self._alert_cache[fingerprint]
            if t > cutoff
        ]

    def get_group_key(self, labels: dict[str, str]) -> str:
        """Generate group key for alert grouping."""
        # Use important labels for grouping
        important_keys = ["service", "severity", "environment"]
        return "|".join([
            f"{k}={labels.get(k, 'unknown')}"
            for k in important_keys
        ])


# Global deduplicator
alert_deduplicator = AlertDeduplicator()


# Export
__all__ = [
    "AnomalyType",
    "AnomalyDetectionPipeline",
    "TimeSeriesForecaster",
    "AlertDeduplicator",
    "anomaly_pipeline",
    "forecaster",
    "alert_deduplicator",
    "IsolationForestDetector",
    "StatisticalDetector",
    "TimeSeriesDetector",
    "ChangePointDetector",
]
