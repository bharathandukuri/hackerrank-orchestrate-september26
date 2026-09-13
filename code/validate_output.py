"""
validate_output.py - CLI tool to validate output.csv for HackerRank submission.
"""

import sys
from pathlib import Path
from output_writer import validate_output_csv


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "dataset/output.csv"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 250

    print(f"Validating {target} (expecting {count} rows)...")
    errors = validate_output_csv(target, expected_count=count)

    if errors:
        print(f"FAILED: Found {len(errors)} validation errors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("PASSED: Output file is completely valid and ready for submission!")


if __name__ == "__main__":
    main()
