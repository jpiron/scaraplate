import abc
import io
from configparser import ConfigParser
from typing import BinaryIO, Optional

from .parsers import parser_to_pretty_output, pylintrc_parser
from .template import TemplateMeta


class Strategy(abc.ABC):
    def __init__(
        self,
        *,
        target_contents: Optional[BinaryIO],
        template_contents: BinaryIO,
        template_meta: TemplateMeta,
    ) -> None:
        self.target_contents = target_contents
        self.template_contents = template_contents
        self.template_meta = template_meta

    @abc.abstractmethod
    def apply(self) -> BinaryIO:
        pass


class Overwrite(Strategy):
    """A simple strategy which always overwrites the target files
    with the ones from the template.
    """

    def apply(self) -> BinaryIO:
        return self.template_contents


class TemplateHash(Strategy):
    """A strategy which appends to the target file a git commit hash of
    the template being applied; and the subsequent applications of
    the same template for this file are ignored.

    This strategy is useful when a file needs to be different from
    the template, yet it should be resynced on template updates.
    """

    line_comment_start = "#"

    def comment(self) -> str:
        comment_lines = [f"Generated by https://github.com/rambler-digital-solutions/scaraplate"]
        if self.template_meta.is_git_dirty:
            comment_lines.append(f"From (dirty) {self.template_meta.commit_url}")
        else:
            comment_lines.append(f"From {self.template_meta.commit_url}")

        return "".join(f"{self.line_comment_start} {line}\n" for line in comment_lines)

    def apply(self) -> BinaryIO:
        comment = self.comment().encode("ascii")
        if self.target_contents is not None:
            target_text = self.target_contents.read()
            if comment in target_text and not self.template_meta.is_git_dirty:
                # Hash hasn't changed -- keep the target.
                self.target_contents.seek(0)
                return self.target_contents

        out_bytes = self.template_contents.read()
        out_bytes += b"\n" + comment
        return io.BytesIO(out_bytes)


class PythonTemplateHash(TemplateHash):
    """TemplateHash strategy which takes Python linters into account:
    the long lines of the appended comment are suffixed with `# noqa`.
    """

    line_length = 87

    def comment(self) -> str:
        comment = super().comment()
        comment_lines = comment.split("\n")
        comment_lines = [self._maybe_add_noqa(line) for line in comment_lines]
        return "\n".join(comment_lines)

    def _maybe_add_noqa(self, line: str) -> str:
        if len(line) >= self.line_length:
            return f"{line}  # noqa"
        return line


class PylintrcMerge(Strategy):
    """A strategy which merges `.pylintrc` between a template
    and the target project.

    The resulting `.pylintrc` is the one from the template with
    the following modifications:
    - Comments are stripped
    - INI file is reformatted (whitespaces are cleaned, sections
      and values are sorted)
    - `ignored-*` keys of the `[TYPECHECK]` section are taken from
      the target `.pylintrc`.
    """

    def apply(self) -> BinaryIO:
        template_parser = pylintrc_parser(
            self.template_contents, source=".pylintrc.template"
        )

        if self.target_contents is not None:
            target_parser = pylintrc_parser(
                self.target_contents, source=".pylintrc.target"
            )
            self._maybe_preserve_key(
                template_parser, target_parser, "TYPECHECK", "ignored-modules"
            )
            self._maybe_preserve_key(
                template_parser, target_parser, "TYPECHECK", "ignored-classes"
            )

        return parser_to_pretty_output(template_parser)

    def _maybe_preserve_key(
        self,
        template_parser: ConfigParser,
        target_parser: ConfigParser,
        section: str,
        key: str,
    ) -> None:
        try:
            target = target_parser[section][key]
        except KeyError:
            # No such section/value in target -- keep the one that is
            # in the template.
            return
        else:
            template_parser[section][key] = target


# XXX setup.cfg
