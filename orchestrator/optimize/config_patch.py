"""Materializing ``apply.kind: config_patch`` into a file a run can read.

THE SEAM THIS CLOSES. ``matrix._render_apply`` has always rendered a
``config_patch`` factor into ``row.apply["patches"]``, the design-matrix
schema has always carried the field, and ``campaign.schema.yaml`` has always
documented the kind alongside ``cli_flag`` and ``env_var``. Nothing read it.
``make_config_runner``'s closure appended ``cli_args`` and merged ``env`` and
stopped there, so every row of a design matrix whose factors used
``config_patch`` executed the target's BASELINE configuration while the
pre-registered matrix, ``runs.jsonl``, and the fitted response surface all
looked real. That is the silent-wrong-result class -- the one this whole kind's
oracle-first discipline (spec §2.1) exists to keep out -- and it was found the
hard way, at row 1 of 18, after a full ``build`` stage, by the run-time
manipulation predicate reporting three levels that had simply never been
applied.

WHY A PER-RUN COPY RATHER THAN AN IN-PLACE EDIT. The obvious implementation
edits the author's file, runs, and restores it. Two reasons not to: rows run
concurrently in principle (nothing in ``execute_design``'s contract forbids a
future parallel sweep, and ``parallel_arms`` already exists next door), so a
shared mutated file is a race; and a crash between edit and restore leaves the
author's repository holding one design corner's configuration, which is a
cross-row contamination channel that survives the campaign. A copy per run has
neither failure mode, and the realized copy is durable evidence of what the row
actually ran on.

WHY THE COMMAND IS REWRITTEN RATHER THAN GIVEN A NEW FLAG. There is no
vocabulary in the campaign schema for "and pass the patched file like this" --
the target's own ``run_command`` already names its config file, because that is
how a file-configured target is invoked. So the declared ``path`` is expected
to appear as an argument value in ``optimization.run_command``, and the
materialized copy's path is substituted for it. A ``path`` the command never
mentions has nothing to rewrite: the patch could not possibly take effect, so
that is a :class:`ConfigPatchError`, never a silent no-op. (The validator's
rule 17 catches the same condition at authoring time, before a campaign spends
anything; this is the runtime backstop for the case where the command is
assembled from something the validator could not see.)

TYPE FIDELITY IS THE POINT. A level of ``42949672960`` must land in the file
as an integer, ``true``/``false`` as the format's native boolean, a policy name
as a string. ``_render_apply`` passes the decoded level through untouched
(``matrix._decode_level`` deliberately preserves an int level as ``2`` rather
than ``2.0``), and this module writes it through ``json``/``yaml`` dumpers that
serialize the Python type natively -- never through ``str()``. A level arriving
as the string ``"42949672960"`` where the target expects an int is the same
silent-wrong-config failure in a new costume.

No model call happens here, and none may: this is inside the compiled epoch's
measurement path (CLAUDE.md's fifth invariant for the kind).
"""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any


class ConfigPatchError(RuntimeError):
    """A ``config_patch`` could not be realized as declared.

    Deliberately loud and deliberately fatal to the row. Every condition that
    raises it -- an absent file, an unsupported format, a pointer that names
    nothing, a ``path`` the command never mentions -- means the configuration
    that would have been measured is NOT the configuration the design matrix
    pre-registered. Degrading to "run it anyway" reproduces the exact defect
    this module exists to remove.
    """


_JSON_SUFFIXES = frozenset({".json"})
_YAML_SUFFIXES = frozenset({".yaml", ".yml"})


def _unescape_token(token: str) -> str:
    """RFC 6901 reference-token unescaping: ``~1`` -> ``/``, ``~0`` -> ``~``.

    Order matters and is fixed by the RFC: ``~1`` first, then ``~0``. Doing it
    the other way round turns the encoded ``~01`` into ``/`` instead of the
    literal ``~1`` it denotes.
    """
    return token.replace("~1", "/").replace("~0", "~")


def _split_pointer(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ConfigPatchError(
            f"pointer {pointer!r} is not a JSON pointer: a non-empty pointer "
            f"must start with '/' (RFC 6901). Write '/cache/policy', not "
            f"'cache/policy'.",
        )
    return [_unescape_token(tok) for tok in pointer[1:].split("/")]


def _descend(node: Any, token: str, pointer: str, so_far: list[str]) -> Any:
    """One step down ``node`` by ``token``, with a locating error message."""
    where = "/" + "/".join(so_far) if so_far else "(document root)"
    if isinstance(node, dict):
        if token not in node:
            raise ConfigPatchError(
                f"pointer {pointer!r} names nothing: {where} is a mapping with "
                f"no key {token!r} (has: "
                f"{', '.join(sorted(map(str, node))[:8]) or '<empty>'}). A "
                f"config_patch never CREATES structure -- the pointer must "
                f"address a field the target already reads, or the patch would "
                f"write a key nothing consults.",
            )
        return node[token]
    if isinstance(node, list):
        try:
            idx = int(token)
        except ValueError:
            raise ConfigPatchError(
                f"pointer {pointer!r} names nothing: {where} is an array, so "
                f"the next token must be a decimal index, got {token!r}.",
            ) from None
        if not (0 <= idx < len(node)):
            raise ConfigPatchError(
                f"pointer {pointer!r} names nothing: {where} is an array of "
                f"length {len(node)}, so index {idx} is out of range.",
            )
        return node[idx]
    raise ConfigPatchError(
        f"pointer {pointer!r} names nothing: {where} is a "
        f"{type(node).__name__}, which has no member {token!r} to descend into.",
    )


def read_pointer(doc: Any, pointer: str) -> Any:
    """The value ``pointer`` addresses in ``doc`` (RFC 6901).

    Exists so a caller can VERIFY a patch landed -- ``--smoke`` reads the
    materialized copy back through this rather than trusting that the write
    happened, because "the patch was requested" and "the patch is in the file
    the target will read" are exactly the two things the original defect
    confused.
    """
    node = doc
    so_far: list[str] = []
    for token in _split_pointer(pointer):
        node = _descend(node, token, pointer, so_far)
        so_far.append(token)
    return node


def apply_pointer(doc: Any, pointer: str, value: Any) -> Any:
    """A deep copy of ``doc`` with ``pointer``'s location set to ``value``.

    Pure: the input document is never mutated, so a caller holding the parsed
    baseline can render several rows from it. An empty pointer replaces the
    whole document, per RFC 6901's "the whole document" semantics.

    ``value`` is stored BY REFERENCE-FREE COPY and never stringified: the
    Python type the level decoded to is the type that reaches the dumper, and
    the dumper is what decides the on-disk representation for the format.
    """
    if pointer == "":
        return copy.deepcopy(value)
    tokens = _split_pointer(pointer)
    out = copy.deepcopy(doc)
    parent = out
    so_far: list[str] = []
    for token in tokens[:-1]:
        parent = _descend(parent, token, pointer, so_far)
        so_far.append(token)
    leaf = tokens[-1]
    # The leaf is validated by the same descent rules as every interior token:
    # a config_patch replaces a field the target already reads, so a leaf that
    # does not exist is a pointer error rather than an insertion.
    _descend(parent, leaf, pointer, so_far)
    if isinstance(parent, list):
        parent[int(leaf)] = copy.deepcopy(value)
    else:
        parent[leaf] = copy.deepcopy(value)
    return out


def load_config(path: Path) -> Any:
    """Parse a config file, dispatching on extension.

    Extension rather than sniffing, because the file has to be WRITTEN back in
    the same format and a guess that reads a JSON file as YAML (which succeeds,
    YAML being a JSON superset) would rewrite it as YAML and hand the target a
    file its own parser may reject.
    """
    suffix = path.suffix.lower()
    if suffix in _JSON_SUFFIXES:
        return json.loads(path.read_text())
    if suffix in _YAML_SUFFIXES:
        import yaml

        return yaml.safe_load(path.read_text())
    raise ConfigPatchError(
        f"config_patch cannot read {path}: unsupported extension "
        f"{suffix or '(none)'}. Supported: "
        f"{', '.join(sorted(_JSON_SUFFIXES | _YAML_SUFFIXES))}. A format Nous "
        f"cannot round-trip cannot be patched without risking a file the "
        f"target's own parser rejects.",
    )


def dump_config(doc: Any, path: Path) -> None:
    """Serialize ``doc`` to ``path`` in the format ``path``'s extension names.

    ``sort_keys=False`` on both dumpers: the target's config is the author's
    document and a reordered one is harder to diff against the original when
    a campaign is being debugged. Neither dumper stringifies scalars -- an int
    stays an int, a bool stays the format's native boolean.
    """
    suffix = path.suffix.lower()
    if suffix in _JSON_SUFFIXES:
        path.write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n")
        return
    if suffix in _YAML_SUFFIXES:
        import yaml

        path.write_text(yaml.safe_dump(doc, sort_keys=False, default_flow_style=False))
        return
    raise ConfigPatchError(
        f"config_patch cannot write {path}: unsupported extension "
        f"{suffix or '(none)'}.",
    )


def materialize_patches(
    patches: list[dict], *, cwd: Path, temp_dir: Path,
) -> list[dict]:
    """Write one patched copy per distinct ``path`` and describe what happened.

    Several factors may patch the SAME file at different pointers (a realistic
    campaign varying three keys of one engine config), so patches are grouped
    by ``path`` and every pointer for a file is applied to a single parsed
    document before it is written once. Patching the same file twice
    independently would have the second copy overwrite the first factor's
    change -- silently, and only for the factors that happened to share a file.

    Returns one entry per patch, in declaration order, each carrying the
    ``path``/``pointer``/``value`` that was requested plus the
    ``materialized_path`` the run will actually read. That list is what the row
    records as ``applied_patches``, next to ``applied_args`` and
    ``applied_env``: the audit trail says what was DONE, not merely what was
    asked for.
    """
    by_path: dict[str, list[dict]] = {}
    for patch in patches:
        raw_path = str(patch.get("path") or "")
        if not raw_path:
            raise ConfigPatchError(
                "config_patch has no 'path': there is no file to patch. Every "
                "config_patch apply spec needs path + pointer + value.",
            )
        by_path.setdefault(raw_path, []).append(patch)

    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    realized: list[dict] = []

    for raw_path, group in by_path.items():
        source = Path(raw_path)
        if not source.is_absolute():
            source = Path(cwd) / source
        if not source.is_file():
            # "does not exist" is wrong and confusing for a path that plainly
            # does exist as a DIRECTORY (or a broken symlink), so the two cases
            # get their own words. An author told "does not exist" about a
            # directory hunts for a typo in a name that is spelled correctly.
            if source.is_dir():
                what = "is a directory, not a file"
            elif source.is_symlink():
                what = "is a symlink that does not resolve to a file"
            elif source.exists():
                what = "is not a regular file"
            else:
                what = "does not exist"
            raise ConfigPatchError(
                f"config_patch path {raw_path!r} {what} (resolved to {source} "
                f"under {cwd}). The patch cannot be applied, so this row would "
                f"have measured the target's baseline while the design matrix "
                f"recorded the requested level. Note that the spelling must "
                f"match optimization.run_command LITERALLY -- './engine.json' "
                f"and 'engine.json' are not interchangeable, because the "
                f"substitution is textual over the assembled argv.",
            )
        doc = load_config(source)
        for patch in group:
            doc = apply_pointer(doc, str(patch.get("pointer", "")), patch.get("value"))

        # A fresh subdirectory per materialization, not a name derived from the
        # row: two rows patching the same file must never collide, and the
        # caller (a run, a smoke probe, a confirm replicate) does not always
        # have a unique index to key on. The basename is preserved because some
        # targets infer format or sibling-relative paths from the filename.
        dest_dir = temp_dir / uuid.uuid4().hex[:12]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / source.name
        dump_config(doc, dest)

        for patch in group:
            entry = {
                "path": raw_path,
                "pointer": str(patch.get("pointer", "")),
                "value": patch.get("value"),
                "materialized_path": str(dest),
            }
            # `factor_id` is carried through when the caller supplied it (it
            # comes from `matrix._render_apply`), because the caller keys the
            # realized record by factor so a manipulation predicate can address
            # `applied_patches.<FACTOR_ID>.value`. Optional rather than required:
            # `--smoke`'s verification re-materializes a single patch with no
            # factor attached, and this function's contract is about files, not
            # about the design.
            if patch.get("factor_id") is not None:
                entry["factor_id"] = patch["factor_id"]
            realized.append(entry)

    return realized


#: Characters that may precede a path inside one argv token. Anything else
#: means the "match" is really the tail of a LONGER path (``sub/engine.json``
#: contains ``engine.json`` after a ``/``) and must not be rewritten.
_PATH_BOUNDARY_CHARS = frozenset("=:,")


def _substitute_in_token(token: str, raw_path: str, dest: str) -> tuple[str, int]:
    """``token`` with each boundary-anchored occurrence of ``raw_path`` replaced.

    Returns ``(new_token, hits)``. A match counts only where ``raw_path`` starts
    the token or follows one of ``_PATH_BOUNDARY_CHARS`` AND ends the token --
    i.e. where it is the whole argument value, which is the only shape a config
    argument takes (``engine.json``, ``--config=engine.json``,
    ``--config:engine.json``).

    THE BOUNDARY IS NOT PEDANTRY. With a bare substring test, two factors
    patching ``engine.json`` and ``sub/engine.json`` collide: whichever is
    processed first consumes the other's token (``sub/engine.json`` contains
    ``engine.json``), and the second path then reports "does not appear anywhere
    in the assembled run command" for a command that plainly names it. Verified
    directly. Anchoring the match to an argument boundary makes the two
    independent, and pairs with the longest-first ordering in
    :func:`rewrite_command` so the more specific path is offered the token first.
    """
    hits = 0
    out: list[str] = []
    i = 0
    n = len(raw_path)
    while i < len(token):
        if token.startswith(raw_path, i) and i + n == len(token) and (
            i == 0 or token[i - 1] in _PATH_BOUNDARY_CHARS
        ):
            out.append(dest)
            i += n
            hits += 1
            continue
        out.append(token[i])
        i += 1
    return "".join(out), hits


def rewrite_command(cmd: list[str], realized: list[dict]) -> list[str]:
    """Point every occurrence of a patched file's ``path`` at its copy.

    Matches inside a token rather than requiring whole-token equality, because a
    target's config argument is written either way in practice --
    ``--config engine.json`` and ``--config=engine.json`` are both ordinary --
    and the second form has the path embedded in the token. The match is
    boundary-anchored (see :func:`_substitute_in_token`), so one factor's path
    cannot swallow another's.

    A ``path`` that appears in NO token raises: the command would have run
    against the author's unpatched file, which is precisely the silent-baseline
    defect. The message names both the path and the command so the author can
    see which of the two is wrong without re-deriving the assembled argv.

    EACH DISTINCT PATH IS SUBSTITUTED EXACTLY ONCE, LONGEST FIRST. ``realized``
    carries one entry per PATCH, and several factors patching different pointers
    of the same file (the realistic shape: three knobs of one engine config)
    share both a ``path`` and a ``materialized_path``. Substituting per entry
    rewrote the already-substituted token a second time -- the materialized path
    ends in the original basename, so ``engine.json`` is still a substring of it
    -- and produced a doubled, nonexistent path. Verified end-to-end: the run
    exited 1 with ``FileNotFoundError`` on
    ``.../patched_configs/<id>//.../patched_configs/<id>/engine.json``. Loud
    rather than silent, but still wrong, and only for the multi-factor
    single-file case that a two-factor smoke probe is the first thing to hit.
    Longest-first ordering is the same defence one level up: it offers the more
    specific of two nested paths its token before the shorter one sees it.
    """
    out = list(cmd)
    seen: set[str] = set()
    # Sorted by descending length so a nested path (`sub/engine.json`) is
    # offered the token before its own suffix (`engine.json`) can be tried
    # against it. Ties broken on the path itself for determinism.
    ordered = sorted(realized, key=lambda e: (-len(str(e["path"])), str(e["path"])))
    for entry in ordered:
        raw_path = str(entry["path"])
        dest = str(entry["materialized_path"])
        if raw_path in seen:
            continue
        seen.add(raw_path)
        hits = 0
        for i, token in enumerate(out):
            new_token, n = _substitute_in_token(token, raw_path, dest)
            if n:
                out[i] = new_token
                hits += n
        if hits == 0:
            raise ConfigPatchError(
                f"config_patch path {raw_path!r} does not appear as an argument "
                f"value anywhere in the assembled run command "
                f"({' '.join(cmd)}), so the patched copy at {dest} could not be "
                f"substituted in and the run would have used the target's "
                f"unpatched configuration. A config_patch factor's 'path' must "
                f"appear as a whole argument value in optimization.run_command "
                f"-- e.g. 'bench --config {raw_path} --json' or "
                f"'bench --config={raw_path}'.",
            )
    return out


def command_names_path(cmd: list[str], raw_path: str) -> bool:
    """Whether ``cmd`` names ``raw_path`` where :func:`rewrite_command` would rewrite it.

    The validator's rule 17 and the runtime must agree on what "the command names
    this file" MEANS, and the disagreement is not hypothetical: a plain ``in``
    substring test passes a campaign whose command names ``other/engine.json``
    for a factor declaring ``engine.json``, which the runtime then rejects. That
    is the same "validated clean, aborted later" gap rule 17 exists to close,
    reintroduced inside the check. So the predicate is exported from here, next
    to the substitution it has to match, rather than reimplemented at the call
    site.
    """
    return any(_substitute_in_token(tok, raw_path, "X")[1] for tok in cmd)
