"""CLI entry point for SPAN NILM.

Usage:
    python -m span_nilm collect [--duration SECONDS]
    python -m span_nilm analyze [--start DATE] [--end DATE]
    python -m span_nilm demo
"""

import argparse
import sys

from span_nilm.utils.config import Config
from span_nilm.utils.logging import setup_logging


def cmd_collect(args, config):
    """Run continuous data collection from SPAN panel."""
    from span_nilm.collector.recorder import DataRecorder

    recorder = DataRecorder(config)
    recorder.run_continuous(duration_seconds=args.duration)


def cmd_analyze(args, config):
    """Run device detection analysis on collected data."""
    from span_nilm.analysis.pipeline import AnalysisPipeline

    pipeline = AnalysisPipeline(config)
    result = pipeline.analyze(start_date=args.start, end_date=args.end)
    report = pipeline.generate_report(result)
    print(report)


def cmd_demo(args, config):
    """Run analysis on synthetic demo data to showcase capabilities."""
    from span_nilm.demo import generate_demo_data
    from span_nilm.analysis.pipeline import AnalysisPipeline

    print("Generating synthetic SPAN circuit data...")
    df = generate_demo_data()
    print(f"Generated {len(df):,} readings across {df['circuit_id'].nunique()} circuits\n")

    pipeline = AnalysisPipeline(config)
    result = pipeline.analyze(df=df)
    report = pipeline.generate_report(result)
    print(report)


def main():
    parser = argparse.ArgumentParser(
        prog="span_nilm",
        description="SPAN NILM - Device detection from circuit power data",
    )
    parser.add_argument(
        "--config", default="span_config.yaml",
        help="Path to configuration file",
    )
    subparsers = parser.add_subparsers(dest="command")

    # collect
    collect_parser = subparsers.add_parser("collect", help="Collect data from SPAN panel")
    collect_parser.add_argument("--duration", type=int, default=None, help="Duration in seconds (default: infinite)")

    # analyze
    analyze_parser = subparsers.add_parser("analyze", help="Analyze collected data")
    analyze_parser.add_argument("--start", default=None, help="Start date (YYYY-MM-DD)")
    analyze_parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")

    # demo
    subparsers.add_parser("demo", help="Run demo with synthetic data")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    config = Config.from_yaml(args.config)
    setup_logging(config.logging)

    commands = {
        "collect": cmd_collect,
        "analyze": cmd_analyze,
        "demo": cmd_demo,
    }
    commands[args.command](args, config)


if __name__ == "__main__":
    main()
