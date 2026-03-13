"""Report generation for NILM analysis results.

Produces human-readable output showing:
- Detected devices per circuit
- Confidence levels and matched signatures
- Energy consumption estimates
- Usage patterns and schedules
"""

import logging
from io import StringIO

logger = logging.getLogger("span_nilm.analysis.report")


class ReportGenerator:
    """Generates analysis reports from pipeline results."""

    def generate(self, result) -> str:
        """Generate a full text report from an AnalysisResult."""
        buf = StringIO()

        buf.write("=" * 70 + "\n")
        buf.write("  SPAN NILM - Device Detection Report\n")
        buf.write(f"  Generated: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        buf.write("=" * 70 + "\n\n")

        # Data summary
        buf.write("DATA SUMMARY\n")
        buf.write("-" * 40 + "\n")
        buf.write(f"  Total readings analyzed: {result.total_readings:,}\n")
        if result.date_range:
            buf.write(f"  Date range: {result.date_range[0]} to {result.date_range[1]}\n")
        buf.write(f"  Circuits with activity: {len(result.circuit_events)}\n")
        total_events = sum(len(e) for e in result.circuit_events.values())
        buf.write(f"  Total power events: {total_events:,}\n")
        total_runs = sum(len(r) for r in result.device_runs.values())
        buf.write(f"  Device runs detected: {total_runs:,}\n")
        buf.write("\n")

        # Per-circuit device detection
        buf.write("DETECTED DEVICES BY CIRCUIT\n")
        buf.write("=" * 70 + "\n\n")

        for circuit_id, identifications in sorted(result.identifications.items()):
            if not identifications:
                continue

            # Get circuit name from first cluster's runs
            circuit_name = circuit_id
            for cluster, _ in identifications:
                if cluster.runs:
                    circuit_name = cluster.runs[0].circuit_name
                    break

            buf.write(f"Circuit: {circuit_name} ({circuit_id})\n")
            buf.write("-" * 50 + "\n")

            for cluster, matches in identifications:
                # Device cluster info
                label = cluster.label or "Unknown Device"
                buf.write(f"\n  [{label}]\n")
                buf.write(f"    Power draw:    {cluster.mean_power_w:.0f}W")
                if cluster.std_power_w > 0:
                    buf.write(f" (+/- {cluster.std_power_w:.0f}W)")
                buf.write("\n")

                if cluster.mean_duration_s is not None:
                    buf.write(f"    Avg duration:  {self._format_duration(cluster.mean_duration_s)}\n")
                buf.write(f"    Observations:  {cluster.observation_count}\n")

                # Energy estimate
                if cluster.mean_duration_s is not None:
                    energy_per_run = cluster.mean_power_w * cluster.mean_duration_s / 3600.0
                    daily_est = energy_per_run * cluster.observation_count  # rough estimate
                    buf.write(f"    Energy/run:    {energy_per_run:.1f} Wh\n")

                # Signature matches
                if matches:
                    buf.write("    Possible IDs:\n")
                    for m in matches[:3]:  # Top 3 matches
                        conf_bar = self._confidence_bar(m.confidence)
                        buf.write(f"      {conf_bar} {m.device_name} ({m.category})")
                        buf.write(f" [{m.confidence:.0%}]\n")
                        if m.matched_features:
                            buf.write(f"           Features: {', '.join(m.matched_features[:3])}\n")
                else:
                    buf.write("    Possible IDs:  No matching signatures\n")

            buf.write("\n")

        # Summary statistics
        buf.write("=" * 70 + "\n")
        buf.write("SUMMARY\n")
        buf.write("-" * 40 + "\n")

        total_clusters = sum(len(c) for c in result.clusters.values())
        identified = sum(
            1 for ids in result.identifications.values()
            for cluster, matches in ids
            if cluster.label is not None
        )

        buf.write(f"  Device clusters found:   {total_clusters}\n")
        buf.write(f"  Confidently identified:  {identified}\n")
        buf.write(f"  Needs more data:         {total_clusters - identified}\n")
        buf.write("\n")

        # Category breakdown
        categories: dict[str, int] = {}
        for ids in result.identifications.values():
            for cluster, matches in ids:
                if cluster.label and matches:
                    cat = matches[0].category
                    categories[cat] = categories.get(cat, 0) + 1

        if categories:
            buf.write("  By category:\n")
            for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
                buf.write(f"    {cat}: {count} device(s)\n")

        buf.write("\n" + "=" * 70 + "\n")
        report = buf.getvalue()
        logger.info("Report generated (%d chars)", len(report))
        return report

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration in human-readable form."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds / 60:.1f}m"
        else:
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            return f"{hours}h {mins}m"

    @staticmethod
    def _confidence_bar(confidence: float) -> str:
        """Create a visual confidence indicator."""
        filled = int(confidence * 5)
        return "[" + "#" * filled + "." * (5 - filled) + "]"
