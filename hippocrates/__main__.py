"""Command line entry point: python -m hippocrates <command>."""

import argparse

from . import clean, dashboard, fetch, matching, patients, tableau


def main(argv=None):
    parser = argparse.ArgumentParser(prog="hippocrates", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="clean, generate patients, match and build the dashboard")
    commands.add_parser("clean", help="clean the raw trial export")
    commands.add_parser("match", help="match patients to cleaned trials")
    commands.add_parser("dashboard", help="rebuild dashboard/index.html")
    commands.add_parser("tableau", help="rebuild the Tableau data and workbook")
    generate = commands.add_parser("patients", help="generate synthetic patients")
    generate.add_argument("--count", type=int, default=20)
    generate.add_argument("--seed", type=int, default=patients.DEFAULT_SEED)
    download = commands.add_parser("fetch", help="download current studies from ClinicalTrials.gov")
    download.add_argument("--condition", default="glioblastoma OR astrocytoma OR meningioma")
    args = parser.parse_args(argv)

    if args.command == "run":
        clean.run()
        patients.run()
        matching.run()
        dashboard.run()
        tableau.run()
    elif args.command == "clean":
        clean.run()
    elif args.command == "patients":
        patients.run(args.count, args.seed)
    elif args.command == "match":
        matching.run()
    elif args.command == "dashboard":
        dashboard.run()
    elif args.command == "tableau":
        tableau.run()
    elif args.command == "fetch":
        fetch.run(args.condition)


if __name__ == "__main__":
    main()
