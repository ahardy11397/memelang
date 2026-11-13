# Memelang Cookbook – 10 Practical Recipes

Below are ready‑to‑copy Memelang snippets for common tasks. All snippets have been compiled with the offline **heuristic** provider and target **Python**, so they will work on any platform.

---

## 1. Parse a CSV line into fields
```meme
# Split a CSV line into an array of strings

define line as "2023,Apple,10"
define parts as split line by ","
print parts[0]   # → 2023
print parts[1]   # → Apple
print parts[2]   # → 10
```
---

## 2. Generate a zero‑padded ID
```meme
function pad_id(n: Int) -> String:
    define raw as text of n
    define padded as raw
    while length of string padded < 6:
        set padded to "0" + padded
    return padded

print pad_id(42)   # → 000042
```
---

## 3. Validate user input (integer prompt)
```meme
this runs in the shell

define val as read Int with prompt "Enter a positive integer: "
print "You entered: " + text of val
```
---

## 4. Safe numeric parsing with fallback
```meme
# Optional value with a default

define maybe as optional 42   # could also be `nothing`

define result as value of maybe or else 100
print text of result   # → 42 (or 100 if `nothing`)
```
---

## 5. Sorted map iteration
```meme
# Deterministic iteration over a map (keys are sorted)

define m as {"c": 3, "a": 1, "b": 2}
for each k in m:
    print k, m[k]
```
---

## 6. Optional‑safe lookup in a map
```meme

define user_roles as {"alice": "admin", "bob": "editor"}

define role as user_roles["charlie"] default "guest"
print role   # → guest
```
---

## 7. File existence check
```meme

define path as "config.yaml"
if file exists path:
    print "Config present"
else:
    print "Missing config"
```
---

## 8. Command‑line argument routing
```meme

define argc as argument count
if argc > 1:
    define sub as argument 1
    print "Running subcommand: " + sub
else:
    print "No subcommand supplied"
```
---

## 9. Exit‑code contracts
```meme
# Exit with a specific status code (0‑255 range)
if false:
    exit with code 0
else:
    exit with code 2   # signals an error condition
```
---

## 10. Multi‑module layout
Create `utils.meme`:
```meme
# utils.meme – reusable helpers
function greet(name: String) -> String:
    return "Hello, " + name
```
Main program `app.meme`:
```meme
use utils

define msg as greet("World")
print msg   # → Hello, World
```
Compile the main file; the compiler will automatically pull in `utils.meme`.
---

All recipes are verified to compile. Feel free to copy, adapt, and combine them to build richer applications.
