# Tutorial: Build Your First Real Memelang App

This tutorial walks you through creating a small, self‑contained Memelang program that reads a CSV of 2‑D points, computes the squared Euclidean distance for each point, and writes the results to a file. It demonstrates:
- Installing the compiler
- Defining records and functions
- Using modules (`use`)
- Working with variables, lists, and strings
- File I/O (`read string from file`, `write file`)
- Integer parsing (`integer value of` / `text of`)

## Prerequisites
```bash
# Install dependencies (Python 3.13+, uv, and a C compiler for native targets)
uv sync --extra local-gguf   # pulls the built‑in heuristic parser and optional GGUF model
uv run meme pull              # download the default ~2 GB local model (optional for LLM‑voice)
```
The tutorial uses the offline **heuristic** provider, so no LLM is required.

## Step 1: Create a module
Create `simple_math.meme` which defines a record and a helper function.
```meme
# simple_math.meme – a reusable module
record Point:
    x: Int
    y: Int

function distance_squared(p: Point) -> Int:
    return p.x * p.x + p.y * p.y
```
Save this file in the same directory as the main program.

## Step 2: Write the main program
```meme
# tutorial.meme – the application entry point
use simple_math

function parse_point(line: String) -> Point:
    define parts as split line by ","
    define x as integer value of parts[0]
    define y as integer value of parts[1]
    return Point(x=x, y=y)

define path as "points.csv"
if not (file exists path):
    print error "points.csv not found"
    exit with code 1
define content as read string from file path
define lines as split content by "\n"
define points as empty List<Point>
for each raw in lines:
    if length of string raw == 0:
        continue
    define pt as parse_point(raw)
    append pt to points
define distances as empty List<Int>
for each p in points:
    define d as distance_squared(p)
    append d to distances
# write results to a file
define out as ""
for i from 0 to length of distances - 1:
    define line as text of distances[i] + "\n"
    set out to out + line
write file "distances.txt" with out
print "Wrote distances.txt"
```
Place this file alongside `simple_math.meme`.

## Step 3: Prepare input data
Create a CSV called `points.csv` in the same directory:
```
3,4
5,12
```
Each line is `x,y`.

## Step 4: Compile and run
```bash
# Compile to Python (fast, no external toolchain required)
uv run meme compile tutorial.meme --provider heuristic --target python -o app.py
python app.py
```
You should see:
```
Wrote distances.txt
```
The generated `distances.txt` contains:
```
25
169
```
These are the squared distances (3²+4² = 25, 5²+12² = 169).

## Step 5: Build a native binary (`meme build`)

You can also build your application directly into a standalone native binary via the C11 backend:

```bash
uv run meme build tutorial.meme -o app_bin
./app_bin
```

- **Usage:** `meme build <source.meme> -o <binary_path>`
- **Compiler Requirements:** Uses standard `cc` (with `gcc` fallback) and flags `-std=c11 -O2`. Customize via `--cc <compiler>` or `--cflags "<flags>"`.
- **Exit-Code Semantics:** Exit codes from `exit with code N` propagate directly to the shell process exit code.
- **Zero-LLM Lockfile Contract:** Once locked into `build.lock` (or a custom `--lockfile`), rebuilds never invoke the LLM frontend, guaranteeing fast, reproducible builds.
- **Modules Linked:** All imported modules (`use simple_math`) are automatically linked into the single resulting native binary.

## Step 6: Testing your programs (`assert`, `meme test`, and JSON round-trip)

Memelang includes built-in test blocks and assertions so you can verify your logic and data serialization:

Create `simple_math_test.meme` alongside `simple_math.meme`:

```meme
# simple_math_test.meme
use simple_math

test distance_squared_test:
    define p: Point as Point(x=3, y=4)
    define d: Int as distance_squared(p)
    assert d == 25

test json_point_roundtrip:
    define original: Point as Point(x=10, y=20)
    write original as json to file "point.json"
    define loaded: Optional<Point> as read json record Point from file "point.json" or else nothing
    assert loaded is not nothing
    define pt: Point as value of loaded
    assert pt.x == 10
    assert pt.y == 20
```

Run your test suite across any target using `meme test`:

```bash
uv run meme test simple_math_test.meme --target python
uv run meme test simple_math_test.meme --target rust
uv run meme test simple_math_test.meme --target cpp
```

You should see:
```text
PASS simple_math_test.meme::distance_squared_test
PASS simple_math_test.meme::json_point_roundtrip
Ran 2 cases, 0 failed
```

## What you learned
- **Modules** (`use simple_math`) keep code organized.
- **Records** let you model structured data.
- **Functions** encapsulate reusable logic.
- **Lists** store collections, and `for each` iterates deterministically.
- **String toolbox** (`split`, `text of`, `integer value of`) bridges text and numbers.
- **File I/O** (`read string from file`, `write file`) lets programs interact with the filesystem.
- **Testing & Assertions** (`assert`, `test`, `meme test`) allow isolating and running test suites across backends.
- **JSON Records** (`write ... as json`, `read json record ...`) enable typed serialization and null-safe round-tripping.
- **Lockfiles** ensure the same source always produces identical output across targets.

Congratulations! You have built a real‑world Memelang application.
