"""Rebuild web/api/medmap_data.json.gz from the raw CSVs.

    python web/api/build_data.py                  # reads <repo>/raw
    python web/api/build_data.py --raw D:/raw

Run this after downloading new raw data, then commit the updated
medmap_data.json.gz. Everyone else (teammates, Docker, hosted demos) uses that
file and never needs raw/.
"""

import argparse
import os
import sys

API_DIR = os.path.dirname(os.path.realpath(__file__))
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)

from data_loader import BUNDLE_PATH, Dataset, missing_raw_files  # noqa: E402

DEFAULT_RAW = os.path.join(os.path.dirname(os.path.dirname(API_DIR)), "raw")


def main():
    parser = argparse.ArgumentParser(description="Rebuild the MedMap data bundle from raw CSVs")
    parser.add_argument("--raw", default=DEFAULT_RAW, help="path to the raw/ data folder")
    parser.add_argument("--out", default=BUNDLE_PATH, help="where to write the bundle")
    args = parser.parse_args()

    missing = missing_raw_files(args.raw)
    if missing:
        sys.exit(f"Missing raw files in {args.raw}:\n  " + "\n  ".join(missing) +
                 "\nDownload them with src/optimal_hospital_placer/etl/get_raw_data.ps1 "
                 "-Sources CMSHospital,PLACES,HPSA,MUAP,RUCA")

    print(f"Reading raw CSVs from {args.raw} ...", flush=True)
    dataset = Dataset(args.raw)
    dataset.save_bundle(args.out)
    size_mb = os.path.getsize(args.out) / 2**20
    print(f"Wrote {args.out} ({size_mb:.1f} MB): {dataset.stats['tracts']} tracts, "
          f"{dataset.stats['hospitals']} hospitals")


if __name__ == "__main__":
    main()
