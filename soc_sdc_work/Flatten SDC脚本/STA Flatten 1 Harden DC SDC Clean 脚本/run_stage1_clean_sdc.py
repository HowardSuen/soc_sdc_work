#!/usr/bin/env python3
"""
Convert a harden DC flattened SDC into a SoC-callable harden-internal SDC.

This implementation follows the v2.3.1 rule document:
  * command normalization is a stateful Tcl-like scanner
  * clock definitions are scanned before command classification
  * kept clock definitions are renamed with the harden instance prefix
  * removed / unsupported / modified details are emitted separately
  * set_units mismatch and structural command-boundary failures are fatal

The script intentionally uses only the Python standard library and stays
compatible with Python 3.6.
"""

from __future__ import print_function

import argparse
import csv
import os
import re
import sys
from collections import OrderedDict, defaultdict


PROCESS_VERSION = "v2.3.1"
TOOL_NAME = "run_stage1_clean_sdc.py"
STAGE_NAME = "STA Flatten 1 Harden DC SDC Clean"
AUTHOR = "Howard"


def author_banner_lines():
    return [
        "============================================================",
        "  Script  : %s" % TOOL_NAME,
        "  Stage   : %s" % STAGE_NAME,
        "  Author  : %s" % AUTHOR,
        "  Version : %s" % PROCESS_VERSION,
        "============================================================",
    ]


def print_author_banner():
    for line in author_banner_lines():
        print(line)


CREATE_CLOCK_COMMANDS = set(["create_clock"])
CREATE_GENERATED_CLOCK_COMMANDS = set(["create_generated_clock", "create_generate_clock"])
CLOCK_DEFINITION_COMMANDS = CREATE_CLOCK_COMMANDS | CREATE_GENERATED_CLOCK_COMMANDS

GET_OBJECT_COMMANDS = set([
    "get_ports",
    "get_pins",
    "get_cells",
    "get_cell",
    "get_nets",
    "get_net",
    "get_clocks",
])

OBJECT_GET_COMMANDS = set([
    "get_ports",
    "get_pins",
    "get_cells",
    "get_cell",
    "get_nets",
    "get_net",
])

GET_OPTIONS_WITH_VALUE = set([
    "-filter",
    "-fi",
    "-of_objects",
    "-of",
])

GET_OPTIONS_NO_VALUE = set([
    "-exact",
    "-quiet",
    "-regexp",
    "-hierarchical",
    "-hier",
    "-nocase",
])

OVERSIZE_GET_OPTIONS_NO_VALUE = set([
    "-exact",
    "-quiet",
])

CLOCK_DEF_OPTIONS_WITH_VALUE = set([
    "-comment",
    "-divide_by",
    "-duty_cycle",
    "-edges",
    "-edge_shift",
    "-master_clock",
    "-multiply_by",
    "-name",
    "-period",
    "-source",
    "-waveform",
])

CLOCK_DEF_OPTIONS_NO_VALUE = set([
    "-add",
    "-combinational",
    "-invert",
])

UNCONDITIONAL_REMOVE_COMMANDS = set([
    "set_input_delay",
    "set_output_delay",
    "set_clock_groups",
    "set_clock_uncertainty",
    "set_clock_transition",
    "set_propagated_clock",
    "set_ideal_network",
    "set_ideal_latency",
    "set_ideal_transition",
    "set_dont_touch_network",
    "set_wire_load_model",
    "set_wire_load_mode",
    "set_resistance",
    "set_capacitance",
    "set_annotated_delay",
    "set_annotated_transition",
    "set_annotated_check",
    "read_parasitics",
    "read_spef",
    "set_timing_derate",
    "set_dont_use",
    "group_path",
])

PORT_ELECTRICAL_COMMANDS = set([
    "set_drive",
    "set_driving_cell",
    "set_input_transition",
    "set_load",
    "set_fanout_load",
    "set_max_transition",
    "set_max_capacitance",
    "set_max_fanout",
])

DEFAULT_MODIFY_COMMANDS = set([
    "set_false_path",
    "set_multicycle_path",
    "set_max_delay",
    "set_min_delay",
    "set_disable_timing",
    "set_case_analysis",
    "set_data_check",
    "set_clock_gating_check",
    "set_min_pulse_width",
    "set_max_skew",
])

BOUNDARY_OWNED_COMMANDS = set([
    "set_false_path",
    "set_max_delay",
    "set_min_delay",
    "set_case_analysis",
])

BOUNDARY_REVIEW_MAPPING_COMMANDS = set([
    "set_multicycle_path",
])

SENSE_COMMANDS = set(["set_clock_sense", "set_sense"])

COMPLEX_TCL_COMMANDS = set([
    "proc",
    "foreach",
    "for",
    "while",
    "if",
    "switch",
    "eval",
    "uplevel",
    "regexp",
    "regsub",
])

COLLECTION_OPERATION_COMMANDS = set([
    "add_to_collection",
    "remove_from_collection",
    "filter_collection",
    "foreach_in_collection",
    "sizeof_collection",
    "get_object_name",
])

SAFE_COLLECTION_WRAPPER_COMMANDS = set([
    "list",
])

DANGEROUS_ALL_COLLECTIONS = set([
    "all_inputs",
    "all_outputs",
    "all_registers",
    "all_fanin",
    "all_fanout",
    "all_clocks",
])

SOURCE_SCOPE_COMMANDS = set([
    "source",
    "current_design",
    "current_instance",
])

DEFAULT_EXPECT_UNITS = "time=ns,capacitance=pF,resistance=ohm,voltage=V,current=mA"
DEFAULT_OVERSIZE_COMMAND_CHARS = 1000000


class Token(object):
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text


class TclCommand(object):
    def __init__(
        self,
        command_id,
        original_start_line,
        original_end_line,
        original_text,
        normalized_text,
        leading_comments,
        trailing_comment,
        parse_status="OK",
    ):
        self.command_id = command_id
        self.original_start_line = original_start_line
        self.original_end_line = original_end_line
        self.original_text = original_text
        self.normalized_text = normalized_text
        self.leading_comments = list(leading_comments or [])
        self.trailing_comment = trailing_comment or ""
        self.parse_status = parse_status

    def clone_with_text(self, normalized_text):
        return TclCommand(
            command_id=self.command_id,
            original_start_line=self.original_start_line,
            original_end_line=self.original_end_line,
            original_text=self.original_text,
            normalized_text=normalized_text,
            leading_comments=self.leading_comments,
            trailing_comment=self.trailing_comment,
            parse_status=self.parse_status,
        )


class NormalizationError(Exception):
    def __init__(self, start_line, end_line, state, nearby_text):
        Exception.__init__(self, "structural_command_boundary_failure")
        self.start_line = start_line
        self.end_line = end_line
        self.state = state
        self.nearby_text = nearby_text


class ClockDecision(object):
    def __init__(
        self,
        command_id,
        command_name,
        old_name,
        new_name,
        action,
        reason,
        target_kind,
        target_text,
        has_name_option,
    ):
        self.command_id = command_id
        self.command_name = command_name
        self.old_name = old_name
        self.new_name = new_name
        self.action = action
        self.reason = reason
        self.target_kind = target_kind
        self.target_text = target_text
        self.has_name_option = has_name_option


class Result(object):
    def __init__(self, command, category, reason, command_type, output_text=None, review_required=False):
        self.command = command
        self.category = category
        self.reason = reason
        self.command_type = command_type
        self.output_text = output_text
        self.review_required = review_required
        self.notes = []


class Violation(object):
    def __init__(self, command_id, line, vtype, token, action, command_text):
        self.command_id = command_id
        self.line = line
        self.vtype = vtype
        self.token = token
        self.action = action
        self.command_text = command_text


class TransformState(object):
    def __init__(self, config, pass1):
        self.config = config
        self.pass1 = pass1
        self.reasons = []
        self.review_items = []
        self.warnings = []
        self.unsupported_reason = None
        self.dangling_clock = None

    def add_reason(self, reason):
        if reason not in self.reasons:
            self.reasons.append(reason)

    def add_review(self, item):
        self.review_items.append(item)

    def add_warning(self, warning):
        self.warnings.append(warning)

    def set_unsupported(self, reason):
        if self.unsupported_reason is None:
            self.unsupported_reason = reason

    def set_dangling(self, clock_name):
        if self.dangling_clock is None:
            self.dangling_clock = clock_name


class Pass1Data(object):
    def __init__(self):
        self.clock_decisions = {}
        self.rename_map = OrderedDict()
        self.removed_clock_names = set()
        self.kept_clock_defs = []
        self.removed_clock_defs = []
        self.unsupported_clock_defs = []


class Config(object):
    def __init__(self, args):
        self.input_path = args.infile
        self.output_path = args.out
        self.removed_path = args.removed_out
        self.unsupported_path = args.unsupported_out
        self.modified_details_path = args.modified_details
        self.report_path = args.report
        self.inst = args.inst.rstrip("/")
        self.path_prefix = self.inst + "/"
        self.clock_prefix = sanitize_clock_prefix(self.inst)
        self.keep_generated_clock = args.keep_generated_clock
        self.keep_internal_create_clock = args.keep_internal_create_clock
        self.prefix_clock_name = args.prefix_clock_name
        self.allow_soc_clocks = set(args.allow_soc_clock or [])
        self.clock_mapping = read_clock_mapping(args.clock_mapping_file)
        self.map_port_case_analysis = args.map_port_case_analysis
        self.keep_kept_clock_source_latency = args.keep_kept_clock_source_latency
        self.strict = args.strict
        self.force_reprocess = args.force_reprocess
        self.detail_limit = args.detail_limit
        self.full_detail = args.full_detail
        self.expect_units = parse_expect_units(args.expect_units)
        self.oversize_command_chars = args.oversize_command_chars


def is_backslash_newline(text, index):
    if index >= len(text) or text[index] != "\\":
        return 0
    if index + 1 < len(text) and text[index + 1] == "\n":
        return 2
    if index + 2 < len(text) and text[index + 1] == "\r" and text[index + 2] == "\n":
        return 3
    return 0


def matching_brace_end(text, start):
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def matching_quote_end(text, start):
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == '"':
            return index
        index += 1
    return -1


def matching_bracket_end(text, start):
    depth = 0
    brace_depth = 0
    in_quote = False
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if brace_depth:
            if char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth -= 1
            index += 1
            continue
        if char == '"' and not brace_depth:
            in_quote = not in_quote
            index += 1
            continue
        if in_quote:
            index += 1
            continue
        if char == "{":
            brace_depth = 1
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def wrapped_by(text, open_char, close_char):
    text = text.strip()
    if len(text) < 2 or text[0] != open_char or text[-1] != close_char:
        return False
    if open_char == "{":
        return matching_brace_end(text, 0) == len(text) - 1
    if open_char == '"':
        return matching_quote_end(text, 0) == len(text) - 1
    return False


def unwrap_word(text):
    stripped = text.strip()
    if wrapped_by(stripped, "{", "}") or wrapped_by(stripped, '"', '"'):
        return stripped[1:-1]
    return stripped


def apply_replacements(text, replacements):
    if not replacements:
        return text
    replacements = sorted(replacements, key=lambda item: item[0])
    merged = []
    last_end = -1
    for start, end, value in replacements:
        if start < last_end:
            raise ValueError("overlapping replacements near offset %s" % start)
        merged.append((start, end, value))
        last_end = end
    out = []
    cursor = 0
    for start, end, value in merged:
        out.append(text[cursor:start])
        out.append(value)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def tokenize_tcl_words(text):
    tokens = []
    index = 0
    length = len(text)
    while index < length:
        if text[index].isspace():
            index += 1
            continue
        start = index
        while index < length:
            if text[index].isspace():
                break
            char = text[index]
            if char == "\\":
                index += 2
                continue
            if char == "{":
                end = matching_brace_end(text, index)
                index = end + 1 if end >= 0 else index + 1
                continue
            if char == '"':
                end = matching_quote_end(text, index)
                index = end + 1 if end >= 0 else index + 1
                continue
            if char == "[":
                end = matching_bracket_end(text, index)
                index = end + 1 if end >= 0 else index + 1
                continue
            index += 1
        tokens.append(Token(start, index, text[start:index]))
    return tokens


def command_name_of(text):
    tokens = tokenize_tcl_words(text)
    if not tokens:
        return ""
    return tokens[0].text


def command_name_fast(text):
    index = 0
    length = len(text)
    while index < length and text[index].isspace():
        index += 1
    start = index
    while index < length and not text[index].isspace():
        index += 1
    return text[start:index]


def sanitize_clock_prefix(inst):
    value = re.sub(r"[/.\[\]]+", "_", inst)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def make_new_clock_name(config, old_name):
    if not config.prefix_clock_name:
        return old_name
    old_name = unwrap_word(old_name)
    return "%s_%s" % (config.clock_prefix, old_name)


def starts_with_inst_path(obj, config):
    stripped = unwrap_word(obj)
    return stripped == config.inst or stripped.startswith(config.path_prefix)


def prefix_object_name(obj, config):
    stripped = obj.strip()
    if stripped == "":
        return obj
    if stripped.startswith("-"):
        return obj
    if stripped.startswith("$"):
        return obj
    if wrapped_by(stripped, "{", "}"):
        inner = stripped[1:-1]
        return "{" + prefix_word_list(inner, config) + "}"
    if wrapped_by(stripped, '"', '"'):
        inner = stripped[1:-1]
        return '"' + prefix_word_list(inner, config) + '"'
    if starts_with_inst_path(stripped, config):
        return obj
    return config.path_prefix + stripped


def prefix_word_list(inner, config):
    tokens = tokenize_tcl_words(inner)
    replacements = []
    for token in tokens:
        new_text = prefix_object_name(token.text, config)
        if new_text != token.text:
            replacements.append((token.start, token.end, new_text))
    return apply_replacements(inner, replacements)


def is_variable_reference(text):
    stripped = text.strip()
    return stripped.startswith("$") or "${" in stripped or re.search(r"(^|[^\\])\$[A-Za-z_]", stripped) is not None


def word_elements(text):
    stripped = text.strip()
    if wrapped_by(stripped, "{", "}") or wrapped_by(stripped, '"', '"'):
        return [token.text for token in tokenize_tcl_words(stripped[1:-1])]
    return [stripped] if stripped else []


def is_full_select_pattern(text):
    values = word_elements(text)
    if not values:
        return True
    for value in values:
        if unwrap_word(value) == "*":
            return True
    return False


def has_object_access(text):
    for name in GET_OBJECT_COMMANDS:
        if re.search(r"(^|[\s\[])" + re.escape(name) + r"($|[\s\]])", text):
            return True
    for name in DANGEROUS_ALL_COLLECTIONS:
        if re.search(r"(^|[\s\[])" + re.escape(name) + r"($|[\s\]])", text):
            return True
    return False


def contains_get_ports(text):
    return re.search(r"(^|[\s\[])get_ports($|[\s\]])", text) is not None


def contains_internal_object_access(text):
    for name in ["get_pins", "get_cells", "get_cell", "get_nets", "get_net"]:
        if re.search(r"(^|[\s\[])" + re.escape(name) + r"($|[\s\]])", text):
            return True
    return False


def contains_get_clocks(text):
    return re.search(r"(^|[\s\[])get_clocks($|[\s\]])", text) is not None


def contains_dangerous_all(text):
    for name in DANGEROUS_ALL_COLLECTIONS:
        if re.search(r"(^|[\s\[])" + re.escape(name) + r"($|[\s\]])", text):
            return name
    return None


def strip_full_line_comments(raw_text):
    """Drop whole-line comments while preserving line count."""
    output = []
    start = 0
    length = len(raw_text)
    while start < length:
        end = raw_text.find("\n", start)
        if end < 0:
            line_end = length
            next_start = length
            newline = ""
        else:
            line_end = end
            next_start = end + 1
            newline = "\n"

        index = start
        while index < line_end and raw_text[index] in " \t\r\f\v":
            index += 1
        if index < line_end and raw_text[index] == "#":
            output.append(newline)
        else:
            output.append(raw_text[start:next_start])
        start = next_start
    return "".join(output)


def normalize_commands(raw_text):
    commands = []
    leading_comments = []
    command_chars = []
    command_original_chars = []
    command_start_line = None
    command_end_line = None
    line_no = 1
    index = 0
    brace_depth = 0
    bracket_depth = 0
    in_quote = False
    command_id = 1

    def begin_command_if_needed(current_line):
        nonlocal_command = None
        return nonlocal_command

    def emit_command(end_line, trailing_comment=""):
        nonlocal command_id
        command_text = "".join(command_chars).strip()
        if len(command_text) > DEFAULT_OVERSIZE_COMMAND_CHARS:
            normalized = command_text
        else:
            normalized = " ".join(command_text.split())
        original = "".join(command_original_chars).strip()
        if normalized:
            start_line = command_start_line if command_start_line is not None else end_line
            commands.append(TclCommand(
                command_id=command_id,
                original_start_line=start_line,
                original_end_line=end_line,
                original_text=original,
                normalized_text=normalized,
                leading_comments=leading_comments[:],
                trailing_comment=trailing_comment,
            ))
            command_id += 1
        del leading_comments[:]
        del command_chars[:]
        del command_original_chars[:]
        return None

    while index < len(raw_text):
        char = raw_text[index]
        continuation_len = is_backslash_newline(raw_text, index)
        if continuation_len:
            if command_chars and command_chars[-1] != " ":
                command_chars.append(" ")
            command_original_chars.append(raw_text[index:index + continuation_len])
            index += continuation_len
            line_no += 1
            command_end_line = line_no
            continue

        at_top = brace_depth == 0 and bracket_depth == 0 and not in_quote

        if at_top and char == "#":
            current = "".join(command_chars)
            if current.strip() == "":
                end = raw_text.find("\n", index)
                if end < 0:
                    comment = raw_text[index:]
                    index = len(raw_text)
                else:
                    comment = raw_text[index:end]
                    index = end + 1
                    line_no += 1
                leading_comments.append(comment.rstrip("\r\n"))
                command_chars = []
                command_original_chars = []
                command_start_line = None
                command_end_line = None
                continue
            if current[-1:].isspace():
                end = raw_text.find("\n", index)
                if end < 0:
                    trailing = raw_text[index:]
                    end_line = line_no
                    index = len(raw_text)
                else:
                    trailing = raw_text[index:end]
                    end_line = line_no
                    index = end + 1
                    line_no += 1
                command_start_line = emit_command(end_line, trailing.rstrip("\r\n"))
                command_end_line = None
                continue

        if command_start_line is None and not char.isspace():
            command_start_line = line_no
        if command_start_line is not None:
            command_end_line = line_no

        if char == "\\":
            command_chars.append(char)
            command_original_chars.append(char)
            if index + 1 < len(raw_text):
                command_chars.append(raw_text[index + 1])
                command_original_chars.append(raw_text[index + 1])
                index += 2
            else:
                index += 1
            continue

        if brace_depth:
            command_chars.append(char)
            command_original_chars.append(char)
            if char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth -= 1
            if char == "\n":
                line_no += 1
            index += 1
            continue

        if char == '"' and not brace_depth:
            in_quote = not in_quote
            command_chars.append(char)
            command_original_chars.append(char)
            index += 1
            continue

        if not in_quote:
            if char == "{":
                brace_depth = 1
                command_chars.append(char)
                command_original_chars.append(char)
                index += 1
                continue
            if char == "[":
                bracket_depth += 1
                command_chars.append(char)
                command_original_chars.append(char)
                index += 1
                continue
            if char == "]":
                if bracket_depth > 0:
                    bracket_depth -= 1
                command_chars.append(char)
                command_original_chars.append(char)
                index += 1
                continue

        at_top = brace_depth == 0 and bracket_depth == 0 and not in_quote
        if at_top and char == ";":
            end_line = command_end_line if command_end_line is not None else line_no
            command_start_line = emit_command(end_line, "")
            command_end_line = None
            index += 1
            continue

        if at_top and char == "\n":
            end_line = command_end_line if command_end_line is not None else line_no
            command_start_line = emit_command(end_line, "")
            command_end_line = None
            line_no += 1
            index += 1
            continue

        command_chars.append(char)
        command_original_chars.append(char)
        if char == "\n":
            line_no += 1
        index += 1

    if brace_depth or bracket_depth or in_quote:
        nearby = "".join(command_original_chars[-300:])
        state = "brace_depth=%d, bracket_depth=%d, in_quote=%s" % (
            brace_depth,
            bracket_depth,
            "true" if in_quote else "false",
        )
        raise NormalizationError(command_start_line or line_no, line_no, state, nearby)

    if "".join(command_chars).strip():
        emit_line = command_end_line if command_end_line is not None else line_no
        emit_command(emit_line, "")

    return commands


def parse_clock_definition(command):
    tokens = tokenize_tcl_words(command.normalized_text)
    if not tokens:
        return None
    command_name = tokens[0].text
    if command_name not in CLOCK_DEFINITION_COMMANDS:
        return None

    old_name = ""
    has_name_option = False
    positional = []
    index = 1
    while index < len(tokens):
        token = tokens[index].text
        if token.startswith("-"):
            if token == "-name" and index + 1 < len(tokens):
                old_name = unwrap_word(tokens[index + 1].text)
                has_name_option = True
                index += 2
                continue
            if token in CLOCK_DEF_OPTIONS_WITH_VALUE and index + 1 < len(tokens):
                index += 2
                continue
            if token in CLOCK_DEF_OPTIONS_NO_VALUE:
                index += 1
                continue
            if index + 1 < len(tokens) and not tokens[index + 1].text.startswith("-"):
                index += 2
            else:
                index += 1
            continue
        positional.append(token)
        index += 1

    target_text = positional[-1] if positional else ""
    target_kind = classify_target_kind(target_text)
    if not old_name:
        old_name = infer_clock_name_from_target(target_text, command.command_id)
    return {
        "command_name": command_name,
        "old_name": old_name,
        "target_text": target_text,
        "target_kind": target_kind,
        "has_name_option": has_name_option,
    }


def classify_target_kind(target_text):
    stripped = target_text.strip()
    inner = bracket_command_inner(stripped)
    if inner is None:
        return "unknown"
    tokens = tokenize_tcl_words(inner)
    if not tokens:
        return "unknown"
    cmd = tokens[0].text
    if cmd == "get_ports":
        return "port"
    if cmd in set(["get_pins", "get_cells", "get_cell", "get_nets", "get_net"]):
        return "internal"
    if cmd == "get_clocks":
        return "clock"
    return "unknown"


def infer_clock_name_from_target(target_text, command_id):
    if not target_text:
        return "virtual_clock_%06d" % command_id
    inner = bracket_command_inner(target_text.strip())
    if inner is not None:
        tokens = tokenize_tcl_words(inner)
        if len(tokens) >= 2:
            for token in tokens[1:]:
                if token.text.startswith("-"):
                    continue
                values = word_elements(token.text)
                if values:
                    return unwrap_word(values[0])
    return "clock_%06d" % command_id


def bracket_command_inner(text):
    stripped = text.strip()
    if len(stripped) < 2 or stripped[0] != "[" or stripped[-1] != "]":
        return None
    if matching_bracket_end(stripped, 0) != len(stripped) - 1:
        return None
    return stripped[1:-1]


def run_pass1(commands, config):
    data = Pass1Data()
    for command in commands:
        parsed = parse_clock_definition(command)
        if parsed is None:
            continue

        command_name = parsed["command_name"]
        old_name = parsed["old_name"]
        target_kind = parsed["target_kind"]
        action = "keep"
        reason = "clock_definition_kept"

        if command_name in CREATE_CLOCK_COMMANDS and target_kind == "port":
            action = "remove"
            reason = "create_clock_on_block_port"
        elif command_name in CREATE_CLOCK_COMMANDS and not config.keep_internal_create_clock:
            action = "remove"
            reason = "drop_internal_create_clock"
        elif command_name in CREATE_GENERATED_CLOCK_COMMANDS and not config.keep_generated_clock:
            action = "remove"
            reason = "drop_generated_clock"
        elif command_name in CREATE_CLOCK_COMMANDS and target_kind == "unknown" and not parsed["target_text"]:
            action = "keep"
            reason = "virtual_create_clock_kept"
        elif target_kind == "unknown":
            action = "unsupported"
            reason = "unsupported_clock_definition_target"

        new_name = make_new_clock_name(config, old_name) if action == "keep" else ""
        decision = ClockDecision(
            command_id=command.command_id,
            command_name=command_name,
            old_name=old_name,
            new_name=new_name,
            action=action,
            reason=reason,
            target_kind=target_kind,
            target_text=parsed["target_text"],
            has_name_option=parsed["has_name_option"],
        )
        data.clock_decisions[command.command_id] = decision

        if action == "keep":
            data.rename_map[old_name] = new_name
            data.kept_clock_defs.append(decision)
        elif action == "remove":
            if old_name:
                data.removed_clock_names.add(old_name)
            data.removed_clock_defs.append(decision)
        else:
            if old_name:
                data.removed_clock_names.add(old_name)
            data.unsupported_clock_defs.append(decision)

    return data


def transform_text(text, state):
    transformed = transform_bracket_commands(text, state)
    return transformed


def transform_oversize_text(text, state):
    if "get_clocks" in text:
        state.set_unsupported("oversize_get_clocks_requires_deep_mapping")
        return text

    output = []
    index = 0
    while index < len(text):
        start = text.find("[", index)
        if start < 0:
            output.append(text[index:])
            break
        output.append(text[index:start])
        end = matching_bracket_end(text, start)
        if end < 0:
            state.set_unsupported("oversize_unbalanced_bracket")
            output.append(text[start:])
            break

        inner = text[start + 1:end]
        mapped_inner = transform_oversize_bracket_inner(inner, state)
        output.append("[")
        output.append(mapped_inner)
        output.append("]")
        index = end + 1
        if state.unsupported_reason:
            output.append(text[index:])
            break
    return "".join(output)


def transform_oversize_bracket_inner(inner, state):
    tokens = tokenize_tcl_words(inner)
    if not tokens:
        return inner
    cmd = tokens[0].text
    if cmd in set(["get_ports", "get_pins", "get_cells", "get_cell", "get_nets", "get_net"]):
        return transform_oversize_get_command(tokens, inner, state)
    if cmd in SAFE_COLLECTION_WRAPPER_COMMANDS:
        state.add_reason("safe_collection_wrapper_mapped")
        return transform_oversize_text(inner, state)
    if has_object_access(inner) or contains_dangerous_all(inner):
        state.set_unsupported("oversize_nested_collection_requires_deep_mapping")
    return inner


def transform_oversize_get_command(tokens, command_text, state):
    cmd = tokens[0].text
    replacements = []
    object_token_count = 0

    if cmd == "get_ports":
        replacements.append((tokens[0].start, tokens[0].end, "get_pins"))

    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token.text in OVERSIZE_GET_OPTIONS_NO_VALUE:
            index += 1
            continue
        if token.text.startswith("-"):
            state.set_unsupported("oversize_get_option_requires_deep_mapping:%s" % token.text)
            return command_text

        object_token_count += 1
        if is_full_select_pattern(token.text):
            state.set_unsupported("oversize_global_or_empty_object_pattern")
            return command_text
        if is_variable_reference(token.text):
            state.set_unsupported("oversize_variable_object_reference")
            return command_text

        mapped = prefix_object_name(token.text, state.config)
        if mapped != token.text:
            replacements.append((token.start, token.end, mapped))
            if cmd == "get_ports":
                state.add_reason("get_ports_mapped_to_get_pins")
            else:
                state.add_reason("%s_mapped" % cmd)
        index += 1

    if object_token_count == 0:
        state.set_unsupported("oversize_bare_get_command:%s" % cmd)
        return command_text
    return apply_replacements(command_text, replacements)


def transform_bracket_commands(text, state):
    output = []
    index = 0
    brace_depth = 0
    in_quote = False
    while index < len(text):
        char = text[index]
        if char == "\\":
            output.append(text[index:index + 2])
            index += 2
            continue
        if brace_depth:
            output.append(char)
            if char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth -= 1
            index += 1
            continue
        if char == '"' and not brace_depth:
            in_quote = not in_quote
            output.append(char)
            index += 1
            continue
        if in_quote:
            output.append(char)
            index += 1
            continue
        if char == "{":
            brace_depth = 1
            output.append(char)
            index += 1
            continue
        if char != "[":
            output.append(char)
            index += 1
            continue

        end = matching_bracket_end(text, index)
        if end < 0:
            state.set_unsupported("unbalanced_nested_bracket")
            output.append(char)
            index += 1
            continue
        inner = text[index + 1:end]
        inner_transformed = transform_bracket_commands(inner, state)
        tokens = tokenize_tcl_words(inner_transformed)
        if tokens:
            cmd = tokens[0].text
            if cmd in GET_OBJECT_COMMANDS:
                inner_transformed = transform_get_command(inner_transformed, state)
            elif cmd in SAFE_COLLECTION_WRAPPER_COMMANDS:
                pass
            elif cmd in DANGEROUS_ALL_COLLECTIONS:
                state.set_unsupported("dangerous_global_collection")
            elif has_object_access(inner_transformed):
                state.set_unsupported("unsupported_nested_collection")
        output.append("[")
        output.append(inner_transformed)
        output.append("]")
        index = end + 1
    return "".join(output)


def transform_get_command(command_text, state):
    tokens = tokenize_tcl_words(command_text)
    if not tokens:
        return command_text
    cmd = tokens[0].text
    if cmd == "get_ports":
        return transform_get_ports(tokens, command_text, state)
    if cmd in set(["get_pins", "get_cells", "get_cell", "get_nets", "get_net"]):
        return transform_get_object(tokens, command_text, state)
    if cmd == "get_clocks":
        return transform_get_clocks(tokens, command_text, state)
    return command_text


def transform_get_ports(tokens, command_text, state):
    replacements = [(tokens[0].start, tokens[0].end, "get_pins")]
    object_token_count = 0
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token.text.startswith("-"):
            option = token.text
            index += 1
            if option in GET_OPTIONS_WITH_VALUE and index < len(tokens):
                if option in set(["-filter", "-fi"]) and not has_object_access(tokens[index].text):
                    state.set_unsupported("get_ports_filter_without_explicit_pattern")
                index += 1
            continue
        object_token_count += 1
        if is_full_select_pattern(token.text):
            state.set_unsupported("dangerous_get_ports_global")
        elif is_variable_reference(token.text):
            state.set_unsupported("variable_object_reference")
        else:
            mapped = prefix_object_name(token.text, state.config)
            if mapped != token.text:
                replacements.append((token.start, token.end, mapped))
                state.add_reason("get_ports_mapped_to_get_pins")
        index += 1
    if object_token_count == 0:
        state.set_unsupported("dangerous_get_ports_bare")
    return apply_replacements(command_text, replacements)


def transform_get_object(tokens, command_text, state):
    cmd = tokens[0].text
    replacements = []
    object_token_count = 0
    has_hier = False
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token.text in set(["-hierarchical", "-hier"]):
            has_hier = True
            index += 1
            continue
        if token.text.startswith("-"):
            option = token.text
            index += 1
            if option in GET_OPTIONS_WITH_VALUE and index < len(tokens):
                index += 1
            continue
        object_token_count += 1
        if is_variable_reference(token.text):
            state.set_unsupported("variable_object_reference")
        elif cmd in set(["get_cells", "get_cell"]) and has_hier and is_full_select_pattern(token.text):
            state.set_unsupported("unsafe_get_cells_hierarchical")
        else:
            mapped = prefix_object_name(token.text, state.config)
            if mapped != token.text:
                replacements.append((token.start, token.end, mapped))
                state.add_reason("%s_mapped" % cmd)
                if cmd in set(["get_cells", "get_cell"]) and has_hier:
                    state.add_review("get_cells -hierarchical pattern was instance-prefixed: %s" % token.text)
        index += 1
    if cmd in set(["get_cells", "get_cell"]) and has_hier and object_token_count == 0:
        state.set_unsupported("unsafe_get_cells_hierarchical")
    return apply_replacements(command_text, replacements)


def transform_get_clocks(tokens, command_text, state):
    replacements = []
    clock_token_count = 0
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token.text.startswith("-"):
            option = token.text
            index += 1
            if option in GET_OPTIONS_WITH_VALUE and index < len(tokens):
                index += 1
            continue
        clock_token_count += 1
        new_text = transform_clock_selector(token.text, state)
        if new_text != token.text:
            replacements.append((token.start, token.end, new_text))
        index += 1
    if clock_token_count == 0:
        state.add_warning("get_clocks_without_explicit_clock_name")
    return apply_replacements(command_text, replacements)


def transform_clock_selector(text, state):
    stripped = text.strip()
    if is_variable_reference(stripped):
        state.set_unsupported("variable_clock_reference")
        return text
    if is_full_select_pattern(stripped):
        state.set_unsupported("dangerous_get_clocks_global")
        return text
    if wrapped_by(stripped, "{", "}"):
        return "{" + transform_clock_list(stripped[1:-1], state) + "}"
    if wrapped_by(stripped, '"', '"'):
        return '"' + transform_clock_list(stripped[1:-1], state) + '"'
    return transform_one_clock_name(stripped, state)


def transform_clock_list(inner, state):
    tokens = tokenize_tcl_words(inner)
    replacements = []
    for token in tokens:
        new_text = transform_one_clock_name(unwrap_word(token.text), state)
        if new_text != token.text:
            replacements.append((token.start, token.end, new_text))
    return apply_replacements(inner, replacements)


def transform_one_clock_name(clock_name, state):
    if not clock_name:
        return clock_name
    if clock_name in state.pass1.rename_map:
        state.add_reason("clock_reference_renamed")
        return state.pass1.rename_map[clock_name]
    if clock_name in state.config.clock_mapping:
        state.add_reason("clock_reference_mapped_to_soc")
        return state.config.clock_mapping[clock_name]
    if clock_name in state.config.allow_soc_clocks:
        state.add_warning("clock reference allowed by allowlist: %s" % clock_name)
        return clock_name
    if clock_name in state.pass1.removed_clock_names:
        state.set_dangling(clock_name)
        return clock_name
    state.add_warning("clock reference not defined by this script, assumed SoC-provided: %s" % clock_name)
    return clock_name


def insert_or_replace_clock_name(command_text, decision):
    tokens = tokenize_tcl_words(command_text)
    replacements = []
    index = 1
    while index < len(tokens) - 1:
        if tokens[index].text == "-name":
            replacements.append((tokens[index + 1].start, tokens[index + 1].end, decision.new_name))
            return apply_replacements(command_text, replacements)
        index += 1
    if len(tokens) >= 1:
        insert_pos = tokens[0].end
        return command_text[:insert_pos] + " -name " + decision.new_name + command_text[insert_pos:]
    return command_text


def classify_command(command, config, pass1, unit_state):
    text = command.normalized_text
    cmd = command_name_fast(text)
    if not cmd:
        return Result(command, "KEEP", "empty", "empty", output_text="")

    if len(text) > config.oversize_command_chars:
        return classify_oversize_command(command, config, pass1, cmd)

    tokens = tokenize_tcl_words(text)

    if cmd in CLOCK_DEFINITION_COMMANDS:
        return classify_clock_definition(command, config, pass1)

    if cmd == "set_units":
        return classify_set_units(command, config, unit_state)

    dangerous = contains_dangerous_all(text)
    if dangerous and cmd not in UNCONDITIONAL_REMOVE_COMMANDS:
        return Result(command, "UNSUPPORTED", "dangerous_global_collection:%s" % dangerous, cmd, review_required=True)

    if cmd in SOURCE_SCOPE_COMMANDS:
        return Result(command, "UNSUPPORTED", "source_or_scope_command", cmd, review_required=True)

    if cmd in COMPLEX_TCL_COMMANDS:
        if has_object_access(text):
            return Result(command, "UNSUPPORTED", "complex_tcl_with_object_access", cmd, review_required=True)
        result = Result(command, "KEEP", "pure_control_tcl_without_object_access", cmd, output_text=text)
        result.notes.append("Warning: pure control Tcl was kept because it contains no object access.")
        return result

    if cmd in COLLECTION_OPERATION_COMMANDS:
        return Result(command, "UNSUPPORTED", "collection_operation", cmd, review_required=True)

    if cmd == "set":
        return classify_set_command(command)

    if cmd in UNCONDITIONAL_REMOVE_COMMANDS:
        if cmd == "set_clock_latency" and should_keep_source_latency(command, config, pass1):
            return classify_modify_command(command, config, pass1, "kept_clock_source_latency")
        result = Result(command, "REMOVE", default_remove_reason(cmd), cmd)
        if cmd == "set_clock_latency" and "-source" in [tok.text for tok in tokens]:
            result.notes.append("Dropped source latency. Use --keep-kept-clock-source-latency only for reviewed kept internal clocks.")
        return result

    if cmd in PORT_ELECTRICAL_COMMANDS:
        if contains_get_ports(text):
            return Result(command, "REMOVE", "port_electrical_assumption_on_get_ports", cmd)
        return Result(command, "UNSUPPORTED", "port_electrical_command_not_on_get_ports", cmd, review_required=True)

    if cmd in set(["set_max_delay", "set_min_delay"]) and contains_get_ports(text):
        mapped_delay = map_boundary_delay(command, config, pass1)
        if mapped_delay is not None:
            return mapped_delay

    if cmd in BOUNDARY_OWNED_COMMANDS and contains_get_ports(text):
        result = Result(command, "REMOVE", default_boundary_remove_reason(cmd), cmd, review_required=True)
        result.notes.append(
            "Boundary get_ports constraint removed from cleaned harden SDC; hand off to scenario pre-setup, 10/20/30, or SoC-level review as appropriate."
        )
        return result

    if cmd in DEFAULT_MODIFY_COMMANDS:
        if config.strict and cmd in BOUNDARY_OWNED_COMMANDS and contains_get_ports(text):
            result = Result(command, "REMOVE", "strict_boundary_port_exception_removed", cmd, review_required=True)
            result.notes.append("Strict mode removed a boundary-port exception; review SoC-level intent.")
            return result
        return classify_modify_command(command, config, pass1, "mapped_internal_constraint")

    if cmd in SENSE_COMMANDS:
        return classify_sense_command(command, config, pass1)

    return Result(command, "UNSUPPORTED", "unclassified_command", cmd, review_required=True)


def classify_oversize_command(command, config, pass1, cmd):
    text = command.normalized_text

    if cmd in CLOCK_DEFINITION_COMMANDS:
        return Result(command, "UNSUPPORTED", "oversize_clock_definition", cmd, review_required=True)

    dangerous = contains_dangerous_all(text)
    if dangerous and cmd not in UNCONDITIONAL_REMOVE_COMMANDS:
        return Result(command, "UNSUPPORTED", "oversize_dangerous_global_collection:%s" % dangerous, cmd, review_required=True)

    if cmd in SOURCE_SCOPE_COMMANDS:
        return Result(command, "UNSUPPORTED", "source_or_scope_command", cmd, review_required=True)

    if cmd in COMPLEX_TCL_COMMANDS or cmd in COLLECTION_OPERATION_COMMANDS:
        return Result(command, "UNSUPPORTED", "oversize_complex_or_collection_command", cmd, review_required=True)

    if cmd in UNCONDITIONAL_REMOVE_COMMANDS:
        return Result(command, "REMOVE", default_remove_reason(cmd), cmd)

    if cmd in PORT_ELECTRICAL_COMMANDS:
        if contains_get_ports(text):
            return Result(command, "REMOVE", "port_electrical_assumption_on_get_ports", cmd)
        return Result(command, "UNSUPPORTED", "oversize_port_electrical_command_not_on_get_ports", cmd, review_required=True)

    if cmd in set(["set_max_delay", "set_min_delay"]) and contains_get_ports(text):
        return classify_oversize_modify_command(command, config, pass1, cmd)

    if cmd in BOUNDARY_OWNED_COMMANDS and contains_get_ports(text):
        result = Result(command, "REMOVE", default_boundary_remove_reason(cmd), cmd, review_required=True)
        result.notes.append(
            "Boundary get_ports constraint removed from cleaned harden SDC; hand off to scenario pre-setup, 10/20/30, or SoC-level review as appropriate."
        )
        return result

    if cmd in DEFAULT_MODIFY_COMMANDS or cmd in SENSE_COMMANDS:
        return classify_oversize_modify_command(command, config, pass1, cmd)

    return Result(command, "UNSUPPORTED", "oversize_unclassified_command", cmd, review_required=True)


def classify_oversize_modify_command(command, config, pass1, cmd):
    state = TransformState(config, pass1)
    mapped = transform_oversize_text(command.normalized_text, state)
    if state.unsupported_reason:
        result = Result(command, "UNSUPPORTED", state.unsupported_reason, cmd, review_required=True)
        result.notes.append("Oversize command skipped deep mapping to avoid excessive runtime.")
        return result
    category = "MODIFY" if mapped != command.normalized_text or state.reasons else "KEEP"
    reason_parts = list(state.reasons)
    reason_parts.append("oversize_shallow_mapped")
    result = Result(command, category, ", ".join(reason_parts), cmd, output_text=mapped, review_required=True)
    result.notes.extend(state.warnings)
    result.notes.extend(state.review_items)
    result.notes.append(
        "Oversize command used shallow object mapping only; review mapped endpoints before STA signoff."
    )
    return result


def classify_clock_definition(command, config, pass1):
    decision = pass1.clock_decisions.get(command.command_id)
    if decision is None:
        return Result(command, "UNSUPPORTED", "clock_definition_not_scanned", command_name_of(command.normalized_text), review_required=True)
    if decision.action == "remove":
        return Result(command, "REMOVE", decision.reason, decision.command_name)
    if decision.action == "unsupported":
        return Result(command, "UNSUPPORTED", decision.reason, decision.command_name, review_required=True)
    state = TransformState(config, pass1)
    mapped = transform_text(command.normalized_text, state)
    mapped = insert_or_replace_clock_name(mapped, decision)
    state.add_reason("clock_name_renamed")
    if state.unsupported_reason:
        return Result(command, "UNSUPPORTED", state.unsupported_reason, decision.command_name, review_required=True)
    if state.dangling_clock:
        category = "ERROR" if config.strict else "REMOVE"
        return Result(command, category, "dangling_clock_reference_related:%s" % state.dangling_clock, decision.command_name, review_required=True)
    result = Result(command, "MODIFY", ", ".join(state.reasons) or "clock_definition_mapped", decision.command_name, output_text=mapped)
    result.notes.extend(state.warnings)
    result.notes.extend(state.review_items)
    return result


def classify_set_units(command, config, unit_state):
    tokens = tokenize_tcl_words(command.normalized_text)
    seen_units = {}
    index = 1
    while index < len(tokens):
        option = tokens[index].text
        if not option.startswith("-"):
            index += 1
            continue
        key = option[1:]
        if index + 1 >= len(tokens):
            unit_state["errors"].append((command, "set_units_missing_value", option))
            return Result(command, "ERROR", "set_units_missing_value:%s" % option, "set_units", review_required=True)
        value = unwrap_word(tokens[index + 1].text)
        seen_units[key] = value
        expected = config.expect_units.get(key)
        if expected is not None and value != expected:
            unit_state["errors"].append((command, "set_units_mismatch", "%s=%s expected %s" % (key, value, expected)))
            return Result(command, "ERROR", "set_units_mismatch:%s=%s_expected_%s" % (key, value, expected), "set_units", review_required=True)
        index += 2
    unit_state["seen"].append((command, seen_units))
    return Result(command, "REMOVE", "set_units_checked_and_removed", "set_units")


def classify_set_command(command):
    text = command.normalized_text
    if has_object_access(text):
        return Result(command, "UNSUPPORTED", "set_variable_with_object_access", "set", review_required=True)
    return Result(command, "KEEP", "pure_variable_assignment", "set", output_text=text)


def classify_modify_command(command, config, pass1, reason):
    state = TransformState(config, pass1)
    mapped = transform_text(command.normalized_text, state)
    if state.unsupported_reason:
        return Result(command, "UNSUPPORTED", state.unsupported_reason, command_name_of(command.normalized_text), review_required=True)
    if state.dangling_clock:
        category = "ERROR" if config.strict else "REMOVE"
        return Result(command, category, "dangling_clock_reference_related:%s" % state.dangling_clock, command_name_of(command.normalized_text), review_required=True)
    category = "MODIFY" if mapped != command.normalized_text or state.reasons else "KEEP"
    result = Result(command, category, ", ".join(state.reasons) or reason, command_name_of(command.normalized_text), output_text=mapped)
    result.notes.extend(state.warnings)
    result.notes.extend(state.review_items)
    if state.review_items:
        result.review_required = True
    if command_involves_boundary_port_exception(command_name_of(command.normalized_text), command.normalized_text):
        result.review_required = True
        result.notes.append("Boundary port exception was mapped get_ports -> get_pins; timing semantics must be reviewed.")
    return result


def map_boundary_delay(command, config, pass1):
    text = command.normalized_text
    tokens = tokenize_tcl_words(text)
    endpoint_options = {}
    index = 1
    while index < len(tokens):
        option = tokens[index].text
        if option in set(["-from", "-to"]):
            if index + 1 >= len(tokens):
                return None
            endpoint_options[option] = {
                "option": tokens[index],
                "value": tokens[index + 1],
            }
            index += 2
            continue
        if option.startswith("-"):
            index += 2 if index + 1 < len(tokens) and not tokens[index + 1].text.startswith("-") else 1
            continue
        index += 1

    if "-from" not in endpoint_options or "-to" not in endpoint_options:
        return None

    from_value = endpoint_options["-from"]["value"].text
    to_value = endpoint_options["-to"]["value"].text
    from_boundary = contains_get_ports(from_value)
    to_boundary = contains_get_ports(to_value)
    from_internal = contains_internal_object_access(from_value)
    to_internal = contains_internal_object_access(to_value)

    if from_boundary and to_boundary:
        reason = "boundary_from_to_mapped_keep_path"
        side = "from/to"
    elif from_boundary and to_internal:
        reason = "boundary_from_mapped_keep_path"
        side = "from"
    elif to_boundary and from_internal:
        reason = "boundary_to_mapped_keep_path"
        side = "to"
    else:
        return None

    result = classify_modify_command(command, config, pass1, reason)
    if result.category in set(["KEEP", "MODIFY"]):
        result.category = "MODIFY"
        if reason not in result.reason:
            result.reason = result.reason + ", " + reason if result.reason else reason
        result.review_required = True
        result.notes.append(
            "Boundary %s side was mapped get_ports -> get_pins with instance hierarchy for %s; path semantics must be reviewed." % (
                side,
                command_name_of(text),
            )
        )
    return result


def classify_sense_command(command, config, pass1):
    text = command.normalized_text
    if not has_object_access(text):
        return Result(command, "UNSUPPORTED", "unsupported_set_sense_variant", command_name_of(text), review_required=True)
    if "all_clocks" in text:
        return Result(command, "REMOVE", "soc_level_clock_sense_policy", command_name_of(text), review_required=True)
    return classify_modify_command(command, config, pass1, "set_sense_mapped")


def should_keep_source_latency(command, config, pass1):
    if not config.keep_kept_clock_source_latency:
        return False
    tokens = tokenize_tcl_words(command.normalized_text)
    if "-source" not in [tok.text for tok in tokens]:
        return False
    if not contains_get_clocks(command.normalized_text):
        return False
    state = TransformState(config, pass1)
    transform_text(command.normalized_text, state)
    return state.unsupported_reason is None and state.dangling_clock is None


def command_involves_boundary_port_exception(cmd, text):
    return cmd in BOUNDARY_REVIEW_MAPPING_COMMANDS and contains_get_ports(text)


def default_boundary_remove_reason(cmd):
    if cmd == "set_case_analysis":
        return "boundary_case_analysis_owned_by_scenario_pre"
    if cmd in set(["set_max_delay", "set_min_delay"]):
        return "boundary_delay_owned_by_10_20_30"
    if cmd in set(["set_false_path", "set_multicycle_path"]):
        return "boundary_exception_owned_by_30"
    return "boundary_constraint_owned_by_soc_flow"


def default_remove_reason(cmd):
    if cmd in set(["set_input_delay", "set_output_delay"]):
        return "block_boundary_io_delay"
    if cmd == "set_clock_groups":
        return "soc_clock_relationship_owned_by_top"
    if cmd in set(["set_clock_uncertainty", "set_clock_latency", "set_clock_transition", "set_propagated_clock"]):
        return "soc_clock_budget_owned_by_top"
    if cmd in set(["set_ideal_network", "set_ideal_latency", "set_ideal_transition", "set_dont_touch_network"]):
        return "block_synthesis_network_assumption"
    if cmd in set(["set_wire_load_model", "set_wire_load_mode", "set_resistance", "set_capacitance", "set_annotated_delay", "set_annotated_transition", "set_annotated_check", "read_parasitics", "read_spef"]):
        return "rc_or_back_annotation_owned_by_soc"
    if cmd == "set_timing_derate":
        return "soc_mmmc_derate_owned_by_top"
    if cmd == "set_dont_use":
        return "global_library_constraint"
    if cmd == "group_path":
        return "global_report_grouping"
    return "removed_by_policy"


def run_pass2(commands, config, pass1):
    unit_state = {"seen": [], "errors": []}
    results = []
    for command in commands:
        results.append(classify_command(command, config, pass1, unit_state))
    return results, unit_state


def parse_get_clocks_from_text(text):
    found = []

    def add_clock_selector(selector):
        stripped = selector.strip()
        if wrapped_by(stripped, "{", "}") or wrapped_by(stripped, '"', '"'):
            for sub_token in tokenize_tcl_words(stripped[1:-1]):
                found.append(unwrap_word(sub_token.text))
        else:
            found.append(unwrap_word(stripped))

    def walk(segment):
        index = 0
        brace_depth = 0
        in_quote = False
        while index < len(segment):
            char = segment[index]
            if char == "\\":
                index += 2
                continue
            if brace_depth:
                if char == "{":
                    brace_depth += 1
                elif char == "}":
                    brace_depth -= 1
                index += 1
                continue
            if char == '"' and not brace_depth:
                in_quote = not in_quote
                index += 1
                continue
            if in_quote:
                index += 1
                continue
            if char == "{":
                brace_depth = 1
                index += 1
                continue
            if char != "[":
                index += 1
                continue
            end = matching_bracket_end(segment, index)
            if end < 0:
                index += 1
                continue
            inner = segment[index + 1:end]
            tokens = tokenize_tcl_words(inner)
            if tokens and tokens[0].text == "get_clocks":
                index2 = 1
                while index2 < len(tokens):
                    token = tokens[index2]
                    if token.text.startswith("-"):
                        option = token.text
                        index2 += 1
                        if option in GET_OPTIONS_WITH_VALUE and index2 < len(tokens):
                            index2 += 1
                        continue
                    add_clock_selector(token.text)
                    index2 += 1
            walk(inner)
            index = end + 1

    walk(text)
    return found


def run_pass3(results, config, pass1, unit_state):
    violations = []
    if unit_state["errors"]:
        for command, vtype, token in unit_state["errors"]:
            violations.append(Violation(
                command.command_id,
                command.original_start_line,
                vtype,
                token,
                "Abort conversion; set_units mismatch is fatal.",
                command.normalized_text,
            ))

    for result in results:
        if result.category not in set(["KEEP", "MODIFY"]):
            continue
        text = result.output_text or ""
        if re.search(r"(^|[\s\[])get_ports($|[\s\]])", text):
            violations.append(Violation(
                result.command.command_id,
                result.command.original_start_line,
                "get_ports_remains",
                "get_ports",
                "Check object mapping.",
                text,
            ))
        dangerous = contains_dangerous_all(text)
        if dangerous:
            violations.append(Violation(
                result.command.command_id,
                result.command.original_start_line,
                "dangerous_global_collection_remains",
                dangerous,
                "Remove or manually constrain collection scope.",
                text,
            ))
        if "get_clocks" in text:
            for clock_name in parse_get_clocks_from_text(text):
                if clock_name in pass1.rename_map:
                    violations.append(Violation(
                        result.command.command_id,
                        result.command.original_start_line,
                        "old_clock_name_remains",
                        clock_name,
                        "Check clock rename pass.",
                        text,
                    ))
                if clock_name in pass1.removed_clock_names and clock_name not in config.allow_soc_clocks and clock_name not in config.clock_mapping:
                    violations.append(Violation(
                        result.command.command_id,
                        result.command.original_start_line,
                        "dangling_clock_reference_remains",
                        clock_name,
                        "Remove command or provide --clock-mapping-file / --allow-soc-clock.",
                        text,
                    ))
    return violations


def find_processed_signature(raw_text):
    """Return a Stage1-specific marker, without rejecting other stage outputs."""
    preamble = "\n".join(raw_text.splitlines()[:80])

    if re.search(r"run_stage2_merge_delay\.tcl", preamble, re.IGNORECASE):
        return None

    if "Auto-generated SoC-callable harden SDC" in preamble:
        return "Auto-generated SoC-callable harden SDC"

    tool_match = re.search(
        r"generated\s+by\s*:?[ \t]*(run_stage1_clean_sdc\.py|proc_harden_sdc\.py)",
        preamble,
        re.IGNORECASE,
    )
    if tool_match:
        return tool_match.group(0).strip()

    return None


def ensure_parent(path):
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)


def write_all_outputs(config, commands, results, pass1, unit_state, violations, normalization_error=None, idempotency_error=False):
    invalid = bool(violations) or normalization_error is not None or idempotency_error
    unsupported_count = sum(1 for r in results if r.category == "UNSUPPORTED")
    error_count = sum(1 for r in results if r.category == "ERROR")
    review_required = unsupported_count > 0 or any(r.review_required for r in results)
    if config.strict and unsupported_count > 0:
        invalid = True
    if error_count:
        invalid = True

    if invalid:
        status = "INVALID_OUTPUT"
    elif review_required:
        status = "REVIEW_REQUIRED"
    else:
        status = "CLEAN"

    for path in [
        config.output_path,
        config.removed_path,
        config.unsupported_path,
        config.modified_details_path,
        config.report_path,
    ]:
        ensure_parent(path)

    write_main_sdc(config, results, status, invalid)
    write_review_file(config.removed_path, config, results, "REMOVE", "removed.sdc")
    write_review_file(config.unsupported_path, config, results, "UNSUPPORTED", "unsupported.sdc")
    write_modified_details(config, results)
    write_report(config, commands, results, pass1, unit_state, violations, status, normalization_error, idempotency_error)
    return status


def header_lines(config):
    return [
        "###############################################################################",
        "# Auto-generated SoC-callable harden SDC",
        "#",
        "# Source SDC          : %s" % config.input_path,
        "# Output SDC          : %s" % config.output_path,
        "# Removed SDC         : %s" % config.removed_path,
        "# Unsupported SDC     : %s" % config.unsupported_path,
        "# Modified details    : %s" % config.modified_details_path,
        "# Report              : %s" % config.report_path,
        "# Instance            : %s" % config.inst,
        "#",
        "# This file contains only commands intended to be sourced by SoC STA.",
        "# Removed / unsupported commands are NOT kept here.",
        "# Please review the removed SDC, unsupported SDC, modified details and report.",
        "#",
        "# Generated by        : %s" % TOOL_NAME,
        "# SDC_PROCESS_VERSION : %s" % PROCESS_VERSION,
        "###############################################################################",
        "",
    ]


def write_main_sdc(config, results, status, invalid):
    lines = header_lines(config)
    if invalid:
        lines.append("# Conversion status    : INVALID_OUTPUT")
        lines.append("# Main SDC body suppressed because conversion failed consistency checks.")
        lines.append("")
    else:
        lines.append("# Conversion status    : %s" % status)
        lines.append("")
        clock_definition_results = [
            result for result in results
            if result.category in set(["KEEP", "MODIFY"]) and result.output_text and is_clock_definition_result(result)
        ]
        review_results = [
            result for result in results
            if (
                result.category in set(["KEEP", "MODIFY"])
                and result.output_text
                and result.review_required
                and not is_clock_definition_result(result)
            )
        ]
        for result in clock_definition_results:
            lines.append(result.output_text)
        if review_results:
            lines.extend(review_block_lines(review_results))
        for result in results:
            if (
                result.category in set(["KEEP", "MODIFY"])
                and result.output_text
                and not result.review_required
                and not is_clock_definition_result(result)
            ):
                lines.append(result.output_text)
    with open(config.output_path, "w") as fout:
        fout.write("\n".join(lines).rstrip() + "\n")


def is_clock_definition_result(result):
    return result.command_type in CLOCK_DEFINITION_COMMANDS


def review_block_lines(review_results):
    lines = [
        "###############################################################################",
        "# !!! REVIEW_REQUIRED COMMANDS BEGIN !!!",
        "# Commands in this block are sourced by SoC STA, but require human review.",
        "# Check report.txt and modified_details.txt before STA signoff.",
        "###############################################################################",
        "",
    ]
    for result in review_results:
        lines.extend([
            "# REVIEW_REQUIRED command_id=%06d line=%s type=%s reason=%s" % (
                result.command.command_id,
                result.command.original_start_line,
                result.command_type,
                result.reason,
            ),
        ])
        for note in result.notes:
            lines.append("# REVIEW_NOTE: %s" % note)
        lines.append(result.output_text)
        lines.append("")
    lines.extend([
        "###############################################################################",
        "# !!! REVIEW_REQUIRED COMMANDS END !!!",
        "###############################################################################",
        "",
    ])
    return lines


def write_review_file(path, config, results, category, label):
    lines = [
        "###############################################################################",
        "# %s generated by %s" % (label, TOOL_NAME),
        "# SDC_PROCESS_VERSION : %s" % PROCESS_VERSION,
        "# Instance            : %s" % config.inst,
        "#",
        "# This file is for review only. Do not source it into SoC STA.",
    ]
    if category == "UNSUPPORTED":
        lines.extend([
            "# Commands here could not be safely converted by the script.",
            "# They must be manually reviewed before STA signoff.",
        ])
    lines.append("###############################################################################")
    lines.append("")
    for result in results:
        if result.category != category:
            continue
        lines.extend([
            "# Command ID      : %06d" % result.command.command_id,
            "# Line            : %s-%s" % (result.command.original_start_line, result.command.original_end_line),
            "# Type            : %s" % result.command_type,
            "# Reason          : %s" % result.reason,
            "# Review required : %s" % ("yes" if result.review_required else "no"),
        ])
        for note in result.notes:
            lines.append("# Note            : %s" % note)
        lines.append(result.command.original_text or result.command.normalized_text)
        lines.append("")
    with open(path, "w") as fout:
        fout.write("\n".join(lines).rstrip() + "\n")


def write_modified_details(config, results):
    lines = [
        "Modified details generated by %s" % TOOL_NAME,
        "SDC_PROCESS_VERSION : %s" % PROCESS_VERSION,
        "Instance            : %s" % config.inst,
        "",
    ]
    for result in results:
        if result.category != "MODIFY":
            continue
        lines.extend([
            "Command ID : %06d" % result.command.command_id,
            "Line       : %s" % result.command.original_start_line,
            "Type       : %s" % result.reason,
            "",
            "--- BEFORE",
            result.command.original_text or result.command.normalized_text,
            "",
            "+++ AFTER",
            result.output_text or "",
            "",
        ])
        if result.notes:
            lines.append("--- NOTES")
            for note in result.notes:
                lines.append(note)
            lines.append("")
    with open(config.modified_details_path, "w") as fout:
        fout.write("\n".join(lines).rstrip() + "\n")


def write_report(config, commands, results, pass1, unit_state, violations, status, normalization_error, idempotency_error):
    counts = defaultdict(int)
    type_counts = defaultdict(lambda: defaultdict(int))
    for result in results:
        counts[result.category] += 1
        type_counts[result.category][result.command_type] += 1

    lines = []
    lines.extend([
        "[SUMMARY]",
        "Input SDC              : %s" % config.input_path,
        "Output SDC             : %s" % config.output_path,
        "Removed SDC            : %s" % config.removed_path,
        "Unsupported SDC        : %s" % config.unsupported_path,
        "Modified details       : %s" % config.modified_details_path,
        "Instance               : %s" % config.inst,
        "Total commands         : %d" % len(commands),
        "Kept commands          : %d" % counts["KEEP"],
        "Modified commands      : %d" % counts["MODIFY"],
        "Removed commands       : %d" % counts["REMOVE"],
        "Unsupported commands   : %d" % counts["UNSUPPORTED"],
        "Error commands         : %d" % counts["ERROR"],
        "Conversion status      : %s" % status,
        "",
    ])

    if counts["UNSUPPORTED"]:
        lines.extend([
            "[UNSUPPORTED_STATUS]",
            "Unsupported commands : %d" % counts["UNSUPPORTED"],
            "Status               : REVIEW_REQUIRED" if status != "INVALID_OUTPUT" else "Status               : INVALID_OUTPUT",
            "Impact               : Potential loss of harden-internal constraints.",
            "Action               : Must be reviewed before STA signoff.",
            "Unsupported file     : %s" % config.unsupported_path,
            "",
        ])

    if idempotency_error:
        lines.extend([
            "[IDEMPOTENCY_ERROR]",
            "Status        : INVALID_OUTPUT",
            "Type          : input_already_processed",
            "Matched marker: %s" % idempotency_error,
            "Action        : Re-run with --force-reprocess only if intentional.",
            "",
        ])

    if normalization_error is not None:
        lines.extend([
            "[NORMALIZATION_ERROR]",
            "Status        : INVALID_OUTPUT",
            "Type          : structural_command_boundary_failure",
            "Start line    : %s" % normalization_error.start_line,
            "End line      : %s" % normalization_error.end_line,
            "State         : %s" % normalization_error.state,
            "Action        : Abort conversion",
            "Nearby text   :",
            normalization_error.nearby_text,
            "",
        ])

    lines.extend(format_type_counts("REMOVED_COMMAND_TYPES", type_counts["REMOVE"]))
    lines.extend(format_type_counts("MODIFIED_COMMAND_TYPES", type_counts["MODIFY"]))
    lines.extend(format_type_counts("UNSUPPORTED_COMMAND_TYPES", type_counts["UNSUPPORTED"]))

    lines.extend([
        "[CLOCK_RENAME_MAP]",
    ])
    if pass1.rename_map:
        for old_name, new_name in pass1.rename_map.items():
            lines.append("%s -> %s" % (old_name, new_name))
    else:
        lines.append("<none>")
    lines.append("")

    lines.extend([
        "[REMOVED_CLOCK_DEFINITIONS]",
    ])
    if pass1.removed_clock_defs:
        for decision in pass1.removed_clock_defs:
            lines.append("%s : %s (%s)" % (decision.old_name, decision.reason, decision.command_name))
    else:
        lines.append("<none>")
    lines.append("")

    lines.extend([
        "[UNUSED_CLOCK_DEFINITION_POLICY]",
        "Unused kept create_clock/create_generated_clock definitions are preserved by policy.",
        "Reason: local harden clock definitions may be useful for downstream review or future constraints even if not referenced by the cleaned body.",
    ])
    lines.append("")

    lines.extend([
        "[UNIT_CHECK]",
    ])
    if unit_state["errors"]:
        for command, vtype, token in unit_state["errors"]:
            lines.append("ERROR command_id=%06d line=%s type=%s token=%s" % (
                command.command_id,
                command.original_start_line,
                vtype,
                token,
            ))
    elif unit_state["seen"]:
        for command, units in unit_state["seen"]:
            unit_text = ",".join("%s=%s" % (k, v) for k, v in sorted(units.items()))
            lines.append("OK command_id=%06d line=%s %s" % (command.command_id, command.original_start_line, unit_text))
    else:
        lines.append("No set_units command found.")
    lines.append("")

    dangling = []
    for result in results:
        if result.reason.startswith("dangling_clock_reference_related"):
            dangling.append(result)
    lines.extend([
        "[DANGLING_CLOCK_REFERENCES]",
    ])
    if dangling:
        for result in dangling:
            lines.append("command_id=%06d line=%s reason=%s" % (
                result.command.command_id,
                result.command.original_start_line,
                result.reason,
            ))
    else:
        lines.append("<none>")
    lines.append("")

    review_items = []
    warnings = []
    for result in results:
        for note in result.notes:
            if "review" in note.lower() or result.review_required:
                review_items.append((result.command, note))
            else:
                warnings.append((result.command, note))
    lines.extend([
        "[REVIEW_ITEMS]",
    ])
    if review_items:
        for command, item in review_items:
            lines.append("command_id=%06d line=%s %s" % (command.command_id, command.original_start_line, item))
    else:
        lines.append("<none>")
    lines.append("")

    lines.extend([
        "[WARNINGS]",
    ])
    if warnings:
        for command, item in warnings:
            lines.append("command_id=%06d line=%s %s" % (command.command_id, command.original_start_line, item))
    else:
        lines.append("<none>")
    lines.append("")

    lines.extend([
        "[CONSISTENCY_VIOLATIONS]",
    ])
    if violations:
        for violation in violations:
            lines.extend([
                "Command ID    : %06d" % violation.command_id,
                "Line          : %s" % violation.line,
                "Type          : %s" % violation.vtype,
                "Token         : %s" % violation.token,
                "Action        : %s" % violation.action,
                "Command       :",
                violation.command_text,
                "",
            ])
    else:
        lines.append("<none>")
        lines.append("")

    lines.extend([
        "[MODIFIED_DETAIL_STATUS]",
        "Full detail file : %s" % config.modified_details_path,
        "Detail truncation: none",
        "",
        "[POST_CHECK_HINT]",
        "Run SoC STA post-checks: check_timing, report_clocks, report_exceptions, report_disable_timing, report_case_analysis, report_unconstrained_paths.",
        "Review get_ports -> get_pins boundary exception semantics; mapping only guarantees object path conversion.",
        "",
    ])

    with open(config.report_path, "w") as fout:
        fout.write("\n".join(lines).rstrip() + "\n")


def format_type_counts(section, mapping):
    lines = ["[%s]" % section]
    if not mapping:
        lines.append("<none>")
    else:
        for key in sorted(mapping):
            lines.append("%s : %d" % (key, mapping[key]))
    lines.append("")
    return lines


def parse_expect_units(spec):
    result = {}
    if spec is None:
        return result
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise SystemExit("Invalid --expect-units item: %s" % part)
        key, value = part.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def read_clock_mapping(path):
    mapping = OrderedDict()
    if not path:
        return mapping
    with open(path, "r") as fin:
        reader = csv.DictReader(fin)
        if "block_clock_name" not in reader.fieldnames or "soc_clock_name" not in reader.fieldnames:
            raise SystemExit("clock mapping file must contain block_clock_name,soc_clock_name")
        for row in reader:
            block_name = (row.get("block_clock_name") or "").strip()
            soc_name = (row.get("soc_clock_name") or "").strip()
            if block_name and soc_name:
                mapping[block_name] = soc_name
    return mapping


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Convert harden DC flattened SDC to SoC-callable harden-internal SDC.",
    )
    parser.add_argument("--in", dest="infile", required=True, help="input DC flattened SDC")
    parser.add_argument("--out", required=True, help="output clean SoC-callable SDC")
    parser.add_argument("--removed-out", required=True, help="removed command review SDC")
    parser.add_argument("--unsupported-out", required=True, help="unsupported command review SDC")
    parser.add_argument("--modified-details", required=True, help="full MODIFY before/after details")
    parser.add_argument("--report", required=True, help="conversion report")
    parser.add_argument("--inst", required=True, help="SoC harden instance path")
    parser.add_argument("--expect-units", default=DEFAULT_EXPECT_UNITS, help="expected units, e.g. time=ns,capacitance=pF")

    parser.set_defaults(keep_generated_clock=True)
    parser.add_argument("--keep-generated-clock", dest="keep_generated_clock", action="store_true")
    parser.add_argument("--drop-generated-clock", dest="keep_generated_clock", action="store_false")

    parser.set_defaults(keep_internal_create_clock=True)
    parser.add_argument("--keep-internal-create-clock", dest="keep_internal_create_clock", action="store_true")
    parser.add_argument("--drop-internal-create-clock", dest="keep_internal_create_clock", action="store_false")

    parser.set_defaults(prefix_clock_name=True)
    parser.add_argument("--prefix-clock-name", dest="prefix_clock_name", action="store_true")
    parser.add_argument("--no-prefix-clock-name", dest="prefix_clock_name", action="store_false")

    parser.add_argument("--allow-soc-clock", action="append", default=[], help="allow an existing SoC clock name")
    parser.add_argument("--clock-mapping-file", help="CSV: block_clock_name,soc_clock_name")

    parser.set_defaults(map_port_case_analysis=True)
    parser.add_argument("--map-port-case-analysis", dest="map_port_case_analysis", action="store_true")
    parser.add_argument("--drop-port-case-analysis", dest="map_port_case_analysis", action="store_false")

    parser.add_argument("--keep-kept-clock-source-latency", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--force-reprocess", action="store_true")
    parser.add_argument("--detail-limit", type=int, default=100)
    parser.add_argument("--full-detail", action="store_true")
    parser.add_argument(
        "--oversize-command-chars",
        type=int,
        default=DEFAULT_OVERSIZE_COMMAND_CHARS,
        help="use shallow mapping for commands longer than this many characters",
    )
    return parser


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = Config(args)
    print_author_banner()

    with open(config.input_path, "r") as fin:
        raw_text = fin.read()

    processed_signature = find_processed_signature(raw_text)
    if processed_signature and not config.force_reprocess:
        status = write_all_outputs(
            config,
            [],
            [],
            Pass1Data(),
            {"seen": [], "errors": []},
            [],
            normalization_error=None,
            idempotency_error=processed_signature,
        )
        print("ERROR: input appears to be a Stage1-generated file: %s" % config.input_path, file=sys.stderr)
        print("Matched Stage1 marker: %s" % processed_signature, file=sys.stderr)
        print("Use the Stage2 flatten SDC as --in, or use --force-reprocess only if intentional.", file=sys.stderr)
        return 2

    raw_text = strip_full_line_comments(raw_text)

    try:
        commands = normalize_commands(raw_text)
    except NormalizationError as exc:
        status = write_all_outputs(
            config,
            [],
            [],
            Pass1Data(),
            {"seen": [], "errors": []},
            [],
            normalization_error=exc,
        )
        print("ERROR: structural command boundary failure; see report: %s" % config.report_path, file=sys.stderr)
        return 2

    pass1 = run_pass1(commands, config)
    results, unit_state = run_pass2(commands, config, pass1)
    violations = run_pass3(results, config, pass1, unit_state)
    status = write_all_outputs(config, commands, results, pass1, unit_state, violations)
    print("Conversion status: %s" % status)
    print("Output SDC       : %s" % config.output_path)
    print("Removed SDC      : %s" % config.removed_path)
    print("Unsupported SDC  : %s" % config.unsupported_path)
    print("Report           : %s" % config.report_path)
    if status == "INVALID_OUTPUT":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
