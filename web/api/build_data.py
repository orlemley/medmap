"""Rebuild web/api/medmap_data.json.gz from the raw CSVs.

    python web/api/build_data.py                  # reads <repo>/raw
    python web/api/build_data.py --raw D:/raw
    python web/api/build_data.py --offline        # reuse cached hospital locations only

Hospital locations are looked up online (Census Geocoder, then OpenStreetMap;
see docs/hospital-locations.md). Answers are cached in raw/_geocode_cache/,
so the first run takes a while (mostly the OpenStreetMap download) and later
runs take seconds. An interrupted run resumes where it stopped.

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
    parser.add_argument("--offline", action="store_true",
                        help="don't look up hospital locations online; use cached answers only")
    args = parser.parse_args()

    missing = missing_raw_files(args.raw)
    if missing:
        sys.exit(f"Missing raw files in {args.raw}:\n  " + "\n  ".join(missing) +
                 "\nDownload them with src/optimal_hospital_placer/etl/get_raw_data.ps1 "
                 "-Sources CMSHospital,PLACES,HPSA,MUAP,RUCA")

    print(f"Reading raw CSVs from {args.raw} ...", flush=True)
    dataset = Dataset(args.raw, geocode="cache" if args.offline else "online")
    dataset.save_bundle(args.out)
    size_mb = os.path.getsize(args.out) / 2**20
    print(f"Wrote {args.out} ({size_mb:.1f} MB): {dataset.stats['tracts']} tracts, "
          f"{dataset.stats['hospitals']} hospitals")
    total = dataset.stats["hospitals"]
    precise = dataset.stats["hospitals_precise"]
    print(f"Hospital locations: {precise} of {total} ({100 * precise / total:.1f}%) at their real location")
    for step, n in dataset.stats["geocoding_steps"].items():
        print(f"  {step}: {n}")


if __name__ == "__main__":
    main()
