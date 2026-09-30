"""`cv-gen`: generate, run, and publish CircuitVerse testbenches.

Exit codes: 0 success, 1 tests failed, 2 usage/config/engine/network error.
"""

import argparse
import base64
import getpass
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from . import engine, pipeline, project, report
from .config import DEFAULT_ENGINE_REV, DEFAULT_SERVER, Config, ConfigError, load_config
from .engine import EngineError
from .oracles import Registry, load_oracles
from .project import ProjectError

EXIT_FAILED = 1
EXIT_ERROR = 2


class CliError(Exception):
    pass


def _err(message: str) -> None:
    print(f"cv-gen: {message}", file=sys.stderr)


# --- helpers -------------------------------------------------------------------------


def _config(args) -> Config:
    if args.command in {"project", "auth", "engine"} and not args.config:
        config = Config(
            Path.cwd(), None, None, DEFAULT_SERVER, DEFAULT_ENGINE_REV, None, 0, 256, 100, ()
        )
    else:
        config = load_config(args.config)
    return replace(
        config,
        project_file=Path(args.project_file).resolve()
        if getattr(args, "project_file", None)
        else config.project_file,
        project_id=getattr(args, "project_id", None) or config.project_id,
        server=getattr(args, "server", None) or config.server,
        engine_rev=getattr(args, "engine_rev", None) or config.engine_rev,
    )


def _registry(config: Config) -> Registry:
    if config.oracles is None:
        raise CliError("set [generate] oracles in cvgen-tests.toml")
    return load_oracles(config.oracles)


def _project_file(config: Config, override: str | None) -> Path:
    path = Path(override) if override else config.project_file
    if path is None:
        raise CliError("no project file: pass one or set [project] file in cvgen-tests.toml")
    if not path.is_file():
        raise CliError(f"project file not found: {path}")
    return path


def _build(config: Config, source: Path) -> pipeline.Build:
    return pipeline.build(
        config,
        project.load(source),
        _registry(config),
        pipeline.engine_calibrator(config.engine_rev),
    )


def _run_and_report(config, path: Path, args, unchecked=None) -> int:
    raw = engine.run(
        config.engine_rev, path, only=args.only or None, max_failures=args.max_failures
    )
    document = project.load(path)
    result = report.build_report(raw, project.dependency_names(document))
    if args.json:
        print(json.dumps(raw, indent=2))
    else:
        print(report.render_text(result, unchecked=unchecked, verbose=args.verbose), end="")
    return 0 if result.ok else EXIT_FAILED


def _client(config: Config, *, authenticated: bool = True):
    from .sync.auth import TokenStore
    from .sync.client import CircuitVerseClient

    token = None
    if authenticated:
        store = TokenStore(config.server)
        found = store.get()
        info = store.info()
        if found is None or info is None:
            raise CliError("not logged in; run `cv-gen auth login`")
        if info.expired:
            raise CliError("CircuitVerse token expired; run `cv-gen auth login`")
        if info.expires_soon:
            _err(f"warning: token expires {info.expires:%Y-%m-%d %H:%M} UTC")
        token = found[0]
    return CircuitVerseClient(config.server, token)


# --- commands ------------------------------------------------------------------------


def cmd_scopes(args) -> int:
    config = _config(args)
    document = project.load(_project_file(config, args.file))
    bound = {suite.scope: suite.oracle for suite in config.suites}
    names = {info.id: info.name for info in project.scopes(document)}
    for info in project.scopes(document):
        ports = " ".join(f"{p.label or '?'}/{p.width}" for p in info.inputs)
        outs = " ".join(f"{p.label or '?'}/{p.width}" for p in info.outputs)
        tests = f"{info.testbench.case_count} cases" if info.testbench else "no tests"
        oracle = bound.get(info.name, "-")
        print(f"{info.name}\n    in:  {ports}\n    out: {outs}\n    {tests}; oracle: {oracle}")
        if args.deps and info.dependencies:
            deps = ", ".join(sorted(names.get(d, d) for d in info.dependencies))
            print(f"    uses: {deps}")
    unbound = [info.name for info in project.scopes(document) if info.name not in bound]
    if unbound:
        print(f"\n{len(unbound)} circuit(s) without a suite: {', '.join(unbound)}")
    return 0


def cmd_gen(args) -> int:
    config = _config(args)
    source = _project_file(config, args.file)
    built = _build(config, source)
    out = Path(args.out) if args.out else config.build_dir / f"{source.stem}.tested.cv"
    project.save(built.document, out)
    for g in built.generated:
        extra = f", {len(g.unknown)} calibrated" if g.unknown else ""
        print(f"  {g.scope}: {g.data.case_count} {g.kind} cases ({g.oracle}{extra})")
    print(f"wrote {out}")
    return 0


def cmd_run(args) -> int:
    config = _config(args)
    return _run_and_report(config, _project_file(config, args.file), args)


def cmd_check(args) -> int:
    config = _config(args)
    source = _project_file(config, args.file)
    built = _build(config, source)
    out = config.build_dir / f"{source.stem}.tested.cv"
    project.save(built.document, out)
    return _run_and_report(config, out, args, unchecked=built.unchecked)


def cmd_engine(args) -> int:
    from .verilog import engine as v1_engine

    config = _config(args)
    if args.action == "install":
        v1_engine.install_converter()
    converter_ready = v1_engine.converter_ready()
    print(f"converter: yosys2digitaljs 0.10.3 ({'ready' if converter_ready else 'missing'})")
    all_ready = converter_ready
    if args.format in {"legacy", "both"}:
        status = (
            engine.install(config.engine_rev)
            if args.action == "install"
            else engine.status(config.engine_rev)
        )
        print(f"legacy: CircuitVerse {status.rev[:12]} at {status.path}")
        print(f"ready: {'yes' if status.ready else 'no'}")
        all_ready &= status.ready
    if args.format in {"canonical-v1", "both"}:
        path = v1_engine.install() if args.action == "install" else v1_engine.directory()
        prepared = v1_engine.ready()
        print(f"canonical-v1: CircuitVerse {v1_engine.V1_REV[:12]} at {path}")
        print(f"ready: {'yes' if prepared else 'no'}")
        all_ready &= prepared
    return 0 if all_ready else EXIT_ERROR


def cmd_login(args) -> int:
    from .sync.auth import TokenStore

    config = _config(args)
    email = args.email or input("CircuitVerse email: ").strip()
    password = getpass.getpass("CircuitVerse password: ")
    from .sync.client import AuthenticationError

    with _client(config, authenticated=False) as client:
        try:
            token = client.login(email, password)
        except AuthenticationError as error:
            raise CliError("invalid email or password") from error
        finally:
            del password
    store = TokenStore(config.server)
    store.save(token)
    info = store.info()
    who = info.username if info else email
    expires = f", expires {info.expires:%Y-%m-%d} UTC" if info and info.expires else ""
    print(f"logged in to {config.server} as {who}{expires}; token stored in the system keyring")
    return 0


def cmd_logout(args) -> int:
    from .sync.auth import TokenStore

    config = _config(args)
    removed = TokenStore(config.server).delete()
    print("token removed from keyring" if removed else "no stored token")
    return 0


def cmd_whoami(args) -> int:
    from .sync.auth import TokenStore

    config = _config(args)
    info = TokenStore(config.server).info()
    if info is None:
        print("not logged in")
        return EXIT_ERROR
    state = "EXPIRED" if info.expired else f"expires {info.expires:%Y-%m-%d %H:%M} UTC"
    print(f"{info.username} <{info.email}> via {info.source}; {state}")
    if args.remote:
        with _client(config) as client:
            me = client.me()
        print(f"server confirms user id {me.get('data', {}).get('id', '?')}")
    return 0


def cmd_pull(args) -> int:
    from .sync.push import pull

    config = _config(args)
    with _client(config, authenticated=not args.anonymous) as client:
        path, backup = pull(client, config)
    print(f"pulled {config.project_id} -> {path}")
    if backup:
        print(f"previous local copy backed up to {backup}")
    return 0


def _preview_image(args) -> str:
    if args.use_default_preview:
        return ""
    data = Path(args.preview_jpeg).read_bytes()
    if not data.startswith(b"\xff\xd8"):
        raise CliError(f"{args.preview_jpeg} is not a JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


def cmd_push(args) -> int:
    from .sync.push import execute_push, plan_push

    config = _config(args)
    if not args.dry_run and not (args.use_default_preview or args.preview_jpeg):
        raise CliError(
            "choose the preview image: --use-default-preview or --preview-jpeg PATH "
            "(CircuitVerse replaces the preview on every circuit upload)"
        )
    registry = _registry(config)
    with _client(config) as client:
        plan = plan_push(
            client,
            config,
            registry,
            pipeline.engine_calibrator(config.engine_rev),
            force=args.force,
        )
        print(
            f"project {plan.ref} ({plan.name}): {len(plan.changed)} circuit(s) get new tests, "
            f"request {plan.request_bytes / 1e6:.2f} MB"
        )
        for name in plan.changed:
            print(f"  {name}")
        if not plan.changed:
            print("nothing to push")
            return 0
        if args.dry_run:
            preview = config.build_dir / f"push-preview-{plan.ref}.cv"
            project.save(plan.build.document, preview)
            print(f"dry run: nothing sent; proposed document at {preview}")
            return 0
        if not args.yes:
            if not sys.stdin.isatty():
                raise CliError("refusing to push without confirmation; pass --yes")
            if input("upload? [y/N] ").strip().lower() != "y":
                print("aborted")
                return EXIT_ERROR
        backup = execute_push(client, config, plan, image=_preview_image(args))
    print(f"pushed and verified; previous version backed up at {backup}")
    return 0


def cmd_verilog_build(args) -> int:
    from .verilog import build, load_spec

    result = build(load_spec(args.manifest))
    print(f"wrote {result.output} ({len(result.scopes)} scopes, {result.format})")
    _print_import_target(result.format)
    return 0


def cmd_verilog_check(args) -> int:
    from .verilog import check, load_spec

    result = check(load_spec(args.manifest))
    print(f"checked {result.samples} samples; wrote {result.output}")
    _print_import_target(result.format)
    return 0


def _print_import_target(fmt: str) -> None:
    target = (
        "https://circuitverse.org/simulator"
        if fmt == "legacy"
        else "https://circuitverse.org/simulatorvue?simver=v1"
    )
    print(f"import this {fmt} file at {target}")


# --- parser --------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cv-gen")
    parser.add_argument("--config", help="cvgen-tests.toml path")
    sub = parser.add_subparsers(dest="command", required=True)
    tests = sub.add_parser("tests", help="test generation and execution")
    test_sub = tests.add_subparsers(dest="test_action", required=True)

    def run_options(p):
        p.add_argument("--only", action="append")
        p.add_argument("-v", "--verbose", action="store_true")
        p.add_argument("--json", action="store_true")
        p.add_argument("--max-failures", type=int, default=5)

    p = test_sub.add_parser("scopes")
    p.add_argument("file", nargs="?")
    p.add_argument("--deps", action="store_true")
    p.set_defaults(func=cmd_scopes)
    p = test_sub.add_parser("generate")
    p.add_argument("file", nargs="?")
    p.add_argument("-o", "--out")
    p.set_defaults(func=cmd_gen)
    p = test_sub.add_parser("run")
    p.add_argument("file", nargs="?")
    run_options(p)
    p.set_defaults(func=cmd_run)
    p = test_sub.add_parser("check")
    p.add_argument("file", nargs="?")
    run_options(p)
    p.set_defaults(func=cmd_check)
    p = test_sub.add_parser("push")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    preview = p.add_mutually_exclusive_group()
    preview.add_argument("--use-default-preview", action="store_true")
    preview.add_argument("--preview-jpeg")
    p.add_argument("-y", "--yes", action="store_true")
    p.set_defaults(func=cmd_push)
    p = test_sub.add_parser("csv")
    p.add_argument("-n", "--name")
    p.add_argument("-i", "--intensity", type=int)
    p.add_argument("-m", "--max-cases", type=int, default=0)
    p.add_argument("-s", "--seed", type=int, default=0)
    p.add_argument("--list", action="store_true")
    p.add_argument("output", nargs="?")

    def csv(args):
        from .cli import main

        argv = []
        for flag, key in (("-n", "name"), ("-i", "intensity"), ("-m", "max_cases"), ("-s", "seed")):
            if getattr(args, key) is not None and (
                key not in {"max_cases", "seed"} or getattr(args, key)
            ):
                argv += [flag, str(getattr(args, key))]
        if args.list:
            argv.append("--list")
        if args.output:
            argv.append(args.output)
        return main(argv)

    p.set_defaults(func=csv)

    verilog = sub.add_parser("verilog")
    verilog_sub = verilog.add_subparsers(dest="verilog_action", required=True)
    for action, func in (("build", cmd_verilog_build), ("check", cmd_verilog_check)):
        p = verilog_sub.add_parser(action)
        p.add_argument("--manifest", default="cvgen-verilog.toml")
        p.set_defaults(func=func)
    p = sub.add_parser("engine")
    p.add_argument("action", choices=["install", "status"])
    p.add_argument("--revision", dest="engine_rev")
    p.add_argument("--format", choices=["legacy", "canonical-v1", "both"], default="both")
    p.set_defaults(func=cmd_engine)
    auth = sub.add_parser("auth")
    auth.add_argument("--server", default=DEFAULT_SERVER)
    auth_sub = auth.add_subparsers(dest="auth_action", required=True)
    p = auth_sub.add_parser("login")
    p.add_argument("--email")
    p.set_defaults(func=cmd_login)
    auth_sub.add_parser("logout").set_defaults(func=cmd_logout)
    p = auth_sub.add_parser("whoami")
    p.add_argument("--remote", action="store_true")
    p.set_defaults(func=cmd_whoami)
    shared = sub.add_parser("project")
    shared.add_argument("--server", default=DEFAULT_SERVER)
    shared_sub = shared.add_subparsers(dest="project_action", required=True)
    p = shared_sub.add_parser("pull")
    p.add_argument("--project-id", required=True)
    p.add_argument("--project-file", required=True)
    p.add_argument("--anonymous", action="store_true")
    p.set_defaults(func=cmd_pull)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.func(args)
    except (CliError, ConfigError, ProjectError, EngineError, ValueError, OSError) as error:
        _err(str(error))
        return EXIT_ERROR
    except KeyboardInterrupt:
        _err("interrupted")
        return EXIT_ERROR
    except Exception as error:
        from .sync.client import AuthenticationError, CircuitVerseError
        from .sync.push import SyncError

        if isinstance(error, AuthenticationError):
            _err(f"{error} (token missing, invalid, or expired: run `cv-gen auth login`)")
        elif isinstance(error, CircuitVerseError | SyncError):
            _err(str(error))
        else:
            raise
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
