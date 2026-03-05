"""
Batch processor for Clara Answers pipeline.
Processes all transcript files in standalone mode or triggers n8n webhooks.

Usage:
    python batch_process.py --mode=standalone
    python batch_process.py --mode=webhook --webhook-url=http://localhost:5678/webhook/clara
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from processor import TranscriptProcessor, TRANSCRIPT_PAIRS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            Path(__file__).parent.parent / "outputs" / "batch_log.txt",
            mode="w",
            encoding="utf-8"
        )
    ]
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"
OUTPUTS_DIR = BASE_DIR / "outputs"


class BatchMetrics:
    """Track batch processing metrics."""

    def __init__(self):
        self.start_time = datetime.now()
        self.demo_success = 0
        self.demo_fail = 0
        self.onboarding_success = 0
        self.onboarding_fail = 0
        self.errors = []
        self.processing_times = {}

    def to_dict(self):
        elapsed = (datetime.now() - self.start_time).total_seconds()
        return {
            "batch_started": self.start_time.isoformat(),
            "batch_completed": datetime.now().isoformat(),
            "total_elapsed_seconds": round(elapsed, 2),
            "demo_calls": {
                "success": self.demo_success,
                "failed": self.demo_fail,
                "total": self.demo_success + self.demo_fail
            },
            "onboarding_calls": {
                "success": self.onboarding_success,
                "failed": self.onboarding_fail,
                "total": self.onboarding_success + self.onboarding_fail
            },
            "total_processed": self.demo_success + self.onboarding_success,
            "total_failed": self.demo_fail + self.onboarding_fail,
            "errors": self.errors,
            "processing_times": self.processing_times
        }

    def save(self):
        metrics_path = OUTPUTS_DIR / "batch_metrics.json"
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info(f"Metrics saved to {metrics_path}")


def run_standalone(metrics: BatchMetrics):
    """Process all transcripts using local processor (no n8n needed)."""
    processor = TranscriptProcessor()

    # Step 1: Process all demo calls
    logger.info("=" * 60)
    logger.info("PHASE 1: Processing Demo Calls")
    logger.info("=" * 60)

    demo_files = sorted(TRANSCRIPTS_DIR.glob("demo_call_*.txt"))
    if not demo_files:
        logger.error(f"No demo call transcripts found in {TRANSCRIPTS_DIR}")
        return

    for demo_file in demo_files:
        file_start = time.time()
        logger.info(f"\n--- Processing: {demo_file.name} ---")
        try:
            with open(demo_file, "r", encoding="utf-8") as f:
                transcript = f.read()

            memo, spec = processor.process_demo_call(transcript, str(demo_file))
            elapsed = round(time.time() - file_start, 2)
            metrics.processing_times[demo_file.name] = elapsed
            metrics.demo_success += 1
            logger.info(f"  ✅ Success: {memo.get('company_name', 'Unknown')} ({elapsed}s)")
            logger.info(f"     Account ID: {memo.get('account_id')}")
            logger.info(f"     Services: {len(memo.get('services_supported', []))}")
            logger.info(f"     Emergencies: {len(memo.get('emergency_definition', []))}")
            logger.info(f"     Unknowns: {len(memo.get('questions_or_unknowns', []))}")
        except Exception as e:
            metrics.demo_fail += 1
            metrics.errors.append({"file": demo_file.name, "error": str(e)})
            logger.error(f"  ❌ Failed: {e}")

    # Step 2: Process all onboarding calls
    logger.info("\n" + "=" * 60)
    logger.info("PHASE 2: Processing Onboarding Calls")
    logger.info("=" * 60)

    for demo_base, (onboarding_base, account_id) in TRANSCRIPT_PAIRS.items():
        onboarding_file = TRANSCRIPTS_DIR / f"{onboarding_base}.txt"
        if not onboarding_file.exists():
            logger.warning(f"  ⚠️ Onboarding transcript not found: {onboarding_file.name}")
            continue

        file_start = time.time()
        logger.info(f"\n--- Processing: {onboarding_file.name} (account: {account_id}) ---")
        try:
            with open(onboarding_file, "r", encoding="utf-8") as f:
                transcript = f.read()

            updated_memo, updated_spec, changelog = processor.process_onboarding_call(
                transcript, account_id, str(onboarding_file)
            )
            elapsed = round(time.time() - file_start, 2)
            metrics.processing_times[onboarding_file.name] = elapsed
            metrics.onboarding_success += 1
            logger.info(f"  ✅ Success: {updated_memo.get('company_name', 'Unknown')} ({elapsed}s)")
            logger.info(f"     Changelog lines: {len(changelog.splitlines())}")
        except Exception as e:
            metrics.onboarding_fail += 1
            metrics.errors.append({"file": onboarding_file.name, "error": str(e)})
            logger.error(f"  ❌ Failed: {e}")


def run_webhook(webhook_url: str, metrics: BatchMetrics):
    """Trigger n8n webhook for each transcript."""
    try:
        import httpx
    except ImportError:
        logger.error("httpx not installed. Run: pip install httpx")
        sys.exit(1)

    client = httpx.Client(timeout=120)

    # Process demo calls via webhook
    logger.info("=" * 60)
    logger.info("PHASE 1: Triggering Demo Call Webhooks")
    logger.info("=" * 60)

    demo_files = sorted(TRANSCRIPTS_DIR.glob("demo_call_*.txt"))
    for demo_file in demo_files:
        logger.info(f"\n--- Triggering: {demo_file.name} ---")
        try:
            with open(demo_file, "r", encoding="utf-8") as f:
                transcript = f.read()

            resp = client.post(
                f"{webhook_url}/demo",
                json={
                    "transcript": transcript,
                    "filename": demo_file.name,
                    "pipeline": "demo"
                }
            )
            resp.raise_for_status()
            metrics.demo_success += 1
            logger.info(f"  ✅ Webhook triggered successfully (status: {resp.status_code})")
        except Exception as e:
            metrics.demo_fail += 1
            metrics.errors.append({"file": demo_file.name, "error": str(e)})
            logger.error(f"  ❌ Webhook failed: {e}")

        time.sleep(2)  # Rate limit between requests

    # Process onboarding calls via webhook
    logger.info("\n" + "=" * 60)
    logger.info("PHASE 2: Triggering Onboarding Call Webhooks")
    logger.info("=" * 60)

    for demo_base, (onboarding_base, account_id) in TRANSCRIPT_PAIRS.items():
        onboarding_file = TRANSCRIPTS_DIR / f"{onboarding_base}.txt"
        if not onboarding_file.exists():
            continue

        logger.info(f"\n--- Triggering: {onboarding_file.name} ---")
        try:
            with open(onboarding_file, "r", encoding="utf-8") as f:
                transcript = f.read()

            resp = client.post(
                f"{webhook_url}/onboarding",
                json={
                    "transcript": transcript,
                    "filename": onboarding_file.name,
                    "account_id": account_id,
                    "pipeline": "onboarding"
                }
            )
            resp.raise_for_status()
            metrics.onboarding_success += 1
            logger.info(f"  ✅ Webhook triggered successfully")
        except Exception as e:
            metrics.onboarding_fail += 1
            metrics.errors.append({"file": onboarding_file.name, "error": str(e)})
            logger.error(f"  ❌ Webhook failed: {e}")

        time.sleep(2)

    client.close()


def main():
    parser = argparse.ArgumentParser(description="Clara Answers Batch Processor")
    parser.add_argument(
        "--mode", choices=["standalone", "webhook"], default="standalone",
        help="Processing mode: standalone (local) or webhook (n8n)"
    )
    parser.add_argument(
        "--webhook-url", default="http://localhost:5678/webhook/clara",
        help="n8n webhook URL (only for webhook mode)"
    )
    args = parser.parse_args()

    logger.info(f"Clara Answers Batch Processor - Mode: {args.mode}")
    logger.info(f"Transcripts directory: {TRANSCRIPTS_DIR}")
    logger.info(f"Outputs directory: {OUTPUTS_DIR}")

    # Ensure output directory exists
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    metrics = BatchMetrics()

    if args.mode == "standalone":
        run_standalone(metrics)
    else:
        run_webhook(args.webhook_url, metrics)

    # Save metrics
    metrics.save()

    # Print summary
    m = metrics.to_dict()
    logger.info("\n" + "=" * 60)
    logger.info("BATCH PROCESSING COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Demo Calls:       {m['demo_calls']['success']}/{m['demo_calls']['total']} succeeded")
    logger.info(f"  Onboarding Calls: {m['onboarding_calls']['success']}/{m['onboarding_calls']['total']} succeeded")
    logger.info(f"  Total Processed:  {m['total_processed']}")
    logger.info(f"  Total Failed:     {m['total_failed']}")
    logger.info(f"  Elapsed Time:     {m['total_elapsed_seconds']}s")

    if m['errors']:
        logger.warning(f"\n  Errors ({len(m['errors'])}):")
        for err in m['errors']:
            logger.warning(f"    - {err['file']}: {err['error']}")


if __name__ == "__main__":
    main()
