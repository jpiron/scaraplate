import contextlib
import fnmatch
import io
import os
import pprint
import tempfile
from pathlib import Path
from typing import BinaryIO, Dict, Optional, Tuple, Union

import click
from cookiecutter.main import cookiecutter

from .config import ScaraplateYaml, StrategyNode, get_scaraplate_yaml
from .template import TemplateMeta, get_template_meta_from_git


__all__ = ("rollup",)


def rollup(
    template_dir: Union[Path, str], target_project_dir: Union[Path, str], no_input: bool
) -> None:
    template_path = Path(template_dir)
    target_path = Path(target_project_dir)

    scaraplate_yaml = get_scaraplate_yaml(template_path)
    template_meta = get_template_meta_from_git(
        template_path, git_remote_type=scaraplate_yaml.git_remote_type
    )

    target_path.mkdir(parents=True, exist_ok=True, mode=0o755)
    project_dest = get_project_dest(target_path)

    extra_context = get_target_project_cookiecutter_context(
        target_path, scaraplate_yaml
    )

    with tempfile.TemporaryDirectory() as tempdir_path:
        output_dir = Path(tempdir_path) / "out"
        output_dir.mkdir(mode=0o700)
        if not no_input:
            click.echo(f'`project_dest` must equal to "{project_dest}"')

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

        extra_context.setdefault("project_dest", project_dest)

        template_root_path, template_dir_name = get_template_root_and_dir(template_path)

        with with_cwd(template_root_path):
            # Cookiecutter preserves its template values to
            # .scaraplate.conf/setup.cfg (this is specified in the template).
            #
            # These values contain a `_template` key, which points to
            # the template just like it was passed to cookiecutter
            # (that is the first positional arg in the command below).
            #
            # In order to specify only the directory name of the template,
            # we change cwd (current working directory) and pass
            # the path to template as just a directory name, effectively
            # stripping off the path to the template in the local
            # filesystem.
            cookiecutter(
                template_dir_name,
                no_input=no_input,
                extra_context=extra_context,
                output_dir=str(output_dir.resolve()),
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
        expected_items_in_tempdir = [project_dest]
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
            output_dir / project_dest,
            target_path,
            template_meta=template_meta,
            scaraplate_yaml=scaraplate_yaml,
            extra_context=extra_context,
        )

        click.echo("Done!")


def get_project_dest(target_dir_path: Path) -> str:
    return target_dir_path.resolve().name


def get_template_root_and_dir(template_path: Path) -> Tuple[Path, str]:
    template_resolved_path = template_path.resolve()
    template_root_path = template_resolved_path.parents[0]
    template_dir_name = template_resolved_path.name
    return template_root_path, template_dir_name


def get_target_project_cookiecutter_context(
    target_path: Path, scaraplate_yaml: ScaraplateYaml
) -> Dict[str, str]:
    cookiecutter_context = scaraplate_yaml.cookiecutter_context_type(target_path)

    try:
        context = cookiecutter_context.read()
    except FileNotFoundError:
        click.echo(
            f"`{cookiecutter_context}` file doesn't exist, "
            f"continuing with an empty context..."
        )
        return {}
    else:
        if context:
            click.echo(
                f"Continuing with the following context from "
                f"the `{cookiecutter_context}` file:\n{pprint.pformat(context)}"
            )
        else:
            click.echo(
                f"No context found in the `{cookiecutter_context}` file, "
                f"continuing with an empty one..."
            )
        return dict(context)


def apply_generated_project(
    generated_path: Path,
    target_path: Path,
    *,
    template_meta: TemplateMeta,
    scaraplate_yaml: ScaraplateYaml,
    extra_context: Dict[str, str],
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

            strategy_node = get_strategy(scaraplate_yaml, path_from_template_root / f)

            template_contents = io.BytesIO(file_path.read_bytes())
            if target_file_path.exists():
                target_contents: Optional[BinaryIO] = io.BytesIO(
                    target_file_path.read_bytes()
                )
            else:
                target_contents = None

            strategy = strategy_node.strategy(
                target_contents=target_contents,
                template_contents=template_contents,
                template_meta=template_meta,
                config=strategy_node.config,
                extra_context=extra_context,
            )

            target_contents = strategy.apply()
            if target_contents is not None:
                target_file_path.write_bytes(target_contents.read())

                # https://stackoverflow.com/a/5337329
                chmod = file_path.stat().st_mode & 0o777
                target_file_path.chmod(chmod)


def get_strategy(scaraplate_yaml: ScaraplateYaml, path: Path) -> StrategyNode:
    for glob_pattern, strategy_node in sorted(
        scaraplate_yaml.strategies_mapping.items()
    ):
        if fnmatch.fnmatch(str(path), glob_pattern):
            return strategy_node
    return scaraplate_yaml.default_strategy


@contextlib.contextmanager
def with_cwd(cwd: Path):
    initial_cwd = os.getcwd()
    try:
        os.chdir(cwd)
        yield
    finally:
        os.chdir(initial_cwd)
