# WS-CORE Specification Notes & Integration Guide

**Document Purpose**: Deliverable from workstream **WS-CORE** for the team coordinator and WS-DOCS. Summarizes new IR schema nodes, canonical grammar, runtime semantics, codegen design, and parity test guarantees implemented in Capability Expansion Batch 1.

---

## 1. Feature Overview

WS-CORE implemented three major capability additions across all 6 compilation targets (`python`, `rust`, `cpp`, `go`, `c`, `ts`):

1. **File Management Builtins**:
   - `copy file <src> to <dst>`
   - `move file <src> to <dst>`
   - `rename file <path> to <new-name>`
   - `delete file <path>`
   - `create directory <path>`
   - `list files in <path>` (returns `List<String>`)
2. **List Item Removal**:
   - `remove item <index-expr> from <list-var>`
   - `remove last item from <list-var>`
3. **Safe Parse & Character Predicate**:
   - `integer value of <s-expr> or else <default-expr>` (lazy evaluation of fallback)
   - `is digit <char-expr>` (evaluates to `Bool`)

All features conform to the 7-artifact rule:
1. `src/memelang/ir/schema.py` AST/IR nodes.
2. `src/memelang/analyzer/verifier.py` static verification, type-checking, bounds/mutation tracking.
3. `src/memelang/ir/canonical.py` canonical syntax decompiler and round-trip fidelity.
4. `src/memelang/codegen/{python_gen,rust_gen,cpp_gen,go_gen,c_gen,ts_gen}.py` 6-target codegen with byte-parity semantics.
5. `tests/test_codegen_targets.py` parity tests covering nominal paths and failure messages.
6. `src/memelang/llm/{heuristic.py,base.py,llama_cpp.py}` Pratt parser, prompt documentation, and GBNF grammar.
7. `docs/WS-CORE-SPEC-NOTES.md` this specification and coordination document.

---

## 2. Feature 1: File Management Builtins

### 2.1 Syntax & Canonical Representation

* **Copy**:
  - Casual / Alternative: `copy <src> to <dst>`, `copy file <src> to <dst>`
  - Canonical: `copy file <src> to <dst>`
* **Move**:
  - Casual / Alternative: `move <src> to <dst>`, `move file <src> to <dst>`
  - Canonical: `move file <src> to <dst>`
* **Rename**:
  - Casual / Alternative: `rename <path> to <new-name>`, `rename file <path> to <new-name>`
  - Canonical: `rename file <path> to <new-name>`
* **Delete**:
  - Casual / Alternative: `delete <path>`, `delete file <path>`, `remove file <path>`
  - Canonical: `delete file <path>`
* **Create Directory**:
  - Casual / Alternative: `create directory <path>`, `make directory <path>`, `create folder <path>`
  - Canonical: `create directory <path>`
* **List Files**:
  - Casual / Alternative: `list files in <path>`, `list files <path>`, `files in <path>`
  - Canonical: `list files in <path>`

### 2.2 IR Schema Nodes

```python
class CopyFileStmt(BaseStmt):
    op: Literal["copy_file"] = "copy_file"
    src: IRExpr
    dst: IRExpr

class MoveFileStmt(BaseStmt):
    op: Literal["move_file"] = "move_file"
    src: IRExpr
    dst: IRExpr

class RenameFileStmt(BaseStmt):
    op: Literal["rename_file"] = "rename_file"
    path: IRExpr
    new_name: IRExpr

class DeleteFileStmt(BaseStmt):
    op: Literal["delete_file"] = "delete_file"
    path: IRExpr

class CreateDirectoryStmt(BaseStmt):
    op: Literal["create_directory"] = "create_directory"
    path: IRExpr

class ListFilesExpr(BaseExpr):
    expr_type: Literal["list_files"] = "list_files"
    path: IRExpr
```

### 2.3 Semantics & Target Behavior

| Builtin | Target Behavior | Destination Exists | Source Missing / Invalid |
| :--- | :--- | :--- | :--- |
| `copy file <src> to <dst>` | Overwrites destination file. Creates parent directories if needed. | Overwritten cleanly | Fails: prints `Error copying file: <src>`, exits code 1 |
| `move file <src> to <dst>` | Atomically moves (or copies + unlinks) file to destination path. | Overwritten cleanly | Fails: prints `Error moving file: <src>`, exits code 1 |
| `rename file <path> to <new-name>` | Renames within directory or relocates if `new-name` is a path. | Overwritten cleanly | Fails: prints `Error renaming file: <path>`, exits code 1 |
| `delete file <path>` | Removes file via filesystem unlink. | N/A | Fails: prints `Error deleting file: <path>`, exits code 1 |
| `create directory <path>` | Creates directory recursively (`mkdir -p` semantics). Idempotent. | No-op / succeeds | Fails if parent directory cannot be created or permissions fail |
| `list files in <path>` | Returns `List<String>` of plain directory entry names, **sorted lexicographically**. Includes files and subdirectories (plain names, not paths). | N/A | Fails: prints `Error listing directory: <path>`, exits code 1 |

---

## 3. Feature 2: List Item Removal

### 3.1 Syntax & Canonical Representation

* **Indexed Removal**:
  - Casual / Alternative: `remove item <index> from <list>`, `remove element <index> from <list>`, `remove item at <index> from <list>`
  - Canonical: `remove item <index> from <list>`
* **Last Item Removal**:
  - Casual / Alternative: `remove last item from <list>`, `remove last element from <list>`
  - Canonical: `remove last item from <list>`

### 3.2 IR Schema Node

```python
class ListRemoveStmt(BaseStmt):
    op: Literal["list_remove"] = "list_remove"
    target: str
    index: IRExpr | None = None  # None indicates removing the last element
```

### 3.3 Semantics & Design Decisions

* **In-Place Mutation**: `remove item` mutates `<list>` in place, shifting all subsequent elements left by 1 index and reducing list length by 1.
* **Negative Indices Banned**: The static verifier rejects negative literal integer indices, directing the developer to `remove last item from <target>` or `length of <target> - k`.
* **Out-of-Bounds Protection**: If `index < 0` or `index >= length` at runtime (or if `remove last item` is called on an empty list), runtime halts with exit code 1 and prints:
  `Error: list index out of range` (identical to index access failure).
* **Decision on `pop` Expression**:
  - *Decision*: Deliberately omitted. In Memelang, mutations are structured statements rather than expressions that yield values. Having `remove item <index> from <target>` and `remove last item from <target>` as dedicated statements cleanly avoids side-effecting expressions and ensures simple, leak-free codegen across C, Rust, Go, and C++.

---

## 4. Feature 3: Safe Parse & Character Predicate

### 4.1 Syntax & Canonical Representation

* **Safe Parse with Fallback**:
  - Casual / Alternative: `integer value of <s> or else <default>`, `integer of <s> or else <default>`
  - Canonical: `integer value of <s> or else <default>`
* **Digit Predicate**:
  - Casual / Alternative: `is digit <char-expr>`
  - Canonical: `is digit <char-expr>`

### 4.2 IR Schema Nodes

```python
class ParseIntOrDefaultExpr(BaseExpr):
    expr_type: Literal["parse_int_or_default"] = "parse_int_or_default"
    target: IRExpr
    default_val: IRExpr

class IsDigitExpr(BaseExpr):
    expr_type: Literal["is_digit"] = "is_digit"
    target: IRExpr
```

### 4.3 Semantics & Design Decisions

* **Lazy Evaluation of Fallback**:
  - `<default>` expression is evaluated **strictly only if parsing fails**. If parsing succeeds, `<default>` is never evaluated.
  - Target code generation implementation of laziness:
    - **Python**: `_meme_parse_int_or_else(s, lambda: <default>)`
    - **TypeScript**: `_meme_parse_int_or_else(s, () => <default>)`
    - **Rust**: `_meme_parse_int_or_else(&(s), || <default>)`
    - **C++20**: `_meme_parse_int_or_else(s, [&]() -> long long { return <default>; })`
    - **Go**: `_meme_parse_int_or_else(s, func() int64 { return <default> })`
    - **C (C11)**: `__extension__ ({ int64_t _v; _meme_try_parse_int(s, &_v) ? _v : (<default>); })` (zero warning under `-Wall -std=c11`).
* **Integer Parsing Rules**:
  - Trims leading and trailing whitespace.
  - Supports optional leading sign (`+` or `-`).
  - Digits must be base-10 ASCII (`'0'` through `'9'`). Any trailing non-digit characters trigger fallback to `<default>`.
* **Digit Predicate (`is digit`)**:
  - Returns `true` if and only if the string argument has length exactly 1 and contains an ASCII decimal digit (`'0'` .. `'9'`).
  - Returns `false` for empty strings, multi-character strings (e.g. `"12"`), whitespace, or any non-digit character.
  - *Decision*: Only `is digit` was introduced; no full regex / char-class engine was added to preserve zero-dependency runtime simplicity across all targets.

---

## 5. Parity & Error Output Reference Table

All targets emit identical exit codes and stdout error messages:

| Scenario | Exit Code | Standard Output Message |
| :--- | :--- | :--- |
| `copy file <src> to <dst>` (src missing) | 1 | `Error copying file: <src>` |
| `move file <src> to <dst>` (src missing) | 1 | `Error moving file: <src>` |
| `rename file <path> to <new>` (src missing) | 1 | `Error renaming file: <path>` |
| `delete file <path>` (file missing) | 1 | `Error deleting file: <path>` |
| `list files in <path>` (invalid path) | 1 | `Error listing directory: <path>` |
| `remove item <idx>` (out of bounds) | 1 | `Error: list index out of range` |
| `remove last item` (empty list) | 1 | `Error: list index out of range` |
| `integer value of <s> or else <dflt>` | 0 | Returns `<dflt>` (does not abort) |

---

## 6. Files Modified by WS-CORE

- `src/memelang/ir/schema.py`
- `src/memelang/ir/__init__.py`
- `src/memelang/ir/canonical.py`
- `src/memelang/analyzer/verifier.py`
- `src/memelang/runner/executor.py`
- `src/memelang/llm/heuristic.py`
- `src/memelang/llm/base.py`
- `src/memelang/llm/llama_cpp.py`
- `src/memelang/codegen/python_gen.py`
- `src/memelang/codegen/rust_gen.py`
- `src/memelang/codegen/cpp_gen.py`
- `src/memelang/codegen/go_gen.py`
- `src/memelang/codegen/c_gen.py`
- `src/memelang/codegen/ts_gen.py`
- `tests/test_ir_and_canonical.py`
- `tests/test_codegen_targets.py`
- `docs/WS-CORE-SPEC-NOTES.md` (new)
