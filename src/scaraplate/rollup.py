import importlib
import io
import os
import pprint
import tempfile
from pathlib import Path
from typing import BinaryIO, Dict, Mapping, NamedTuple, Optional, Type

import click
import yaml
from cookiecutter.main import cookiecutter

from .parsers import setup_cfg_parser_from_path
from .strategies import Strategy
from .template import TemplateMeta, get_template_meta_from_git


class ScaraplateYaml(NamedTuple):
    default_strategy: Type[Strategy]
    strategies_mapping: Mapping[str, Type[Strategy]]


def rollup(template_dir: str, target_project_dir: str, no_input: bool) -> None:
    template_path = Path(template_dir)
    target_path = Path(target_project_dir)

    template_meta = get_template_meta_from_git(template_path)
    scaraplate_yaml = get_scaraplate_yaml(template_path)

    target_path.mkdir(parents=True, exist_ok=True, mode=0o755)

    extra_context = get_target_project_cookiecutter_context(target_path)

    with tempfile.TemporaryDirectory() as tempdir_path:
        output_dir = Path(tempdir_path) / "out"
        output_dir.mkdir(mode=0o700)
        if not no_input:
            click.echo(f'`project_dest` must equal to "{target_path.name}"')

        # By default cookiecutter preserves all entered variables in
        # the user's home and tries to reuse it on subsequent cookiecutter
        # executions.
        #
        # Give cookiecutter a fake config so it would write its stuff
        # to the tempdir, which would then be removed.
        cookiecutter_config_path = Path(tempdir_path) / "cookiecutter_home"
        cookiecutter_config_path.mkdir(parents=True)
        cookiecutter_config = cookiecutter_config_path / "cookiecutterrc.yaml"
        cookiecutter_config.write_text(
            f"""
cookiecutters_dir: "{cookiecutter_config_path / 'cookiecutters'}"
replay_dir: "{cookiecutter_config_path / 'replay'}"
"""
        )

        extra_context.setdefault("project_dest", target_path.name)

        cookiecutter(
            str(template_path),
            no_input=no_input,
            extra_context=extra_context,
            output_dir=str(output_dir),
            config_file=str(cookiecutter_config),
        )

        # Say the `target_path` looks like `/some/path/to/myproject`.
        #
        # Cookiecutter puts the generated project files to
        # `output_path / "{{ cookiecutter.project_dest }}"`.
        #
        # We assume that `project_dest` equals the dirname of
        # the `target_path` (i.e. `myproject`).
        #
        # Later we need to move the generated files from
        # `output_path / "{{ cookiecutter.project_dest }}" / ...`
        # to `/some/path/to/myproject/...`.
        #
        # For that we need to ensure that cookiecutter did indeed
        # put the generated files to `output_path / 'myproject'`
        # and no extraneous files or dirs were generated.
        actual_items_in_tempdir = os.listdir(output_dir)
        expected_items_in_tempdir = [target_path.name]
        if actual_items_in_tempdir != expected_items_in_tempdir:
            raise RuntimeError(
                f"A project generated by cookiecutter has an unexpected "
                f"file structure.\n"
                f"Expected directory listing: {expected_items_in_tempdir}\n"
                f"Actual: {actual_items_in_tempdir}\n"
                f"\n"
                f"Does the TARGET_PROJECT_DIR name match "
                f"the cookiecutter's `project_dest` value?"
            )

        apply_generated_project(
            output_dir / target_path.name,
            target_path,
            template_meta=template_meta,
            scaraplate_yaml=scaraplate_yaml,
        )

        click.echo("Done!")


def get_scaraplate_yaml(template_path: Path) -> ScaraplateYaml:
    config = yaml.safe_load((template_path / "scaraplate.yaml").read_text())
    default_strategy = class_from_str(config["default_strategy"])
    if not issubclass(default_strategy, Strategy) or default_strategy == Strategy:
        raise RuntimeError(
            f"`{default_strategy}` is not a subclass of "
            f"`scaraplate.strategies.Strategy`"
        )

    strategies_mapping: Dict[str, Type[Strategy]] = {  # type: ignore
        str(path): class_from_str(ref)
        for path, ref in config["strategies_mapping"].items()
    }
    for cls in strategies_mapping.values():
        if not issubclass(cls, Strategy) or default_strategy == Strategy:
            raise RuntimeError(
                f"`{default_strategy}` is not a subclass of "
                f"`scaraplate.strategies.Strategy`"
            )
    return ScaraplateYaml(
        default_strategy=default_strategy, strategies_mapping=strategies_mapping
    )


def get_target_project_cookiecutter_context(target_path: Path) -> Dict[str, str]:
    setup_cfg = target_path / "setup.cfg"
    if not setup_cfg.exists():
        click.echo("setup.cfg doesn't exist, continuing with an empty context")
        return {}

    click.echo("setup.cfg exists, parsing...")
    section = "tool:cookiecutter_context"
    configparser = setup_cfg_parser_from_path(setup_cfg)
    context_configparser = dict(configparser).get(section)
    # ConfigParser section's pprint doesn't include contents.
    context = dict(context_configparser or {})
    if context:
        click.echo(f"Continuing with the following context:\n{pprint.pformat(context)}")
    else:
        click.echo(
            f"The [{section}] section of setup.cfg is empty, "
            f"continuing with an empty context"
        )
    return dict(context)


def apply_generated_project(
    generated_path: Path,
    target_path: Path,
    *,
    template_meta: TemplateMeta,
    scaraplate_yaml: ScaraplateYaml,
) -> None:
    generated_path = generated_path.resolve()

    for root, dirs, files in os.walk(generated_path):
        current_root_path = Path(root)
        path_from_template_root = current_root_path.relative_to(generated_path)
        target_root_path = target_path / path_from_template_root
        target_root_path.mkdir(parents=True, exist_ok=True, mode=0o755)

        for d in dirs:
            (target_root_path / d).mkdir(parents=True, exist_ok=True, mode=0o755)

        for f in files:
            file_path = current_root_path / f
            target_file_path = target_root_path / f

            strategy_cls = scaraplate_yaml.strategies_mapping.get(
                str(path_from_template_root / f), scaraplate_yaml.default_strategy
            )

            template_contents = io.BytesIO(file_path.read_bytes())
            if target_file_path.exists():
                target_contents: Optional[BinaryIO] = io.BytesIO(
                    target_file_path.read_bytes()
                )
            else:
                target_contents = None

            strategy = strategy_cls(
                target_contents=target_contents,
                template_contents=template_contents,
                template_meta=template_meta,
            )

            target_contents = strategy.apply()
            target_file_path.write_bytes(target_contents.read())

            # https://stackoverflow.com/a/5337329
            chmod = file_path.stat().st_mode & 0o777
            target_file_path.chmod(chmod)


def class_from_str(ref: str) -> Type[object]:
    module_s, cls_s = ref.rsplit(".", 1)
    module = importlib.import_module(module_s)
    return getattr(module, cls_s)
