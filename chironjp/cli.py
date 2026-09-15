"""Public-preview commands backed by the extracted Chiron core."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ingress import import_stream
from .registry import load_registry
from .runner import claim_and_run, finish_review
from .store import Store
from .tailor import admit_package, ensure_source_request, finish_request, render_request, run_one


def _ingest(args: argparse.Namespace) -> None:
    store = Store(args.database)
    store.initialize()
    if args.input == "-":
        result = import_stream(store, sys.stdin)
    else:
        with Path(args.input).open("r", encoding="utf-8") as handle:
            result = import_stream(store, handle)
    print(json.dumps(result, sort_keys=True))


def _jobs(args: argparse.Namespace) -> None:
    rows = Store(args.database, readonly=True).source_jobs()
    print(json.dumps(rows, indent=2, sort_keys=True))


def _store(path: Path) -> Store:
    store = Store(path)
    store.initialize()
    return store


def _tailor_request(args: argparse.Namespace) -> None:
    result = ensure_source_request(
        _store(args.database), source_row_id=args.source,
        profile_path=args.profile, bank_path=args.bank, template_path=args.template,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def _tailor_render(args: argparse.Namespace) -> None:
    registry = load_registry(args.registry)
    if registry.database != args.database.expanduser().resolve():
        raise ValueError("--database does not match the configured registry")
    result = render_request(
        _store(args.database), registry, request_id=args.request,
        selection_path=args.manifest, workspace=args.workspace,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def _tailor_finish(args: argparse.Namespace) -> None:
    registry = load_registry(args.registry)
    if registry.database != args.database.expanduser().resolve():
        raise ValueError("--database does not match the configured registry")
    result = finish_request(
        _store(args.database), registry, request_id=args.request,
        validation_path=args.validation, visual_inspection_path=args.visual_inspection,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def _tailor_run(args: argparse.Namespace) -> None:
    registry = load_registry(args.registry)
    if registry.database != args.database.expanduser().resolve():
        raise ValueError("--database does not match the configured registry")
    result = run_one(_store(args.database), registry, args.request, timeout_seconds=args.timeout)
    print(json.dumps(result, indent=2, sort_keys=True))


def _package_admit(args: argparse.Namespace) -> None:
    result = admit_package(
        _store(args.database), source_row_id=args.source, artifact_id=args.artifact,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def _browser_run(args: argparse.Namespace) -> None:
    registry = load_registry(args.registry)
    if registry.database != args.database.expanduser().resolve():
        raise ValueError("--database does not match the configured registry")
    result = claim_and_run(
        _store(args.database), registry, package_id=args.package,
        worker_id=args.worker, timeout_seconds=args.timeout,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def _finish_review(args: argparse.Namespace) -> None:
    registry = load_registry(args.registry)
    if registry.database != args.database.expanduser().resolve():
        raise ValueError("--database does not match the configured registry")
    result = finish_review(
        _store(args.database), registry, attempt_id=args.attempt,
        review_path=args.review_file,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def _review_serve(args: argparse.Namespace) -> None:
    from .review_server import serve
    serve(
        database=args.database, registry_path=args.registry,
        host=args.host, port=args.port, novnc_root=args.novnc_root,
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="chironctl")
    subparsers = result.add_subparsers(dest="command", required=True)
    ingest = subparsers.add_parser("ingest", help="import normalized source NDJSON")
    ingest.add_argument("--database", type=Path, required=True)
    ingest.add_argument("--input", default="-", help="NDJSON path or - for stdin")
    ingest.set_defaults(func=_ingest)
    jobs = subparsers.add_parser("jobs", help="print the durable source rows as JSON")
    jobs.add_argument("--database", type=Path, required=True)
    jobs.set_defaults(func=_jobs)

    request = subparsers.add_parser("tailor-request", help="create an immutable profile/bank/template-bound request")
    request.add_argument("--database", type=Path, required=True)
    request.add_argument("--source", type=int, required=True)
    request.add_argument("--profile", type=Path, required=True)
    request.add_argument("--bank", type=Path, required=True)
    request.add_argument("--template", type=Path, required=True)
    request.set_defaults(func=_tailor_request)

    render = subparsers.add_parser("tailor-render", help="render one Tailor manifest in its confined workspace")
    render.add_argument("--database", type=Path, required=True)
    render.add_argument("--registry", type=Path, required=True)
    render.add_argument("--request", required=True)
    render.add_argument("--manifest", type=Path, required=True)
    render.add_argument("--workspace", type=Path, required=True)
    render.set_defaults(func=_tailor_render)

    finish = subparsers.add_parser("tailor-finish", help="admit exact deterministic and visual Tailor evidence")
    finish.add_argument("--database", type=Path, required=True)
    finish.add_argument("--registry", type=Path, required=True)
    finish.add_argument("--request", required=True)
    finish.add_argument("--validation", type=Path, required=True)
    finish.add_argument("--visual-inspection", type=Path, required=True)
    finish.set_defaults(func=_tailor_finish)

    run = subparsers.add_parser("tailor-run", help="invoke the configured non-browser Hermes Tailor")
    run.add_argument("--database", type=Path, required=True)
    run.add_argument("--registry", type=Path, required=True)
    run.add_argument("--request", required=True)
    run.add_argument("--timeout", type=int, default=2100)
    run.set_defaults(func=_tailor_run)

    admit = subparsers.add_parser("package-admit", help="bind a passing Tailor artifact to a browser package")
    admit.add_argument("--database", type=Path, required=True)
    admit.add_argument("--source", type=int, required=True)
    admit.add_argument("--artifact", required=True)
    admit.set_defaults(func=_package_admit)

    browser = subparsers.add_parser("browser-run", help="claim one package and prepare it with its isolated Hermes worker")
    browser.add_argument("--database", type=Path, required=True)
    browser.add_argument("--registry", type=Path, required=True)
    browser.add_argument("--package", required=True)
    browser.add_argument("--worker", required=True)
    browser.add_argument("--timeout", type=int, default=2100)
    browser.set_defaults(func=_browser_run)

    finish_review_parser = subparsers.add_parser("finish-review", help="controller-verify and retain one guarded Review")
    finish_review_parser.add_argument("--database", type=Path, required=True)
    finish_review_parser.add_argument("--registry", type=Path, required=True)
    finish_review_parser.add_argument("--attempt", required=True)
    finish_review_parser.add_argument("--review-file", type=Path, required=True)
    finish_review_parser.set_defaults(func=_finish_review)

    review = subparsers.add_parser("review-serve", help="serve the authenticated retained-Review/noVNC edge")
    review.add_argument("--database", type=Path, required=True)
    review.add_argument("--registry", type=Path, required=True)
    review.add_argument("--host", default="127.0.0.1")
    review.add_argument("--port", type=int, default=8080)
    review.add_argument("--novnc-root", type=Path, default=Path("/usr/share/novnc"))
    review.set_defaults(func=_review_serve)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        args.func(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"chironctl: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
