"""
Apply value substitution (replacement) on tox strings.
"""
import os
import re
from configparser import SectionProxy
from typing import TYPE_CHECKING, Iterator, List, Optional, Sequence, Tuple, Union

from tox.config.loader.stringify import stringify
from tox.config.main import Config
from tox.config.sets import ConfigSet
from tox.execute.request import shell_cmd

if TYPE_CHECKING:
    from tox.config.loader.ini import IniLoader

CORE_PREFIX = "tox"
BASE_TEST_ENV = "testenv"

ARGS_GROUP = re.compile(r"(?<!\\):")


def replace(value: str, conf: Optional[Config], name: Optional[str], loader: "IniLoader") -> str:
    # perform all non-escaped replaces
    while True:
        start, end, match = _find_replace_part(value)
        if not match:
            break
        to_replace = value[start + 1 : end]
        replaced = _replace_match(conf, name, loader, to_replace)
        new_value = value[:start] + replaced + value[end + 1 :]
        if new_value == value:  # if we're not making progress stop (circular reference?)
            break
        value = new_value
    # remove escape sequences
    value = value.replace("\\{", "{")
    value = value.replace("\\}", "}")
    return value


def _find_replace_part(value: str) -> Tuple[int, int, bool]:
    start, end, match = 0, 0, False
    while end != -1:
        end = value.find("}", end)
        if end == -1:
            continue
        if end > 1 and value[end - 1] == "\\":  # ignore escaped
            end += 1
            continue
        while start != -1:
            start = value.rfind("{", 0, end)
            if start > 1 and value[start - 1] == "\\":  # ignore escaped
                continue
            match = True
            break
        if match:
            break
    return start, end, match


def _replace_match(
    conf: Optional[Config],
    current_env: Optional[str],
    loader: "IniLoader",
    value: str,
) -> str:
    of_type, *args = ARGS_GROUP.split(value)
    if of_type == "env":
        replace_value: Optional[str] = replace_env(args)
    elif of_type == "posargs":
        if conf is None:
            raise RuntimeError("no configuration yet")
        replace_value = replace_posargs(args, conf.pos_args)
    else:
        replace_value = replace_reference(conf, current_env, loader, value)
    if replace_value is None:
        return ""
    if not isinstance(replace_value, str):
        raise TypeError(f"could not replace {replace_value!r}")
    return replace_value


_REPLACE_REF = re.compile(
    rf"""
    (\[(?P<full_env>{BASE_TEST_ENV}(:(?P<env>[^]]+))?|(?P<section>\w+))\])? # env/section
    (?P<key>[a-zA-Z0-9_]+) # key
    (:(?P<default>.*))? # default value
""",
    re.VERBOSE,
)


def replace_reference(
    conf: Optional[Config],
    current_env: Optional[str],
    loader: "IniLoader",
    value: str,
) -> Optional[str]:
    match = _REPLACE_REF.match(value)
    if match:
        settings = match.groupdict()
        # if env set try only there, if section set try only there
        # otherwise try first in core, then in current env
        try:
            key = settings["key"]
            if settings["section"] is None and settings["full_env"] == BASE_TEST_ENV:
                settings["section"] = BASE_TEST_ENV
            for src in _config_value_sources(settings["env"], settings["section"], current_env, conf, loader):
                try:
                    if isinstance(src, SectionProxy):
                        return src[key]
                    value = src[key]
                    as_str, _ = stringify(value)
                    return as_str
                except KeyError:  # if this is missing maybe another src has it
                    continue
            default = settings["default"]
            if default is not None:
                return default
        except Exception as exc:  # noqa # ignore errors - but don't replace them
            pass
    # we should raise here - but need to implement escaping factor conditionals
    # raise ValueError(f"could not replace {value} from {current_env}")
    return f"{{{value}}}"


def _config_value_sources(
    env: Optional[str],
    section: Optional[str],
    current_env: Optional[str],
    conf: Optional[Config],
    loader: "IniLoader",
) -> Iterator[Union[SectionProxy, ConfigSet]]:
    # if we have an env name specified take only from there
    if env is not None:
        if conf is not None and env in conf:
            yield conf.get_env(env)
        return

    # if we have a section name specified take only from there
    if section is not None:
        # special handle the core section under name tox
        if section == CORE_PREFIX:
            if conf is not None:
                yield conf.core
            return
        value = loader.get_section(section)
        if value is not None:
            yield value
        return

    # otherwise try first from core conf, and fallback to our own environment
    if conf is not None:
        yield conf.core
        if current_env is not None:
            yield conf.get_env(current_env)


def replace_posargs(args: List[str], pos_args: Optional[Sequence[str]]) -> str:
    if pos_args is None:
        replace_value = args[0] if args else ""
    else:
        replace_value = shell_cmd(pos_args)
    return replace_value


def replace_env(args: List[str]) -> str:
    key = args[0]
    default = "" if len(args) == 1 else args[1]
    return os.environ.get(key, default)


__all__ = (
    "CORE_PREFIX",
    "BASE_TEST_ENV",
    "replace",
)