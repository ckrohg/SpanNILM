"""ML-based device classifier that learns from observed patterns.

While the signature library provides rule-based matching, this classifier
uses scikit-learn to learn device patterns from accumulated data, similar
to how Sense improves over time with more observations.

Features extracted for each device run:
- Power level (watts)
- Duration (seconds)
- Time of day (captures usage patterns)
- Day of week
- Power variance during run
- Has startup surge
"""

import logging
import pickle
from pathlib import Path

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler

from span_nilm.detection.event_detector import DeviceRun

logger = logging.getLogger("span_nilm.models.classifier")


class DeviceCluster:
    """A cluster of similar device runs, representing a likely device type."""

    def __init__(self, cluster_id: int, runs: list[DeviceRun]):
        self.cluster_id = cluster_id
        self.runs = runs
        self.label: str | None = None  # Human-assigned or signature-matched label

        powers = [r.power_draw_w for r in runs]
        durations = [r.duration_s for r in runs if r.duration_s is not None]

        self.mean_power_w = float(np.mean(powers))
        self.std_power_w = float(np.std(powers))
        self.mean_duration_s = float(np.mean(durations)) if durations else None
        self.std_duration_s = float(np.std(durations)) if durations else None
        self.observation_count = len(runs)

    def __repr__(self) -> str:
        label = self.label or f"Cluster_{self.cluster_id}"
        return (
            f"{label}: {self.mean_power_w:.0f}W "
            f"(n={self.observation_count}, "
            f"dur={self.mean_duration_s:.0f}s)" if self.mean_duration_s else
            f"{label}: {self.mean_power_w:.0f}W (n={self.observation_count})"
        )


class DeviceClassifier:
    """Unsupervised device classifier using clustering.

    Since we don't have labeled training data initially, we use DBSCAN
    clustering to group similar device runs together. Each cluster likely
    represents a distinct device. Over time, users can label clusters
    and the system learns.
    """

    def __init__(self):
        self.scaler = StandardScaler()
        self.clusters: dict[str, list[DeviceCluster]] = {}  # circuit_id -> clusters
        self._model_dir = Path("./models")

    def _extract_features(self, runs: list[DeviceRun]) -> np.ndarray:
        """Extract feature vectors from device runs."""
        features = []
        for run in runs:
            hour = run.on_event.timestamp.hour + run.on_event.timestamp.minute / 60.0
            dow = run.on_event.timestamp.dayofweek if hasattr(run.on_event.timestamp, 'dayofweek') else 0
            duration = run.duration_s if run.duration_s is not None else 0

            features.append([
                run.power_draw_w,
                duration,
                hour,
                dow,
            ])
        return np.array(features)

    def cluster_runs(self, runs: list[DeviceRun], circuit_id: str) -> list[DeviceCluster]:
        """Cluster device runs for a circuit to identify distinct devices.

        Uses DBSCAN which doesn't require specifying the number of clusters
        upfront - it discovers them from the data density.
        """
        if len(runs) < 3:
            logger.warning("Too few runs (%d) for clustering on circuit %s", len(runs), circuit_id)
            # Return each run as its own cluster
            return [DeviceCluster(i, [r]) for i, r in enumerate(runs)]

        features = self._extract_features(runs)

        # Normalize features so they're comparable
        scaled = self.scaler.fit_transform(features)

        # DBSCAN clustering
        # eps and min_samples tuned for typical home device patterns
        db = DBSCAN(eps=0.8, min_samples=2)
        labels = db.fit_predict(scaled)

        # Group runs by cluster
        cluster_map: dict[int, list[DeviceRun]] = {}
        noise_runs = []
        for run, label in zip(runs, labels):
            if label == -1:
                noise_runs.append(run)
            else:
                cluster_map.setdefault(label, []).append(run)

        clusters = []
        for cluster_id, cluster_runs in cluster_map.items():
            clusters.append(DeviceCluster(cluster_id, cluster_runs))

        # Add noise points as individual clusters
        next_id = max(cluster_map.keys(), default=-1) + 1
        for run in noise_runs:
            clusters.append(DeviceCluster(next_id, [run]))
            next_id += 1

        self.clusters[circuit_id] = clusters
        logger.info(
            "Circuit %s: %d device runs -> %d clusters (%d noise)",
            circuit_id, len(runs), len(cluster_map), len(noise_runs),
        )
        return clusters

    def save(self, path: str | None = None):
        """Save the classifier state."""
        save_path = Path(path) if path else self._model_dir / "classifier.pkl"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            pickle.dump({
                "scaler": self.scaler,
                "clusters": self.clusters,
            }, f)
        logger.info("Saved classifier to %s", save_path)

    def load(self, path: str | None = None):
        """Load a previously saved classifier."""
        load_path = Path(path) if path else self._model_dir / "classifier.pkl"
        if not load_path.exists():
            logger.warning("No saved classifier at %s", load_path)
            return
        with open(load_path, "rb") as f:
            data = pickle.load(f)
        self.scaler = data["scaler"]
        self.clusters = data["clusters"]
        logger.info("Loaded classifier from %s", load_path)
