"""Main analysis pipeline - orchestrates data collection, detection, and classification.

This is the top-level coordinator that ties together:
1. Data collection from SPAN panel
2. Event detection (power transitions)
3. State tracking (stable power levels)
4. Device classification (signature matching + ML clustering)
5. Report generation
"""

import logging
from datetime import datetime, timezone

import pandas as pd

from span_nilm.collector.recorder import DataRecorder
from span_nilm.detection.event_detector import EventDetector, DeviceRun
from span_nilm.detection.state_tracker import StateTracker
from span_nilm.models.classifier import DeviceClassifier, DeviceCluster
from span_nilm.models.signatures import SignatureLibrary, SignatureMatch
from span_nilm.analysis.report import ReportGenerator
from span_nilm.utils.config import Config

logger = logging.getLogger("span_nilm.pipeline")


class AnalysisResult:
    """Container for a complete analysis run's results."""

    def __init__(self):
        self.timestamp = datetime.now(timezone.utc)
        self.circuit_events: dict[str, list] = {}
        self.device_runs: dict[str, list[DeviceRun]] = {}
        self.clusters: dict[str, list[DeviceCluster]] = {}
        self.identifications: dict[str, list[tuple[DeviceCluster, list[SignatureMatch]]]] = {}
        self.total_readings = 0
        self.date_range: tuple[str, str] | None = None


class AnalysisPipeline:
    """End-to-end analysis pipeline for device detection."""

    def __init__(self, config: Config):
        self.config = config
        self.recorder = DataRecorder(config)
        self.detector = EventDetector(config.detection)
        self.state_tracker = StateTracker(
            min_state_duration_s=config.detection.min_state_duration_s,
            min_power_delta_w=config.detection.min_power_delta_w,
        )
        self.classifier = DeviceClassifier()
        self.signatures = SignatureLibrary(config.classification.signatures_file)
        self.reporter = ReportGenerator()

    def analyze(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        df: pd.DataFrame | None = None,
    ) -> AnalysisResult:
        """Run the full analysis pipeline on historical or provided data.

        Args:
            start_date: Start date for historical analysis (YYYY-MM-DD).
            end_date: End date for historical analysis (YYYY-MM-DD).
            df: Pre-loaded DataFrame (skips loading from disk if provided).

        Returns:
            AnalysisResult with all detected devices and classifications.
        """
        result = AnalysisResult()

        # Step 1: Load data
        if df is None:
            logger.info("Loading historical data from %s to %s", start_date, end_date)
            df = self.recorder.load_historical(start_date, end_date)

        if df.empty:
            logger.warning("No data available for analysis")
            return result

        result.total_readings = len(df)
        result.date_range = (
            str(df["timestamp"].min()),
            str(df["timestamp"].max()),
        )
        logger.info(
            "Analyzing %d readings from %s to %s",
            result.total_readings, result.date_range[0], result.date_range[1],
        )

        # Step 2: Detect events per circuit
        logger.info("Step 2: Detecting power transition events...")
        result.circuit_events = self.detector.detect_all_circuits(df)
        total_events = sum(len(e) for e in result.circuit_events.values())
        logger.info("Detected %d events across %d circuits", total_events, len(result.circuit_events))

        # Step 3: Pair events into device runs
        logger.info("Step 3: Pairing events into device runs...")
        for circuit_id, events in result.circuit_events.items():
            runs = self.detector.pair_events(events)
            if runs:
                result.device_runs[circuit_id] = runs

        total_runs = sum(len(r) for r in result.device_runs.values())
        logger.info("Identified %d device runs across %d circuits", total_runs, len(result.device_runs))

        # Step 4: Cluster runs to find distinct devices
        logger.info("Step 4: Clustering device runs...")
        for circuit_id, runs in result.device_runs.items():
            clusters = self.classifier.cluster_runs(runs, circuit_id)
            result.clusters[circuit_id] = clusters

        # Step 5: Match clusters against known signatures
        logger.info("Step 5: Matching against device signatures...")
        for circuit_id, clusters in result.clusters.items():
            identifications = []
            for cluster in clusters:
                # Determine pattern type from duty cycle analysis
                pattern = self._infer_pattern(cluster)

                matches = self.signatures.match(
                    power_w=cluster.mean_power_w,
                    duration_s=cluster.mean_duration_s,
                    has_surge=False,  # TODO: detect from event shape
                    pattern=pattern,
                )

                if matches:
                    # Auto-label with top match if confidence is high enough
                    if matches[0].confidence >= self.config.classification.match_threshold:
                        cluster.label = matches[0].device_name

                identifications.append((cluster, matches))

            result.identifications[circuit_id] = identifications

        # Log summary
        identified = sum(
            1 for ids in result.identifications.values()
            for cluster, matches in ids
            if cluster.label is not None
        )
        total_clusters = sum(len(c) for c in result.clusters.values())
        logger.info(
            "Analysis complete: %d device clusters found, %d identified",
            total_clusters, identified,
        )

        return result

    def _infer_pattern(self, cluster: DeviceCluster) -> str | None:
        """Infer the duty cycle pattern of a device cluster."""
        if not cluster.runs or cluster.mean_duration_s is None:
            return None

        # Check for cycling pattern (multiple short runs in sequence)
        if cluster.observation_count >= 3 and cluster.mean_duration_s < 3600:
            if cluster.std_duration_s is not None and cluster.std_duration_s < cluster.mean_duration_s * 0.5:
                return "cycling"

        # Very long sustained runs
        if cluster.mean_duration_s > 3600:
            if cluster.std_power_w < cluster.mean_power_w * 0.1:
                return "sustained"

        # High variance suggests multi-phase
        if cluster.std_power_w > cluster.mean_power_w * 0.3:
            return "multi_phase"

        return "sustained"

    def generate_report(self, result: AnalysisResult) -> str:
        """Generate a human-readable report from analysis results."""
        return self.reporter.generate(result)
