from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from sugarkube_toolkit.pi_cluster import bootstrap as core

BootstrapError = core.BootstrapError
ClusterConfig = core.ClusterConfig
JoinConfig = core.JoinConfig
NodeConfig = core.NodeConfig
NodeDefaults = core.NodeDefaults
WifiConfig = core.WifiConfig
WorkflowConfig = core.WorkflowConfig
build_flash_command = core.build_flash_command
build_install_command = core.build_install_command
build_join_command = core.build_join_command
build_workflow_dispatch_command = core.build_workflow_dispatch_command
load_cluster_config = core.load_cluster_config
render_cloud_init = core.render_cloud_init
run_bootstrap = core.run_bootstrap

__all__ = [
    "BootstrapError",
    "ClusterConfig",
    "JoinConfig",
    "NodeConfig",
    "NodeDefaults",
    "WifiConfig",
    "WorkflowConfig",
    "build_flash_command",
    "build_install_command",
    "build_join_command",
    "build_workflow_dispatch_command",
    "load_cluster_config",
    "render_cloud_init",
    "run_bootstrap",
    "parse_args",
    "main",
]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the cluster configuration TOML file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview commands without executing them.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip downloading the pi-image artifact.",
    )
    parser.add_argument(
        "--skip-join",
        action="store_true",
        help="Skip the k3s join rehearsal/apply step.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        config_path = Path(args.config).expanduser()
        if not config_path.is_absolute():
            config_path = (Path.cwd() / config_path).resolve()
        config = load_cluster_config(config_path)
        run_bootstrap(
            config,
            dry_run=bool(args.dry_run),
            skip_download=bool(args.skip_download),
            skip_join=bool(args.skip_join),
        )
    except BootstrapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - unexpected failures
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
