from pathlib import Path

import pytest

import scaraplate.strategies
from scaraplate.config import ScaraplateYaml, StrategyNode, get_scaraplate_yaml
from scaraplate.cookiecutter import ScaraplateConf, SetupCfg
from scaraplate.gitremotes import GitHub


@pytest.mark.parametrize(
    "yaml_text, expected",
    [
        (
            """
default_strategy: scaraplate.strategies.Overwrite
strategies_mapping:
  Jenkinsfile: scaraplate.strategies.TemplateHash
  'some/nested/setup.py': scaraplate.strategies.TemplateHash
""",
            ScaraplateYaml(
                default_strategy=StrategyNode(
                    strategy=scaraplate.strategies.Overwrite, config={}
                ),
                strategies_mapping={
                    "Jenkinsfile": StrategyNode(
                        strategy=scaraplate.strategies.TemplateHash, config={}
                    ),
                    "some/nested/setup.py": StrategyNode(
                        strategy=scaraplate.strategies.TemplateHash, config={}
                    ),
                },
                git_remote_type=None,
                cookiecutter_context_type=ScaraplateConf,
            ),
        ),
        (
            """
default_strategy:
  strategy: scaraplate.strategies.Overwrite
  config:
    some_key: True
strategies_mapping:
  other_file.txt:
    strategy: scaraplate.strategies.IfMissing
    unrelated_key_but_okay: 1
  another_file.txt:
    strategy: scaraplate.strategies.SortedUniqueLines
    config:
      some_key: True
""",
            ScaraplateYaml(
                default_strategy=StrategyNode(
                    strategy=scaraplate.strategies.Overwrite, config={"some_key": True}
                ),
                strategies_mapping={
                    "other_file.txt": StrategyNode(
                        strategy=scaraplate.strategies.IfMissing, config={}
                    ),
                    "another_file.txt": StrategyNode(
                        strategy=scaraplate.strategies.SortedUniqueLines,
                        config={"some_key": True},
                    ),
                },
                git_remote_type=None,
                cookiecutter_context_type=ScaraplateConf,
            ),
        ),
        (
            """
git_remote_type: scaraplate.gitremotes.GitHub
default_strategy: scaraplate.strategies.Overwrite
strategies_mapping:
  Jenkinsfile: scaraplate.strategies.TemplateHash
""",
            ScaraplateYaml(
                default_strategy=StrategyNode(
                    strategy=scaraplate.strategies.Overwrite, config={}
                ),
                strategies_mapping={
                    "Jenkinsfile": StrategyNode(
                        strategy=scaraplate.strategies.TemplateHash, config={}
                    )
                },
                git_remote_type=GitHub,
                cookiecutter_context_type=ScaraplateConf,
            ),
        ),
        (
            """
cookiecutter_context_type: scaraplate.cookiecutter.SetupCfg
default_strategy: scaraplate.strategies.Overwrite
strategies_mapping:
  Jenkinsfile: scaraplate.strategies.TemplateHash
""",
            ScaraplateYaml(
                default_strategy=StrategyNode(
                    strategy=scaraplate.strategies.Overwrite, config={}
                ),
                strategies_mapping={
                    "Jenkinsfile": StrategyNode(
                        strategy=scaraplate.strategies.TemplateHash, config={}
                    )
                },
                git_remote_type=None,
                cookiecutter_context_type=SetupCfg,
            ),
        ),
    ],
)
def test_get_scaraplate_yaml_valid(tempdir_path: Path, yaml_text, expected) -> None:
    (tempdir_path / "scaraplate.yaml").write_text(yaml_text)
    scaraplate_yaml = get_scaraplate_yaml(tempdir_path)
    assert scaraplate_yaml == expected


@pytest.mark.parametrize(
    "cls",
    [
        "tempfile.TemporaryDirectory",
        "tempfile",
        "scaraplate.strategies.Strategy",
        '{"strategy": "tempfile.TemporaryDirectory"}',
        '{"strategy": 42}',
        '{"config": {}}',  # strategy is missing
        '{"strategy": "scaraplate.strategies.Overwrite", "config": 42}',
        "42",
    ],
)
@pytest.mark.parametrize("mutation_target", ["default_strategy", "strategies_mapping"])
def test_get_scaraplate_yaml_invalid_strategies(
    tempdir_path: Path, cls: str, mutation_target: str
) -> None:
    classes = dict(
        default_strategy="scaraplate.strategies.Overwrite",
        strategies_mapping="scaraplate.strategies.Overwrite",
    )
    classes[mutation_target] = cls

    yaml_text = f"""
default_strategy: {classes['default_strategy']}
strategies_mapping:
  Jenkinsfile: {classes['strategies_mapping']}
"""
    (tempdir_path / "scaraplate.yaml").write_text(yaml_text)
    with pytest.raises(ValueError):
        get_scaraplate_yaml(tempdir_path)


@pytest.mark.parametrize(
    "cls",
    [
        "tempfile.TemporaryDirectory",
        "tempfile",
        "scaraplate.gitremotes.GitRemote",
        "scaraplate.cookiecutter.ScaraplateConf",
        '{"strategy": "scaraplate.gitremotes.GitLab"}',
        "42",
    ],
)
def test_get_scaraplate_yaml_invalid_git_remotes(tempdir_path: Path, cls: str) -> None:
    yaml_text = f"""
git_remote_type: {cls}
default_strategy: scaraplate.strategies.Overwrite
strategies_mapping:
  Jenkinsfile: scaraplate.strategies.Overwrite
"""
    (tempdir_path / "scaraplate.yaml").write_text(yaml_text)
    with pytest.raises(ValueError):
        get_scaraplate_yaml(tempdir_path)


@pytest.mark.parametrize(
    "cls",
    [
        "tempfile.TemporaryDirectory",
        "tempfile",
        "scaraplate.gitremotes.GitHub",
        "scaraplate.cookiecutter.CookieCutterContext",
        '{"strategy": "scaraplate.cookiecutter.ScaraplateConf"}',
        "42",
    ],
)
def test_get_scaraplate_yaml_invalid_cookiecutter_context(
    tempdir_path: Path, cls: str
) -> None:
    yaml_text = f"""
cookiecutter_context_type: {cls}
default_strategy: scaraplate.strategies.Overwrite
strategies_mapping:
  Jenkinsfile: scaraplate.strategies.Overwrite
"""
    (tempdir_path / "scaraplate.yaml").write_text(yaml_text)
    with pytest.raises(ValueError):
        get_scaraplate_yaml(tempdir_path)
