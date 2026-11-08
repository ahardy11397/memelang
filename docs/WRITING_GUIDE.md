# Writing Memelang — A Practical Guide

Memelang (`meme`) is a programming language written in plain English. You write a `.meme`
file, the compiler turns your English into a strictly-typed Intermediate Representation
(IR), verifies it for type errors and ambiguity, locks it into `build.lock` for
deterministic rebuilds, and emits **Python 3**, **Rust**, or **C++20**.

Designing software still takes someone who knows how to design software. Memelang just
removes the ceremony between your design and running code.

```bash
# Prereqs: Python 3.13+, uv
uv sync --extra local-gguf
uv run meme pull                        # one-time ~2GB local compiler model

uv run meme run my_program.meme --target rust
```

---

## 1. The Two Voices

Memelang accepts two dialects. Both compile to the same IR — use whichever fits the
program (you can even mix them).

### Canonical Structured English

Typed, colon-terminated blocks, works fully offline with the zero-dependency
`heuristic` provider:

```meme
# FizzBuzz in Structured English
function is_divisible(n: Int, d: Int) -> Bool:
    return n % d == 0

for i from 1 to 20:
    if is_divisible(i, 15):
        print "FizzBuzz"
    else:
        if is_divisible(i, 3):
            print "Fizz"
        else:
            if is_divisible(i, 5):
                print "Buzz"
            else:
                print i
```

### Conversational Memelang (the author's voice)

Looser English with a class/function layout. Requires an LLM provider (local GGUF,
Ollama, or Gemini — see the README's provider table):

```meme
this runs in the shell

class bank-account

  define function deposit with balance, amount
    return balance + amount

  define function withdraw with balance, amount
    if amount <= balance
      return balance - amount
    else
      return balance - amount - 10

  define function main
    define initial_balance from user "Opening balance?"
    define dep_amount from user "Deposit amount?"
    define with_amount from user "Withdrawal amount?"
    define step1 as deposit from initial_balance, dep_amount
    define final_balance as withdraw from step1, with_amount
    print final_balance
```

---

## 2. Anatomy of a Conversational Program

> **Voice note:** The conversational wrapper (`this runs in the shell`, `class <kebab-name>`,
> `define function ... with ...`) is **LLM-voice only** (requires `ollama`, `openai-local`,
> `llama-cpp`, or `gemini`). The **offline** `heuristic` parser requires Canonical Structured
> English (`function name(param: Type) -> RetType:`, `read <Type> with prompt "..."`, etc.).

```meme
this runs in the shell          ← optional header (LLM-voice only): program reads stdin

class my-program                ← optional class wrapper (LLM-voice only), kebab-case name

  define function helper with a, b    ← untyped params (LLM-voice only; types inferred)
    return a + b

  define function main          ← entry point (LLM-voice only); runs last, after helpers
    ...
```

- `this runs in the shell` marks the program as interactive (reads from the user; **LLM-voice only**).
- `class <kebab-name>` groups helper functions (**LLM-voice only**). It compiles to plain functions in the
  target language — it is an organizational device, not objects.
- `define function main` is the entry point (**LLM-voice only**). Its body becomes the top-level program.
- Indentation (2 spaces) defines block nesting. No colons or braces needed.
- `# ...` lines and inline trailing `# ...` comments (outside string literals) are ignored in both **offline** and **LLM-voice** modes.

---

## 3. Variables and Types

Declare with `define ... as` (**offline** & **LLM-voice**), `define <name>: <Type> as` (**offline**), or `define ... from user` (**LLM-voice only**):

```meme
define count as 10
define name as "Ada"
define price as 9.99
define flag as true
define items as [1, 2, 3]
define empty_list as empty                        # LLM-voice only
define list typed_empty as empty List<Int>        # offline (heuristic)
```

Mutate an existing variable with `set <name> to <expr>` (**offline** & **LLM-voice** — always use `set ... to`, never `set ... as`):

```meme
set count to count + 1
```

Every value resolves to one of these types:

| Type | Literal example |
|---|---|
| `Int` (64-bit) | `42` |
| `Float` | `9.99` |
| `Bool` | `true` / `false` |
| `String` | `"hello"` |
| `List<Int>` / `List<Float>` / `List<String>` / `List<Bool>` | `[1, 2, 3]` |

**Type inference rules by voice:**
- **LLM-voice only:** untyped numbers, untyped function parameters, bare `empty` lists,
  and `from user` inputs default to `Float` / `List<Float>`. Write the word *integer* / *integers* to
  get `Int` behavior (`10 random integers`, `count by integer steps`).
- **Offline (`heuristic` parser):** silent type defaults are forbidden. Every expression's type
  must be statically derivable from literals or declared symbols, function parameters require
  explicit `: <Type>` annotations, empty collections require explicit type parameters
  (`empty List<T>`, `empty Map<K, V>`), and user inputs require an explicit target type
  (`read <Int|Float|Bool|String> with prompt "..."`).
- Types are checked statically before anything runs — a type mismatch is a compile error, not a runtime
  surprise.

---

## 4. Expressions and Operators

```meme
define total as a + b - c * d          # arithmetic: + - * / %
define even as n % 2 == 0              # comparisons: == != < <= > >=
define both as a > 0 and b > 0         # logic: and or
define negated as not flag             # unary: - not
```

Printing (**offline** & **LLM-voice**):

```meme
print "Hello, World!"
print total
print "Score: ", score                  # multiple values, space-separated
```

Reading input:

```meme
# LLM-voice only (requires `this runs in the shell`):
define answer from user "Pick a number? "

# Offline (heuristic):
define answer: Float as read Float with prompt "Pick a number? "
```

The prompt string is shown to the user by default (or suppressed when `MEME_QUIET_PROMPTS=1` is set in the environment); the value comes back typed as requested.

---

## 5. Control Flow

**`if` / `else`** — indentation is the block (**offline** & **LLM-voice**):

```meme
if score >= 90
  print "A"
else
  print "keep trying"
```

**Counted loop** — **both ends are inclusive** (**offline** & **LLM-voice**):

```meme
for i from 1 to 20          # i = 1, 2, ..., 20 (not 19!)
  print i
```

**For-each loop** (**offline** & **LLM-voice** — must be two words `for each`; single-word `foreach` is **LLM-voice only**):

```meme
for each n in numbers
  print n
```

**While loop** (**offline** & **LLM-voice**):

```meme
while digit_buffer > 0
  define extracted_digit as digit_buffer % 10
  set digit_buffer to digit_buffer / 10
```

---

## 6. Lists

Memelang's list verbs are the heart of the language:

```meme
define list numbers as 10 random integers between 1 and 100
define sorted_copy as empty                  # LLM-voice only (offline: empty List<Int>)
sort numbers into sorted_copy ascending      # LLM-voice only (copy-then-sort)
sort numbers descending                      # offline & LLM-voice (in-place)
filter numbers where item >= 50              # offline & LLM-voice (in-place only!)
add 100 to numbers                           # offline & LLM-voice (append)
clamp numbers between 1 and 10               # offline & LLM-voice (clamp every element)
```

> **Note on `filter`:** In the IR and **offline** parser, `filter <list> where <predicate>` is
> **in-place only** — it mutates `<list>` directly. Conversational phrasings like
> `define evens as each n in list where <cond>` are **LLM-voice only** (synthesized by copying
> and filtering in place).

**Indexing:**
- **Offline (`heuristic`):** 0-based bracket indexing `numbers[0]`, `sorted[length of sorted - 1]`.
- **LLM-voice only:** when you *say* a position in English (`item 1`, `item 2`, `item last`), counting starts at **1**:

```meme
define first as numbers item 1        # LLM-voice only (offline: numbers[0])
define last as sorted item last       # LLM-voice only (offline: sorted[length of sorted - 1])
```

When you *compute* a position with a loop counter in **LLM-voice**, it is used as-is (0-based numeric):

```meme
for r from 0 to 1                     # 2x2 matrix: rows 0 and 1
  define row as transposed item r     # LLM-voice only (offline: transposed[r])
```

**In-place element mutation** (always uses `set ... to`, never `set ... as`):

```meme
# Offline (heuristic):
set row[r] to val
set numbers[i] to numbers[i] + 1

# LLM-voice only:
set row item r to val
set numbers item i to numbers item i + 1
```

**Length:**

```meme
# For lists (offline & LLM-voice):
for k from 1 to length of numbers
  ...

# For strings in offline (heuristic) mode, include the word `string`:
define n as length of string identifier
```

**Copy-sorting into a new list:**
- **Offline (`heuristic`):** copy the list first, then sort the copy in place:
  ```meme
  define list sorted as unsorted
  sort sorted ascending
  return sorted[length of sorted - 1]
  ```
- **LLM-voice only:** `sort A into B ascending` expects `B` to be declared as `empty` first — the compiler copies `A` into `B`, then sorts `B` in place, leaving `A` untouched:
  ```meme
  define sorted as empty
  sort unsorted into sorted ascending
  return largest from sorted
  ```
- **Verifier Contract Feature (`_normalize_sort_into_empty`):** Because the IR contains only an in-place `sort_collection(target)` node, an LLM synthesizing `define B as empty` followed by `sort A into B` may emit `define list B as empty List<T>`, `sort A <dir>`, and subsequent reads of `B` (with no further reads of `A` and no prior mutations of `B`). The static verifier (`verifier.py:_normalize_sort_into_empty`) explicitly normalizes this pattern into `set B to A` + `sort B <dir>` as a deterministic language-contract feature rather than raising an ambiguity diagnostic.

You can either sort in place or copy-sort and then index or use a selector (`largest from sorted`, `smallest from sorted` — **LLM-voice only**):

```meme
# Option A: sort in place, then index freely
sort scores descending
define top as scores item 1           # LLM-voice only (offline: scores[0])

# Option B: copy-sort into an empty list, then select or index (LLM-voice only)
define sorted as empty
sort unsorted into sorted ascending
return largest from sorted
```

---

## 7. Strings

```meme
# LLM-voice only:
define c as identifier char k           # k-th character (1-based)
if c is uppercase
  ...
length of identifier                    # string length (LLM-voice only without `string` keyword)

# Offline (heuristic):
define c as slice identifier from idx to idx + 1   # 0-based [idx, idx + 1)
define n as length of string identifier            # `length of string <expr>` required offline
define ok as filepath ends with ".json"            # case-insensitive suffix test (offline & LLM-voice)
```

---

## 8. Functions

**Conversational syntax (LLM-voice only):** define helpers with `define function ... with ...`, then call them with `... from <args>`:

```meme
define function withdraw with balance, amount
  if amount <= balance
    return balance - amount
  else
    return balance - amount - 10

define function main
  define result as withdraw from 100, 30
  print result
```

- In **LLM-voice only**, untyped parameters infer their type from use (`Float` by default; write
  `with balance as Int` style annotations or the word *integer* when you need `Int`).
- In **offline (`heuristic`)** mode, every parameter must carry an explicit `: <Type>` annotation.
- A function has **one static return type**. If one branch returns a number and another
  returns an error string, write the error branch as a failure:

```meme
# LLM-voice only:
define function loadFile with filepath
  if filepath is json
    define list as fromFile from filepath
    return list
  else return "Wrong File Type"

# Offline (heuristic):
function loadFile(filepath: String) -> List<Float>:
    if filepath ends with ".json":
        define list fromFile as read JSON number list from filepath
        return fromFile
    else:
        fail with "Wrong File Type"
```

The `else return "<message>"` form (**LLM-voice only**) and `fail with "<message>"` (**offline**) compile to a `fail_stmt`: it prints the message to stdout and **exits with status code 1 (non-zero)** — it counts as diverging/returning on that branch, so the static verifier stays happy.

**Structured English equivalent** (**offline** & **LLM-voice**, typed, with colons):

```meme
function withdraw(balance: Float, amount: Float) -> Float:
    if amount <= balance:
        return balance - amount
    else:
        return balance - amount - 10
```

---

## 9. Writing Unambiguous English

The compiler refuses to guess. If a sentence has two readings, it halts (exit code 2)
with numbered candidates and locks nothing. The classic example:

```meme
array = 10.random numbers

for each number in array
    sort from 1 to 10
```

compiles to a warning like:

```text
[Compiler Warning: Ambiguous Intent at Statement 2 (Line 3)]
  Did you mean:
    (1) Mutate `array` by sorting all elements in ascending order
    (2) Clamp each item in `array` between bounds and sort ascending
    (3) Generate random integers restricted to the specified range for `array` and sort
```

Resolve it once, and the choice is locked forever:

```bash
uv run meme compile array.meme --resolve 2=3 --target rust
```

**Habits that never trigger ambiguity:**

1. **Name the target of mutations.** Write `sort array ascending`, not bare
   `sort from 1 to 10`.
2. **Declare before you sort into.** `define sorted as empty` *before*
   `sort unsorted into sorted ascending`.
3. **Bound your randomness.** `10 random integers between 1 and 100`, not
   `10.random numbers`.
4. **One statement per line.** Each line should read as a single command.
5. **Prefer the verbs** (`sort`, `clamp`, `filter`, `add ... to`, `set ... item ... to`)
   over improvised phrasing — the verifier knows the verbs.
6. **Reuse variable names consistently.** The compiler auto-heals small typos, but
   don't rely on it.

---

## 10. Determinism and Lockfiles

Compiling writes `build.lock` in the current working directory by default (or to a custom
path via `--lockfile <path>`): a SHA-256 of the source plus the fully-resolved IR plus
the **Canonical Structured English** decompilation of your program. Rebuilds read the
lockfile — **zero LLM calls, zero latency** — so the same source always produces the
same output.

Inspect what the compiler understood:

```bash
uv run meme explain my_program.meme      # canonical English + lock status
uv run meme check my_program.meme        # verify without compiling
cat build.lock                           # the locked IR and canonical form
```

If you edit the `.meme` file, the SHA changes and the compiler re-synthesizes on the
next compile, then re-locks.

---

## 11. Records and Maps

Memelang supports typed user-defined records (structs) and key-value maps (dictionaries) for modeling structured data, domain entities, and API contracts.

### Records (Structs)

Define a record type with typed fields:

```meme
record User:
    id: Int
    name: String
    email: String
    is_active: Bool
```

Construct a record using `RecordName(field1=val1, field2=val2)`:

```meme
define admin as User(id=1, name="Alice", email="alice@corp.internal", is_active=true)
```

Access fields with dot notation:

```meme
print admin.name, admin.email
```

Mutate fields with `set <target>.<field> to <value>`:

```meme
set admin.is_active to false
```

Record types can be used as function parameters and return types:

```meme
record AuthResponse:
    success: Bool
    user: User

function authenticate(user_id: Int, username: String) -> AuthResponse:
    define u as User(id=user_id, name=username, email="user@corp.internal", is_active=true)
    return AuthResponse(success=true, user=u)
```

### Maps (Lookup Tables / Dictionaries)

Maps associate keys of a static type with values of a static type. Define maps with literal `{key: value, ...}` or `empty Map<KeyType, ValueType>`:

```meme
define user_roles as {"alice": "admin", "bob": "editor"}
define user_scores as empty Map<String, Int>
```

Set key-value entries:

```meme
set user_roles["charlie"] to "viewer"
set user_scores["alice"] to 100
```

Read entries with index lookup `m[key]` or provide a default fallback with `m[key] default <fallback>`:

```meme
define role as user_roles["alice"]
define guest_role as user_roles["nobody"] default "guest"
```

Check key membership with `target has key key`:

```meme
if user_roles has key "alice":
    print "Found alice"
```

All three compiler backends (Python, standalone Rust, and C++20) generate native representations (Python `@dataclass` and `dict`, Rust `struct` and `std::collections::HashMap`, C++ `struct` and `std::unordered_map`) with deterministic output formatting parity.

---

## 12. CLI Cheat Sheet

```bash
uv run meme compile app.meme --target rust      # compile (writes build.lock)
uv run meme run app.meme --target python        # compile + execute
uv run meme run app.meme --target cpp --resolve 2=3
uv run meme check app.meme                      # static check only
uv run meme explain app.meme                    # show canonical form + lock status

# Providers
uv run meme run app.meme --provider heuristic          # offline, structured English
uv run meme run app.meme --provider ollama:qwen2.5-coder:3b
uv run meme run app.meme --provider gemini:gemini-2.5-flash
```

Targets: `python`, `rust`, `cpp`. Rust output is standalone (compiles with bare
`rustc`, no Cargo.toml); C++ output is standard C++20.

---

## 13. Teaching the Language: the `examples/` Axis

The compiler's BM25 retriever learns phrasing from `.meme` files in `examples/` that
have a paired, verified `.meme.lock` sidecar (such as the locked examples in
`examples/cs101/`, `cs102/`, `cs103/`, and `examples/advanced/`). When you invent a phrasing the compiler doesn't
know, the fix is usually to **add a locked example**:

1. Write a small, canonical `.meme` file demonstrating the idiom in `examples/`.
2. Generate its verified sidecar lockfile with `--lockfile`:
   ```bash
   uv run meme check examples/cs101/my_idiom.meme --lockfile examples/cs101/my_idiom.meme.lock
   ```
3. New programs using similar phrasing now retrieve your locked example as a few-shot
   demonstration during synthesis (unlocked `.meme` files are ignored by the retriever).

The `.meme` scripts under `tests/corpus/` include deliberate typo and ambiguity
stress-test cases — don't copy phrasing from `typo` or `ambiguous` corpus scripts.

---

## 14. A Complete Worked Program

Putting it all together — input, a helper function, and a call
(verified end-to-end: `meme run --provider llama-cpp --target python`, input `88 92 79`
→ `86.33333333333333`):

```meme
this runs in the shell

class exam-scorer

  define function average3 with a, b, c
    define total as a + b + c
    return total / 3

  define function main
    define first from user "First score? "
    define second from user "Second score? "
    define third from user "Third score? "
    define top_avg as average3 from first, second, third
    print top_avg
```

Run it on any target — the lockfile guarantees the same program, the backend is your
choice:

```bash
uv run meme run exam-scorer.meme --target python
uv run meme run exam-scorer.meme --target rust
uv run meme run exam-scorer.meme --target cpp
```

**Type-matching tip:** untyped function parameters default to `Float`, so pass `Float`
values into them. If you read integers (`10 random integers`) or count with `% 10`
arithmetic, either do the arithmetic in the main body or keep the list operations and
function calls operating on the same kind of number — the verifier does not silently
widen `Int` to `Float` at call boundaries.

---

## Quick Rules Card

Each construct is labeled **offline** (supported by the zero-dependency `heuristic` parser as well as LLM providers) or **LLM-voice only** (requires `ollama`, `openai-local`, `llama-cpp`, or `gemini`).

| I want to... | Write | Voice |
|---|---|---|
| Interactive header | `this runs in the shell` | **LLM-voice only** |
| Declare a variable | `define x as <expr>` / `define x: <Type> as <expr>` | **offline** |
| Reassign a variable | `set x to <expr>` *(always `set ... to`, never `set ... as`)* | **offline** |
| Declare an empty list | `define list out as empty List<Int>` (**offline**) / `define out as empty` (**LLM-voice only**) | **offline** / **LLM-voice only** |
| Read input | `define x: <Type> as read <Int\|Float\|Bool\|String> with prompt "Prompt? "` (**offline**) / `define x from user "Prompt? "` (**LLM-voice only**) | **offline** / **LLM-voice only** |
| Print | `print x` / `print "a, ", b` | **offline** |
| Branch | `if <cond>[:]` / `else if <cond>[:]` / `else[:]` (indentation) | **offline** |
| Count 1..N inclusive | `for i from 1 to N[:]` | **offline** |
| Iterate a list | `for each n in list[:]` *(two words `for each`; `foreach` is **LLM-voice only**)* | **offline** |
| Repeat while | `while <cond>[:]` | **offline** |
| Sort in place | `sort list ascending` / `sort list descending` | **offline** |
| Sort into a copy | `define list out as list` + `sort out descending` (**offline**) / `define out as empty` + `sort list into out descending` (**LLM-voice only**; verifier normalizes `empty` + `sort` via `_normalize_sort_into_empty`) | **offline** / **LLM-voice only** |
| Filter (in-place) | `filter list where item >= 0` *(mutates `list` in place — **offline**)* / `define evens as each n in list where <cond>` (**LLM-voice only**) | **offline** / **LLM-voice only** |
| Append | `add x to list` / `append x to list` | **offline** |
| First/last element | `list[0]` / `list[length of list - 1]` (0-based, **offline**) / `list item 1` / `list item last` (1-based, **LLM-voice only**) | **offline** / **LLM-voice only** |
| Mutate an element | `set list[i] to v` (**offline**) / `set list item i to v` (**LLM-voice only**) | **offline** / **LLM-voice only** |
| List length | `length of list` | **offline** |
| String length | `length of string s` (**offline**) / `length of s` (**LLM-voice only** on strings) | **offline** / **LLM-voice only** |
| Char at position / slice | `slice s from idx to idx + 1` (0-based, **offline**) / `s char k` (1-based, **LLM-voice only**) | **offline** / **LLM-voice only** |
| Define a function | `function f(a: Int, b: Int) -> Int:` (**offline**, explicit types required) / `define function f with a, b` (**LLM-voice only**, defaults params to `Float`) | **offline** / **LLM-voice only** |
| Call a function | `define r: Int as f(a, b)` (**offline**) / `define r as f from a, b` (**LLM-voice only**) | **offline** / **LLM-voice only** |
| Define a record | `record User:\n    id: Int\n    name: String` | **offline** |
| Instantiate a record | `define u as User(id=1, name="Alice")` | **offline** |
| Access record field | `u.name` | **offline** |
| Mutate record field | `set u.name to "Bob"` | **offline** |
| Define a map | `define m as {"a": 1, "b": 2}` / `empty Map<K, V>` | **offline** |
| Map lookup / default | `m["a"]` / `m["c"] default 0` | **offline** |
| Map key test | `m has key "a"` | **offline** |
| Mutate map entry | `set m["a"] to 10` | **offline** |
| Fail (exits code 1) | `fail with "error message"` (**offline**) / `else return "error message"` (**LLM-voice only**) | **offline** / **LLM-voice only** |
| Comment (line or inline) | `# this is ignored` / `define x as 1 # inline comment` | **offline** |

Happy memeing.
