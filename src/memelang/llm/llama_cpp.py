"""In-process GGUF local LLM provider and model puller via `llama-cpp-python`."""

from __future__ import annotations

import os
from pathlib import Path
import re
from pydantic import ValidationError

from memelang.ir.schema import FuncDefStmt, SynthesisItem, SynthesisResult
from memelang.llm.base import (
    LLMProviderError,
    build_compiler_messages,
    has_executable_content,
    split_compilation_units,
)

DEFAULT_GGUF_REPO = "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF"
DEFAULT_GGUF_FILENAME = "qwen2.5-coder-3b-instruct-q4_k_m.gguf"

_GBNF_COMMON = r"""
meme-type ::= non-void-type | "\"Void\""
non-void-type ::= scalar-type | list-type | nested-list-type | map-type | optional-type | ident-str
scalar-type ::= "\"Int\"" | "\"Float\"" | "\"Bool\"" | "\"String\""
map-key-type ::= "\"Int\"" | "\"Bool\"" | "\"String\""
list-type ::= "\"List<Int>\"" | "\"List<Float>\"" | "\"List<Bool>\"" | "\"List<String>\"" | "\"List<" [a-zA-Z_] [a-zA-Z0-9_]* ">\""
nested-list-type ::= "\"List<List<Int>>\"" | "\"List<List<Float>>\"" | "\"List<List<Bool>>\"" | "\"List<List<String>>\""
map-type ::= "\"Map<" [a-zA-Z0-9_]+ ", " [a-zA-Z0-9_<> ,]+ ">\""
optional-type ::= "\"Optional<" [a-zA-Z0-9_<> ,]+ ">\""
bin-op ::= int-bin-op | bool-cmp-op
int-bin-op ::= "\"+\"" | "\"-\"" | "\"*\"" | "\"/\"" | "\"%\""
compound-op ::= "\"+\"" | "\"-\"" | "\"*\"" | "\"/\""
bool-cmp-op ::= "\"==\"" | "\"!=\"" | "\"<\"" | "\"<=\"" | "\">\"" | "\">=\"" | "\"and\"" | "\"or\""
un-op ::= "\"-\"" | "\"not\""
sort-dir ::= "\"ascending\"" | "\"descending\""
opt-source-line ::= (ws "," ws "\"source_line\"" ws ":" ws (pos-int | "null"))?

ir-expr ::= literal-expr | list-literal-expr | var-ref-expr | random-int-expr | random-list-expr | binary-op-expr | unary-op-expr | list-length-expr | list-index-expr | string-length-expr | string-slice-expr | parse-int-expr | parse-int-or-default-expr | format-int-expr | is-digit-expr | call-expr | read-input-expr | str-ends-with-expr | str-contains-expr | str-starts-with-expr | string-replace-expr | string-upper-expr | string-lower-expr | string-trim-expr | string-split-expr | string-join-expr | string-index-of-expr | string-char-at-expr | file-exists-expr | read-file-string-expr | list-files-expr | arg-count-expr | arg-at-expr | read-json-list-expr | record-literal-expr | record-field-expr | map-literal-expr | map-get-expr | map-has-key-expr | optional-none-expr | optional-wrap-expr | optional-is-nothing-expr | optional-unwrap-expr | optional-unwrap-or-default-expr
expr-list ::= "[" ws (ir-expr (ws "," ws ir-expr)*)? ws "]"

int-lit-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"literal\"" ws "," ws "\"value\"" ws ":" ws integer ws "," ws "\"data_type\"" ws ":" ws "\"Int\"" ws "}"
int-bin-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"binary_op\"" ws "," ws "\"op\"" ws ":" ws int-bin-op ws "," ws "\"left\"" ws ":" ws int-expr ws "," ws "\"right\"" ws ":" ws int-expr ws "}"
int-un-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"unary_op\"" ws "," ws "\"op\"" ws ":" ws "\"-\"" ws "," ws "\"operand\"" ws ":" ws int-expr ws "}"
int-expr ::= int-lit-expr | var-ref-expr | random-int-expr | int-bin-expr | int-un-expr | list-length-expr | list-index-expr | string-length-expr | string-index-of-expr | parse-int-expr | parse-int-or-default-expr | arg-count-expr | call-expr | read-input-expr | record-field-expr | map-get-expr

bool-lit-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"literal\"" ws "," ws "\"value\"" ws ":" ws boolean ws "," ws "\"data_type\"" ws ":" ws "\"Bool\"" ws "}"
bool-bin-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"binary_op\"" ws "," ws "\"op\"" ws ":" ws bool-cmp-op ws "," ws "\"left\"" ws ":" ws ir-expr ws "," ws "\"right\"" ws ":" ws ir-expr ws "}"
bool-un-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"unary_op\"" ws "," ws "\"op\"" ws ":" ws "\"not\"" ws "," ws "\"operand\"" ws ":" ws bool-expr ws "}"
bool-expr ::= bool-lit-expr | var-ref-expr | bool-bin-expr | bool-un-expr | list-index-expr | is-digit-expr | call-expr | str-ends-with-expr | str-contains-expr | str-starts-with-expr | file-exists-expr | read-input-expr | record-field-expr | map-get-expr | map-has-key-expr | optional-is-nothing-expr

literal-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"literal\"" ws "," ws (
    "\"value\"" ws ":" ws integer ws "," ws "\"data_type\"" ws ":" ws ("\"Int\"" | "\"Float\"")
  | "\"value\"" ws ":" ws float-num ws "," ws "\"data_type\"" ws ":" ws "\"Float\""
  | "\"value\"" ws ":" ws boolean ws "," ws "\"data_type\"" ws ":" ws "\"Bool\""
  | "\"value\"" ws ":" ws string ws "," ws "\"data_type\"" ws ":" ws "\"String\""
) ws "}"
list-literal-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"list_literal\"" ws "," ws "\"elements\"" ws ":" ws expr-list ws "," ws "\"element_type\"" ws ":" ws non-void-type ws "}"
var-ref-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"var_ref\"" ws "," ws "\"name\"" ws ":" ws ident-str ws "}"
random-int-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"random_int\"" ws "," ws "\"min_val\"" ws ":" ws int-expr ws "," ws "\"max_val\"" ws ":" ws int-expr ws "}"
random-list-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"random_list\"" ws "," ws "\"count\"" ws ":" ws int-expr ws "," ws "\"min_val\"" ws ":" ws int-expr ws "," ws "\"max_val\"" ws ":" ws int-expr (ws "," ws "\"implicit_bounds\"" ws ":" ws boolean)? ws "}"
binary-op-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"binary_op\"" ws "," ws "\"op\"" ws ":" ws bin-op ws "," ws "\"left\"" ws ":" ws ir-expr ws "," ws "\"right\"" ws ":" ws ir-expr ws "}"
unary-op-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"unary_op\"" ws "," ws "\"op\"" ws ":" ws un-op ws "," ws "\"operand\"" ws ":" ws ir-expr ws "}"
list-length-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"list_length\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "}"
list-index-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"list_index\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "," ws "\"index\"" ws ":" ws int-expr ws "}"
string-length-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"string_length\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "}"
string-slice-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"string_slice\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "," ws "\"start\"" ws ":" ws int-expr ws "," ws "\"end\"" ws ":" ws int-expr ws "}"
parse-int-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"parse_int\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "}"
parse-int-or-default-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"parse_int_or_default\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "," ws "\"default_val\"" ws ":" ws int-expr ws "}"
format-int-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"format_int\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "}"
is-digit-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"is_digit\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "}"
call-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"call\"" ws "," ws "\"func_name\"" ws ":" ws ident-str (ws "," ws "\"args\"" ws ":" ws expr-list)? ws "}"
read-input-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"read_input\"" (ws "," ws "\"prompt\"" ws ":" ws string)? (ws "," ws "\"target_type\"" ws ":" ws scalar-type)? ws "}"
str-ends-with-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"str_ends_with\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "," ws "\"suffix\"" ws ":" ws ir-expr ws "}"
str-contains-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"str_contains\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "," ws "\"substring\"" ws ":" ws ir-expr ws "}"
str-starts-with-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"str_starts_with\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "," ws "\"prefix\"" ws ":" ws ir-expr ws "}"
string-replace-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"string_replace\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "," ws "\"old\"" ws ":" ws ir-expr ws "," ws "\"new\"" ws ":" ws ir-expr ws "}"
string-upper-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"string_upper\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "}"
string-lower-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"string_lower\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "}"
string-trim-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"string_trim\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "}"
string-split-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"string_split\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "," ws "\"separator\"" ws ":" ws ir-expr ws "}"
string-join-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"string_join\"" ws "," ws "\"items\"" ws ":" ws ir-expr ws "," ws "\"separator\"" ws ":" ws ir-expr ws "}"
string-index-of-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"string_index_of\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "," ws "\"substring\"" ws ":" ws ir-expr ws "}"
string-char-at-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"string_char_at\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "," ws "\"index\"" ws ":" ws int-expr ws "}"
file-exists-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"file_exists\"" ws "," ws "\"filepath\"" ws ":" ws ir-expr ws "}"
read-file-string-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"read_file_string\"" ws "," ws "\"filepath\"" ws ":" ws ir-expr ws "}"
list-files-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"list_files\"" ws "," ws "\"path\"" ws ":" ws ir-expr ws "}"
arg-count-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"arg_count\"" ws "}"
arg-at-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"arg_at\"" ws "," ws "\"index\"" ws ":" ws int-expr ws "}"
read-json-list-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"read_json_list\"" ws "," ws "\"filepath\"" ws ":" ws ir-expr (ws "," ws "\"element_type\"" ws ":" ws scalar-type)? (ws "," ws "\"explicit_type\"" ws ":" ws boolean)? ws "}"
record-field-init ::= "{" ws "\"name\"" ws ":" ws ident-str ws "," ws "\"value\"" ws ":" ws ir-expr ws "}"
record-field-init-list ::= "[" ws (record-field-init (ws "," ws record-field-init)*)? ws "]"
record-literal-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"record_literal\"" ws "," ws "\"record_name\"" ws ":" ws ident-str (ws "," ws "\"fields\"" ws ":" ws record-field-init-list)? ws "}"
record-field-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"record_field\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "," ws "\"field_name\"" ws ":" ws ident-str ws "}"
map-entry ::= "{" ws "\"key\"" ws ":" ws ir-expr ws "," ws "\"value\"" ws ":" ws ir-expr ws "}"
map-entry-list ::= "[" ws (map-entry (ws "," ws map-entry)*)? ws "]"
map-literal-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"map_literal\"" ws "," ws "\"key_type\"" ws ":" ws map-key-type ws "," ws "\"value_type\"" ws ":" ws non-void-type (ws "," ws "\"entries\"" ws ":" ws map-entry-list)? ws "}"
map-get-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"map_get\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "," ws "\"key\"" ws ":" ws ir-expr (ws "," ws "\"default_val\"" ws ":" ws (ir-expr | "null"))? ws "}"
map-has-key-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"map_has_key\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "," ws "\"key\"" ws ":" ws ir-expr ws "}"
optional-none-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"optional_none\"" ws "}"
optional-wrap-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"optional_wrap\"" ws "," ws "\"value\"" ws ":" ws ir-expr ws "}"
optional-is-nothing-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"optional_is_nothing\"" ws "," ws "\"target\"" ws ":" ws ir-expr (ws "," ws "\"negated\"" ws ":" ws boolean)? ws "}"
optional-unwrap-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"optional_unwrap\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "}"
optional-unwrap-or-default-expr ::= "{" ws "\"expr_type\"" ws ":" ws "\"optional_unwrap_or_default\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "," ws "\"default_val\"" ws ":" ws ir-expr ws "}"

body-stmt ::= var-decl-stmt | assign-stmt | compound-assign-stmt | sort-stmt | clamp-stmt | filter-stmt | append-stmt | insert-stmt | set-index-stmt | remove-stmt | record-set-field-stmt | map-set-stmt | write-file-stmt | append-file-stmt | copy-file-stmt | move-file-stmt | rename-file-stmt | delete-file-stmt | create-directory-stmt | fail-stmt | exit-stmt | print-stmt | if-stmt | switch-stmt | for-each-stmt | for-range-stmt | while-stmt | loop-break-stmt | loop-continue-stmt | return-stmt
ir-stmt ::= body-stmt | func-def-stmt | record-def-stmt | import-stmt
stmt-list ::= "[" ws (body-stmt (ws "," ws body-stmt)*)? ws "]"
func-param ::= "{" ws "\"name\"" ws ":" ws ident-str ws "," ws "\"param_type\"" ws ":" ws non-void-type ws "}"
param-list ::= "[" ws (func-param (ws "," ws func-param)*)? ws "]"
record-field-def ::= "{" ws "\"name\"" ws ":" ws ident-str ws "," ws "\"field_type\"" ws ":" ws non-void-type ws "}"
record-field-def-list ::= "[" ws (record-field-def (ws "," ws record-field-def)*)? ws "]"

var-decl-stmt ::= "{" ws "\"op\"" ws ":" ws "\"var_decl\"" ws "," ws "\"name\"" ws ":" ws ident-str ws "," ws "\"var_type\"" ws ":" ws non-void-type ws "," ws "\"value\"" ws ":" ws ir-expr opt-source-line ws "}"
assign-stmt ::= "{" ws "\"op\"" ws ":" ws "\"assign\"" ws "," ws "\"name\"" ws ":" ws ident-str ws "," ws "\"value\"" ws ":" ws ir-expr opt-source-line ws "}"
compound-assign-stmt ::= "{" ws "\"op\"" ws ":" ws "\"compound_assign\"" ws "," ws "\"target\"" ws ":" ws ident-str ws "," ws "\"operator\"" ws ":" ws compound-op ws "," ws "\"value\"" ws ":" ws ir-expr opt-source-line ws "}"
sort-stmt ::= "{" ws "\"op\"" ws ":" ws "\"sort_collection\"" ws "," ws "\"target\"" ws ":" ws ident-str (ws "," ws "\"direction\"" ws ":" ws sort-dir)? opt-source-line ws "}"
clamp-stmt ::= "{" ws "\"op\"" ws ":" ws "\"clamp_collection\"" ws "," ws "\"target\"" ws ":" ws ident-str ws "," ws "\"min_val\"" ws ":" ws ir-expr ws "," ws "\"max_val\"" ws ":" ws ir-expr opt-source-line ws "}"
filter-stmt ::= "{" ws "\"op\"" ws ":" ws "\"filter_collection\"" ws "," ws "\"target\"" ws ":" ws ident-str ws "," ws "\"item_var\"" ws ":" ws ident-str ws "," ws "\"predicate\"" ws ":" ws bool-expr opt-source-line ws "}"
append-stmt ::= "{" ws "\"op\"" ws ":" ws "\"list_append\"" ws "," ws "\"target\"" ws ":" ws ident-str ws "," ws "\"value\"" ws ":" ws ir-expr opt-source-line ws "}"
insert-stmt ::= "{" ws "\"op\"" ws ":" ws "\"list_insert\"" ws "," ws "\"target\"" ws ":" ws ident-str ws "," ws "\"index\"" ws ":" ws int-expr ws "," ws "\"value\"" ws ":" ws ir-expr opt-source-line ws "}"
set-index-stmt ::= "{" ws "\"op\"" ws ":" ws "\"list_set_index\"" ws "," ws "\"target\"" ws ":" ws ident-str ws "," ws "\"index\"" ws ":" ws int-expr ws "," ws "\"value\"" ws ":" ws ir-expr opt-source-line ws "}"
remove-stmt ::= "{" ws "\"op\"" ws ":" ws "\"list_remove\"" ws "," ws "\"target\"" ws ":" ws ident-str (ws "," ws "\"index\"" ws ":" ws (int-expr | "null"))? opt-source-line ws "}"
record-set-field-stmt ::= "{" ws "\"op\"" ws ":" ws "\"record_set_field\"" ws "," ws "\"target\"" ws ":" ws ident-str ws "," ws "\"field_name\"" ws ":" ws ident-str ws "," ws "\"value\"" ws ":" ws ir-expr opt-source-line ws "}"
map-set-stmt ::= "{" ws "\"op\"" ws ":" ws "\"map_set\"" ws "," ws "\"target\"" ws ":" ws ident-str ws "," ws "\"key\"" ws ":" ws ir-expr ws "," ws "\"value\"" ws ":" ws ir-expr opt-source-line ws "}"
write-file-stmt ::= "{" ws "\"op\"" ws ":" ws "\"write_file\"" ws "," ws "\"filepath\"" ws ":" ws ir-expr ws "," ws "\"content\"" ws ":" ws ir-expr opt-source-line ws "}"
append-file-stmt ::= "{" ws "\"op\"" ws ":" ws "\"append_file\"" ws "," ws "\"filepath\"" ws ":" ws ir-expr ws "," ws "\"content\"" ws ":" ws ir-expr opt-source-line ws "}"
copy-file-stmt ::= "{" ws "\"op\"" ws ":" ws "\"copy_file\"" ws "," ws "\"src\"" ws ":" ws ir-expr ws "," ws "\"dst\"" ws ":" ws ir-expr opt-source-line ws "}"
move-file-stmt ::= "{" ws "\"op\"" ws ":" ws "\"move_file\"" ws "," ws "\"src\"" ws ":" ws ir-expr ws "," ws "\"dst\"" ws ":" ws ir-expr opt-source-line ws "}"
rename-file-stmt ::= "{" ws "\"op\"" ws ":" ws "\"rename_file\"" ws "," ws "\"path\"" ws ":" ws ir-expr ws "," ws "\"new_name\"" ws ":" ws ir-expr opt-source-line ws "}"
delete-file-stmt ::= "{" ws "\"op\"" ws ":" ws "\"delete_file\"" ws "," ws "\"path\"" ws ":" ws ir-expr opt-source-line ws "}"
create-directory-stmt ::= "{" ws "\"op\"" ws ":" ws "\"create_directory\"" ws "," ws "\"path\"" ws ":" ws ir-expr opt-source-line ws "}"
fail-stmt ::= "{" ws "\"op\"" ws ":" ws "\"fail_stmt\"" ws "," ws "\"message\"" ws ":" ws ir-expr opt-source-line ws "}"
exit-stmt ::= "{" ws "\"op\"" ws ":" ws "\"exit_stmt\"" ws "," ws "\"code\"" ws ":" ws int-expr opt-source-line ws "}"
print-stmt ::= "{" ws "\"op\"" ws ":" ws "\"print_stmt\"" ws "," ws "\"expressions\"" ws ":" ws "[" ws ir-expr (ws "," ws ir-expr)* ws "]" opt-source-line ws "}"
if-stmt ::= "{" ws "\"op\"" ws ":" ws "\"if_stmt\"" ws "," ws "\"condition\"" ws ":" ws bool-expr ws "," ws "\"then_body\"" ws ":" ws stmt-list (ws "," ws "\"else_body\"" ws ":" ws stmt-list)? opt-source-line ws "}"
switch-case ::= "{" ws "\"value\"" ws ":" ws ir-expr ws "," ws "\"body\"" ws ":" ws stmt-list ws "}"
switch-cases ::= "[" ws (switch-case (ws "," ws switch-case)*)? ws "]"
switch-stmt ::= "{" ws "\"op\"" ws ":" ws "\"switch_stmt\"" ws "," ws "\"target\"" ws ":" ws ir-expr ws "," ws "\"cases\"" ws ":" ws switch-cases (ws "," ws "\"default_body\"" ws ":" ws stmt-list)? opt-source-line ws "}"
for-each-stmt ::= "{" ws "\"op\"" ws ":" ws "\"for_each\"" ws "," ws "\"item_var\"" ws ":" ws ident-str (ws "," ws "\"index_var\"" ws ":" ws (ident-str | "null"))? ws "," ws "\"collection\"" ws ":" ws ident-str ws "," ws "\"body\"" ws ":" ws stmt-list opt-source-line ws "}"
for-range-stmt ::= "{" ws "\"op\"" ws ":" ws "\"for_range\"" ws "," ws "\"loop_var\"" ws ":" ws ident-str ws "," ws "\"start\"" ws ":" ws int-expr ws "," ws "\"end\"" ws ":" ws int-expr ws "," ws "\"body\"" ws ":" ws stmt-list opt-source-line ws "}"
while-stmt ::= "{" ws "\"op\"" ws ":" ws "\"while_loop\"" ws "," ws "\"condition\"" ws ":" ws bool-expr ws "," ws "\"body\"" ws ":" ws stmt-list opt-source-line ws "}"
loop-break-stmt ::= "{" ws "\"op\"" ws ":" ws "\"loop_break\"" opt-source-line ws "}"
loop-continue-stmt ::= "{" ws "\"op\"" ws ":" ws "\"loop_continue\"" opt-source-line ws "}"

record-def-stmt ::= "{" ws "\"op\"" ws ":" ws "\"record_def\"" ws "," ws "\"name\"" ws ":" ws ident-str (ws "," ws "\"fields\"" ws ":" ws record-field-def-list)? opt-source-line ws "}"
func-def-stmt ::= "{" ws "\"op\"" ws ":" ws "\"func_def\"" ws "," ws "\"name\"" ws ":" ws ident-str (ws "," ws "\"params\"" ws ":" ws param-list)? (ws "," ws "\"return_type\"" ws ":" ws meme-type)? ws "," ws "\"body\"" ws ":" ws stmt-list opt-source-line ws "}"
import-stmt ::= "{" ws "\"op\"" ws ":" ws "\"import_stmt\"" ws "," ws "\"module\"" ws ":" ws ident-str opt-source-line ws "}"
return-stmt ::= "{" ws "\"op\"" ws ":" ws "\"return_stmt\"" (ws "," ws "\"value\"" ws ":" ws (ir-expr | "null"))? opt-source-line ws "}"

ident-str ::= "\"" [a-zA-Z_] [a-zA-Z0-9_]* "\""
pos-int ::= [1-9] [0-9]*
integer ::= "-"? ("0" | [1-9] [0-9]*)
float-num ::= "-"? ("0" | [1-9] [0-9]*) "." [0-9]+ ([eE] [-+]? [0-9]+)?
boolean ::= "true" | "false"
string ::= "\"" ([^"\\\x7F\x00-\x1F] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4}))* "\""
ws ::= [ \t\n\r]*
"""

MEMELANG_GBNF = (
    'root ::= ws "{" ws "\\"items\\"" ws ":" ws "[" ws (ir-stmt (ws "," ws ir-stmt)*)? ws "]" ws "}" ws\n'
    + _GBNF_COMMON
)

MEMELANG_FUNC_GBNF = (
    'root ::= ws "{" ws "\\"items\\"" ws ":" ws "[" ws func-def-stmt ws "]" ws "}" ws\n'
    + _GBNF_COMMON
)


def build_llama_grammar(func_only: bool = False):
    try:
        from llama_cpp import LlamaGrammar  # type: ignore[import-not-found]
    except ImportError as exc:
        raise LLMProviderError(
            "llama-cpp-python is not installed. Install with: `uv sync --extra local-gguf`"
        ) from exc
    return LlamaGrammar.from_string(
        MEMELANG_FUNC_GBNF if func_only else MEMELANG_GBNF,
        verbose=False,
    )


def get_model_cache_dir() -> Path:
    env_dir = os.environ.get("MEME_MODEL_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".cache" / "memelang" / "models"


def find_cached_gguf(model_dir: Path | None = None) -> Path | None:
    target_dir = model_dir or get_model_cache_dir()
    if not target_dir.exists():
        return None
    preferred = target_dir / DEFAULT_GGUF_FILENAME
    if preferred.is_file():
        return preferred
    ggufs = sorted(target_dir.glob("*.gguf"))
    return ggufs[0] if ggufs else None


def pull_gguf_model(
    repo_id: str = DEFAULT_GGUF_REPO,
    filename: str = DEFAULT_GGUF_FILENAME,
    model_dir: Path | None = None,
) -> Path:
    target_dir = model_dir or get_model_cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import hf_hub_download  # type: ignore[import-not-found]
    except ImportError as exc:
        raise LLMProviderError(
            "huggingface-hub is not installed. Install with: `uv sync --extra local-gguf`"
        ) from exc

    try:
        downloaded = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(target_dir),
        )
        return Path(downloaded)
    except Exception as exc:
        raise LLMProviderError(
            f"Failed to download `{filename}` from `{repo_id}`: {exc}"
        ) from exc


def _extract_json_object(raw: str) -> str:
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, flags=re.DOTALL)
    if m:
        return m.group(1)
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return s[start : end + 1]
    return s


class LlamaCppProvider:
    def __init__(
        self,
        model_path: str | Path,
        n_gpu_layers: int = -1,
        n_ctx: int = 8192,
        max_tokens: int = 4096,
        retriever: object = None,
    ) -> None:
        self.model_path = Path(model_path)
        self.n_gpu_layers = n_gpu_layers
        self.n_ctx = n_ctx
        self.max_tokens = max_tokens
        self.retriever = retriever
        self.name = f"llama-cpp:{self.model_path.name}"
        self._llm = None

    def _get_llm(self):
        if not self.model_path.exists():
            raise LLMProviderError(f"GGUF model file not found: {self.model_path}")
        if self._llm is None:
            try:
                from llama_cpp import Llama  # type: ignore[import-not-found]
            except ImportError as exc:
                raise LLMProviderError(
                    "llama-cpp-python is not installed. Install with: `uv sync --extra local-gguf`"
                ) from exc
            self._llm = Llama(
                model_path=str(self.model_path),
                n_gpu_layers=self.n_gpu_layers,
                n_ctx=self.n_ctx,
                verbose=False,
            )
        return self._llm

    def synthesize(
        self, source_text: str, source_path: Path | None = None
    ) -> SynthesisResult:
        if not has_executable_content(source_text):
            return SynthesisResult(items=[])

        units = split_compilation_units(source_text)
        if not units:
            return SynthesisResult(items=[])

        llm = self._get_llm()
        all_items: list[SynthesisItem] = []
        defined_funcs: list[FuncDefStmt] = []

        try:
            for unit in units:
                grammar = build_llama_grammar(func_only=unit.is_func)
                msgs = build_compiler_messages(
                    unit.text,
                    line_numbers=unit.line_numbers,
                    available_functions=defined_funcs if defined_funcs else None,
                    source_path=source_path,
                    retriever=self.retriever,
                )
                resp = llm.create_chat_completion(
                    messages=msgs,
                    temperature=0.0,
                    seed=42,
                    max_tokens=self.max_tokens,
                    grammar=grammar,
                )
                content = _extract_json_object(resp["choices"][0]["message"]["content"])
                part = SynthesisResult.model_validate_json(content)
                for it in part.items:
                    if isinstance(it, FuncDefStmt):
                        if it.source_line is None and unit.line_numbers:
                            it.source_line = unit.line_numbers[0]
                        defined_funcs.append(it)
                    all_items.append(it)
            return SynthesisResult(items=all_items)
        except (KeyError, IndexError, ValueError, ValidationError, RuntimeError) as exc:
            raise LLMProviderError(f"llama.cpp synthesis failed: {exc}") from exc
