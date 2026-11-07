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

```meme
this runs in the shell          ← optional header: program reads stdin (user input)

class my-program                ← optional class wrapper, kebab-case name

  define function helper with a, b    ← untyped params (types inferred)
    return a + b

  define function main          ← entry point; runs last, after helpers
    ...
```

- `this runs in the shell` marks the program as interactive (reads from the user).
- `class <kebab-name>` groups helper functions. It compiles to plain functions in the
  target language — it is an organizational device, not objects.
- `define function main` is the entry point. Its body becomes the top-level program.
- Indentation (2 spaces) defines block nesting. No colons or braces needed.
- `# ...` lines are comments.

---

## 3. Variables and Types

Declare with `define ... as` (expression) or `define ... from user` (input):

```meme
define count as 10
define name as "Ada"
define price as 9.99
define flag as true
define items as [1, 2, 3]
define empty_list as empty
```

Every value resolves to one of these types:

| Type | Literal example |
|---|---|
| `Int` (64-bit) | `42` |
| `Float` | `9.99` |
| `Bool` | `true` / `false` |
| `String` | `"hello"` |
| `List<Int>` / `List<Float>` / `List<String>` / `List<Bool>` | `[1, 2, 3]` |

**Type inference defaults:** untyped numbers, untyped function parameters, empty lists,
and user inputs become `Float` / `List<Float>`. Write the word *integer* / *integers* to
get `Int` behavior (`10 random integers`, `count by integer steps`). Types are checked
statically before anything runs — a type mismatch is a compile error, not a runtime
surprise.

---

## 4. Expressions and Operators

```meme
define total as a + b - c * d          # arithmetic: + - * / %
define even as n % 2 == 0              # comparisons: == != < <= > >=
define both as a > 0 and b > 0         # logic: and or
define negated as not flag             # unary: - not
```

Printing:

```meme
print "Hello, World!"
print total
print "Score: ", score                  # multiple values, space-separated
```

Reading input (requires `this runs in the shell`):

```meme
define answer from user "Pick a number? "
```

The prompt string is shown to the user; the value comes back typed as needed.

---

## 5. Control Flow

**`if` / `else`** — indentation is the block:

```meme
if score >= 90
  print "A"
else
  print "keep trying"
```

**Counted loop** — **both ends are inclusive**:

```meme
for i from 1 to 20          # i = 1, 2, ..., 20 (not 19!)
  print i
```

**For-each loop:**

```meme
for each n in numbers
  print n
```

**While loop:**

```meme
while digit_buffer > 0
  define extracted_digit as digit_buffer % 10
  define digit_buffer as digit_buffer / 10
```

---

## 6. Lists

Memelang's list verbs are the heart of the language:

```meme
define list numbers as 10 random integers between 1 and 100
define sorted_copy as empty
sort numbers into sorted_copy ascending      # copy-then-sort
sort numbers descending                      # in-place
filter numbers where item >= 50              # keep only elements passing the test
add 100 to numbers                           # append
clamp numbers between 1 and 10               # clamp every element
```

**Indexing — the one rule to memorize:** when you *say* a position in English
(`item 1`, `item 2`, `item last`), counting starts at **1**:

```meme
define first as numbers item 1        # first element
define last as sorted item last       # last element
```

When you *compute* a position with a loop counter, it is used as-is (0-based numeric):

```meme
for r from 0 to 1                     # 2x2 matrix: rows 0 and 1
  define row as transposed item r
```

**In-place mutation** (sets an element at a computed index):

```meme
set row item r to val
set numbers item i to numbers item i + 1
```

**Length:**

```meme
for k from 1 to length of identifier
  ...
```

**Copy-sorting into a new list:** `sort A into B ascending` expects `B` to be declared
as `empty` first — the compiler copies `A` into `B`, then sorts `B` in place, leaving `A`
untouched:

```meme
define sorted as empty
sort unsorted into sorted ascending
return largest from sorted
```

You can either sort in place or copy-sort and then index or use a selector (`largest from sorted`, `smallest from sorted`):

```meme
# Option A: sort in place, then index freely
sort scores descending
define top as scores item 1

# Option B: copy-sort into an empty list, then select or index
define sorted as empty
sort unsorted into sorted ascending
return largest from sorted
```

---

## 7. Strings

```meme
define c as identifier char k           # k-th character (1-based)
if c is uppercase
  ...
length of identifier                    # string length
```

---

## 8. Functions

Define helpers, then call them with `... from <args>`:

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

- Untyped parameters infer their type from use (`Float` by default; write
  `with balance as Int` style annotations or the word *integer* when you need `Int`).
- A function has **one static return type**. If one branch returns a number and another
  returns an error string, write the error branch as a failure:

```meme
define function loadFile with filepath
  if filepath is json
    define list as fromFile from filepath
    return list
  else return "Wrong File Type"
```

The `else return "<message>"` form compiles to a fail statement: it prints the message
and exits cleanly — it counts as returning on that branch, so the verifier stays happy.

**Structured English equivalent** (typed, with colons):

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

## 11. CLI Cheat Sheet

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

## 12. Teaching the Language: the `examples/` Axis

The compiler's BM25 retriever learns phrasing from `.meme` files in `examples/` that
have a paired, verified `.meme.lock` sidecar (such as the locked examples in
`examples/cs101/`, `cs102/`, `cs103/`). When you invent a phrasing the compiler doesn't
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

## 13. A Complete Worked Program

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

| I want to... | Write |
|---|---|
| Declare a variable | `define x as <expr>` |
| Read input | `define x from user "Prompt? "` |
| Print | `print x` / `print "a, ", b` |
| Branch | `if <cond>` / `else` (indentation) |
| Count 1..N inclusive | `for i from 1 to N` |
| Iterate a list | `for each n in list` |
| Repeat while | `while <cond>` |
| Sort in place | `sort list ascending` |
| Sort into a copy | `define out as empty` + `sort list into out descending` |
| Filter | `define evens as each n in list where <cond>` |
| Append | `add x to list` |
| First/last element | `list item 1` / `list item last` |
| Mutate an element | `set list item i to v` |
| Length | `length of list` |
| Char at position | `s char k` (1-based) |
| Define a function | `define function f with a, b` |
| Call it | `define r as f from a, b` |
| Fail cleanly | `else return "error message"` |
| Comment | `# this is ignored` |

Happy memeing.
