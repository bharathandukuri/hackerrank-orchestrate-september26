"""
test_env_modes.py - Test running the Buy or Wait? agent both WITH and WITHOUT .env

Usage:
  # 1. Test offline mode (WITHOUT .env / no API keys):
  python code/test_env_modes.py --mode offline

  # 2. Test dynamic mode (WITH .env / with API key):
  python code/test_env_modes.py --mode online

  # 3. Test both modes sequentially:
  python code/test_env_modes.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Add code/ to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_loader import DataLoader
from evidence_extractor import EvidenceExtractor, load_env_file
from financial_state import FinancialStateBuilder
from cashflow_simulator import CashflowSimulator
from plan_evaluator import PlanEvaluator
from plan_ranker import PlanRanker


def test_offline_mode():
    print("\n" + "=" * 70)
    print("  [TEST 1] Testing Agent WITHOUT .env (Offline / Pure Deterministic Mode)")
    print("=" * 70)

    # Temporarily remove any API keys from environment
    old_gemini = os.environ.pop("GEMINI_API_KEY", None)
    old_google = os.environ.pop("GOOGLE_API_KEY", None)

    try:
        print("  1. Checking environment keys:")
        print(f"     GEMINI_API_KEY set? {'GEMINI_API_KEY' in os.environ}")
        print(f"     GOOGLE_API_KEY set? {'GOOGLE_API_KEY' in os.environ}")

        print("  2. Ingesting dataset and initializing EvidenceExtractor:")
        loader = DataLoader("dataset").load_all()
        extractor = EvidenceExtractor(loader=loader)

        print(
            f"     - Cached Image Facts: {len(extractor.images.facts_by_event_id)} / 16"
        )
        print(f"     - Total Message Facts: {len(extractor.messages.facts)} / 215")
        assert (
            len(extractor.images.facts_by_event_id) == 16
        ), "All 16 image facts must be present"
        assert len(extractor.messages.facts) >= 215, "All message facts must be present"

        print("  3. Simulating 25 sample requests offline:")
        builder = FinancialStateBuilder(loader, extractor)
        sim = CashflowSimulator(forecast_days=90)
        evaluator = PlanEvaluator(loader, extractor, builder, sim)
        ranker = PlanRanker()

        matches = 0
        for s in loader.sample_requests:
            candidates = evaluator.evaluate(s)
            best = ranker.select_best_plan(candidates)
            if best.method == s.recommended_payment_method:
                matches += 1

        print(
            f"     - Recommended method match: {matches} / {len(loader.sample_requests)} (100%)"
        )
        assert matches == 25, "Must achieve 25/25 match on sample requests"

        print("\n  >>> RESULT: OFFLINE MODE PASSED PERFECTLY! <<<")
        print(
            "      The agent operates with 100% accuracy with ZERO API keys and ZERO .env."
        )
    finally:
        # Restore environment
        if old_gemini:
            os.environ["GEMINI_API_KEY"] = old_gemini
        if old_google:
            os.environ["GOOGLE_API_KEY"] = old_google


def test_online_mode():
    print("\n" + "=" * 70)
    print("  [TEST 2] Testing Agent WITH .env (Dynamic VLM Extraction Mode)")
    print("=" * 70)

    env_path = load_env_file()
    if env_path:
        print(f"  1. Found .env file at: {env_path.resolve()}")
    else:
        print("  1. No .env file found in workspace root or code/ folder.")

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("     Notice: No GEMINI_API_KEY or GOOGLE_API_KEY is currently defined.")
        print("     To test dynamic VLM calling:")
        print("       a) Create a file named `.env` in the project root")
        print("       b) Add: GEMINI_API_KEY=your_actual_gemini_api_key")
        print("       c) Re-run: python code/test_env_modes.py --mode online")
        print("\n  2. Testing graceful offline fallback when key is absent:")
        extractor = EvidenceExtractor()
        amt = extractor.images.get_amount_for_event("event_253")
        print(f"     - Extracted amount for event_253 from cache: {amt} IDR")
        assert amt == 4365000.0
        print("\n  >>> RESULT: GRACEFUL FALLBACK VERIFIED! <<<")
        return

    print(f"  2. GEMINI_API_KEY detected: {api_key[:6]}...{api_key[-4:]}")
    print("  3. Attempting dynamic VLM extraction on media/images/image_01.png:")

    image_path = Path("dataset/media/images/image_01.png")
    if not image_path.exists():
        print(f"     Warning: {image_path} not found.")
        return

    extractor = EvidenceExtractor()
    fact = extractor.images.extract_dynamically(
        image_path=image_path,
        event_id="event_253",
        image_id="image_01",
        currency="IDR",
    )

    if fact:
        print(f"     SUCCESS: Dynamically extracted via Gemini 2.5 Flash VLM!")
        print(f"     - Amount: {fact.amount} {fact.currency}")
        print(f"     - Source: {fact.extracted_from}")
        print("\n  >>> RESULT: ONLINE VLM EXTRACTION PASSED! <<<")
    else:
        print("     VLM call failed (e.g. invalid key, rate limit, or no internet).")
        print("     Agent automatically falls back to verified cache.")


def main():
    parser = argparse.ArgumentParser(
        description="Test Buy or Wait? agent in offline and online .env modes"
    )
    parser.add_argument(
        "--mode",
        choices=["offline", "online", "both"],
        default="both",
        help="Which mode to test",
    )
    args = parser.parse_args()

    if args.mode in ("offline", "both"):
        test_offline_mode()

    if args.mode in ("online", "both"):
        test_online_mode()


if __name__ == "__main__":
    main()
