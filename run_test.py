"""
PDN Load Transient Test - main entry point.

Usage:
    python run_test.py --serial SN017 --config config/test_config.yaml
    python run_test.py --serial SN999 --mock   # dry-run without hardware
"""

from __future__ import annotations
import argparse
import logging
import sys
from pathlib import Path

from test_sequencer import TestSequencer
import reporter
import yaml


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="PDN Load Transient Test")
    p.add_argument("--serial", required=True, help="Board serial number (e.g. SN017)")
    p.add_argument("--config", default="config/test_config.yaml", help="YAML test config")
    p.add_argument("--mock", action="store_true", help="Use mock instruments (no hardware required)")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
    )
    log = logging.getLogger("run_test")

    seq = TestSequencer(args.config, serial=args.serial, mock=args.mock)
    try:
        captures = seq.run()
    except KeyboardInterrupt:
        log.warning("Interrupted by user; safe-shutdown was called.")
        return 130
    except Exception as e:
        log.exception("Test failed with an exception: %s", e)
        return 2

    config = yaml.safe_load(Path(args.config).read_text())
    results_csv, summary_csv, report_pdf = reporter.write_all(
        captures, seq.run_dir, args.serial, config,
    )

    overall_pass = all(c.result.passed for c in captures)
    log.info("---")
    log.info("Results : %s", results_csv)
    log.info("Summary : %s", summary_csv)
    log.info("Report  : %s", report_pdf)
    log.info("Verdict : %s", "PASS" if overall_pass else "FAIL")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
