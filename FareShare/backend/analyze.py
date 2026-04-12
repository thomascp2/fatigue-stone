"""
CLI tool for Phase 0 manual validation.

Usage:
    python analyze.py <path_to_assessment_notice.pdf>
    python analyze.py <path_to_photo.jpg> --county Madison --parcel 12-34-56-789

Useful for manually validating comp analysis before building the full web pipeline.
"""

import argparse
import json
import sys
from pathlib import Path

from config import settings
from services import extract_assessment, analyze_assessment, generate_report


def main():
    parser = argparse.ArgumentParser(description="FairShare — analyze a property assessment notice")
    parser.add_argument("file", help="PDF or image path of the assessment notice")
    parser.add_argument("--county", help="Override county name (if extraction misses it)")
    parser.add_argument("--parcel", help="Override parcel ID")
    parser.add_argument("--no-comps", action="store_true", help="Skip comp analysis (extraction only)")
    parser.add_argument("--out-dir", default="./reports", help="Output directory for report files")
    args = parser.parse_args()

    file_path = args.file
    if not Path(file_path).exists():
        print(f"ERROR: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    print(f"\n[1/3] Extracting parcel data from: {file_path}")
    try:
        extraction = extract_assessment(file_path)
    except Exception as e:
        print(f"ERROR during extraction: {e}", file=sys.stderr)
        sys.exit(1)

    # Allow CLI overrides
    if args.county:
        extraction["county"] = args.county
    if args.parcel:
        extraction["parcel_id"] = args.parcel

    print("\n--- Extracted Fields ---")
    for key, val in extraction.items():
        if key != "_raw_response":
            print(f"  {key}: {val}")

    if args.no_comps:
        print("\n[Skipping comp analysis — --no-comps flag set]")
        return

    assessed = extraction.get("assessed_value")
    if not assessed:
        print("\nWARNING: No assessed value extracted. Cannot run comp analysis.")
        print("Try running with --no-comps or check the document image quality.")
        sys.exit(1)

    print(f"\n[2/3] Running comp analysis for {extraction.get('county', 'Unknown County')}...")
    try:
        analysis = analyze_assessment(
            assessed_value=assessed,
            appraised_value=extraction.get("appraised_value"),
            county=extraction.get("county") or "",
            parcel_id=extraction.get("parcel_id") or "",
            acreage=extraction.get("acreage"),
            property_class=extraction.get("property_class"),
        )
    except Exception as e:
        print(f"ERROR during comp analysis: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  Comps found: {analysis['comp_count']}")
    print(f"  Median comp appraised: ${analysis.get('median_comp_appraised') or 0:,.0f}")
    print(f"  Expected assessed value: ${analysis.get('expected_assessed') or 0:,.0f}")
    print(f"  Over-assessment: {(analysis.get('overassessment_pct') or 0) * 100:.1f}%")
    print(f"  Flagged for appeal: {'YES' if analysis['is_flagged'] else 'NO'}")
    print(f"\n  {analysis['summary']}")

    print(f"\n[3/3] Generating dispute report...")
    settings.report_dir = args.out_dir
    try:
        report = generate_report(dispute_id=0, extraction=extraction, analysis=analysis)
    except Exception as e:
        print(f"ERROR generating report: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n  Markdown: {report['md_path']}")
    print(f"  PDF:      {report['pdf_path']}")
    print(f"\nDone. Report ID: {report['report_id']}")

    if analysis["is_flagged"]:
        print("\n*** APPEAL RECOMMENDED — strong grounds to file with Board of Equalization ***")


if __name__ == "__main__":
    main()
