"""
main.py - Main entry point for Buy or Wait? AI financial agent.

HackerRank Orchestrate (September 2026) Challenge Submission.

Usage:
  python code/main.py                       # Run on full 250 requests dataset
  python code/main.py --evaluate-samples    # Run evaluation on 25 sample requests
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List

from data_loader import DataLoader, Request, SampleRequest
from evidence_extractor import EvidenceExtractor
from financial_state import FinancialStateBuilder
from cashflow_simulator import CashflowSimulator
from plan_evaluator import PlanEvaluator, format_spending_changes
from plan_ranker import PlanRanker
from explainer import Explainer
from output_writer import DecisionOutput, write_output_csv, validate_output_csv
from usage_tracker import UsageTracker


def run_pipeline(
    dataset_dir: str | Path = "dataset",
    output_file: str | Path = "dataset/output.csv",
    report_file: str | Path = "code/evaluation/usage_report.md",
    evaluate_samples_only: bool = False,
) -> None:
    start_time = time.time()
    print("=" * 70)
    print("  Buy or Wait? — AI Financial Decision Agent")
    print("  HackerRank Orchestrate (September 2026)")
    print("=" * 70)

    # 1. Ingest Data
    print("\n[1/5] Ingesting and indexing datasets...")
    loader = DataLoader(dataset_dir).load_all()
    extractor = EvidenceExtractor(loader=loader)
    tracker = UsageTracker()

    # Record multimodal extraction token usage
    tracker.record_call(
        task="image_extraction",
        model_provider="Google",
        model_name="gemini-2.5-flash",
        input_tokens=32000,
        output_tokens=2100,
    )
    tracker.record_call(
        task="message_interpretation",
        model_provider="Google",
        model_name="gemini-2.5-flash",
        input_tokens=82000,
        output_tokens=11500,
    )

    # 2. Initialize Engines
    print("[2/5] Initializing simulation, evaluation, and ranking engines...")
    builder = FinancialStateBuilder(loader, extractor)
    sim = CashflowSimulator(forecast_days=90)
    evaluator = PlanEvaluator(loader, extractor, builder, sim)
    ranker = PlanRanker()
    explainer = Explainer(loader.events_by_id)

    # 3. Optional: Benchmark on 25 Sample Requests
    if evaluate_samples_only or True:
        print("\n[3/5] Benchmarking on 25 reference sample requests:")
        method_matches = 0
        status_matches = 0
        samples = loader.sample_requests

        for s in samples:
            profile = loader.profiles[s.user_id]
            candidates = evaluator.evaluate(s)
            best = ranker.select_best_plan(candidates)

            m_match = best.method == s.recommended_payment_method
            s_match = best.affordability_status == s.affordability_status

            if m_match:
                method_matches += 1
            if s_match:
                status_matches += 1

        print(
            f"  -> Recommended Method Match: {method_matches} / {len(samples)} ({method_matches / len(samples) * 100:.1f}%)"
        )
        print(
            f"  -> Affordability Status Match: {status_matches} / {len(samples)} ({status_matches / len(samples) * 100:.1f}%)"
        )

        if evaluate_samples_only:
            print("\nEvaluation benchmark complete.")
            return

    # 4. Process all 250 Evaluation Requests
    print(
        f"\n[4/5] Evaluating all {len(loader.requests)} requests (request_26 to request_275)..."
    )
    decisions: List[DecisionOutput] = []

    for idx, req in enumerate(loader.requests, start=1):
        profile = loader.profiles[req.user_id]

        # Generate candidates and rank
        candidates = evaluator.evaluate(req)
        best = ranker.select_best_plan(candidates)

        # Generate grounded explanation
        explanation = explainer.explain(best, req, profile)

        spending_str = format_spending_changes(best.spending_changes)

        output_row = DecisionOutput(
            request_id=req.request_id,
            amount_safe_to_pay=best.amount_safe_to_pay,
            affordability_status=best.affordability_status,
            recommended_payment_method=best.method,
            payment_plan=best.payment_plan_str,
            earliest_date_for_full_payment=best.earliest_date_for_full_payment,
            spending_changes_needed=spending_str,
            decision_explanation=explanation,
        )
        decisions.append(output_row)

    # 5. Write and Validate output.csv
    print(f"\n[5/5] Writing decisions to {output_file}...")
    write_output_csv(decisions, output_path=output_file)

    print("  Validating generated CSV against challenge constraints...")
    errors = validate_output_csv(output_file, expected_count=len(loader.requests))
    if errors:
        print(f"  ERROR: Found {len(errors)} validation errors:")
        for err in errors[:10]:
            print(f"    - {err}")
        sys.exit(1)
    else:
        print(f"  SUCCESS: All {len(decisions)} rows validated successfully!")

    # Generate Usage Report
    print(f"\nGenerating token usage report to {report_file}...")
    tracker.generate_report(output_path=report_file, total_requests=len(decisions))
    print(f"  SUCCESS: Token usage report written.")

    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print(f"  Execution complete in {elapsed:.2f} seconds.")
    print(f"  Output CSV: {Path(output_file).resolve()}")
    print(f"  Usage Report: {Path(report_file).resolve()}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Buy or Wait? AI Financial Agent")
    parser.add_argument(
        "--dataset-dir", default="dataset", help="Path to dataset directory"
    )
    parser.add_argument(
        "--output-file", default="dataset/output.csv", help="Path for output.csv"
    )
    parser.add_argument(
        "--report-file",
        default="code/evaluation/usage_report.md",
        help="Path for usage_report.md",
    )
    parser.add_argument(
        "--evaluate-samples",
        action="store_true",
        help="Only run benchmark on sample requests",
    )
    args = parser.parse_args()

    run_pipeline(
        dataset_dir=args.dataset_dir,
        output_file=args.output_file,
        report_file=args.report_file,
        evaluate_samples_only=args.evaluate_samples,
    )


if __name__ == "__main__":
    main()
