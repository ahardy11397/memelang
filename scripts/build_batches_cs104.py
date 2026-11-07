"""Batch builder for CS104 batches 3 to 7 (IDs 321..370)."""

from scripts.expand_examples import ExampleDef, process_batch


def get_batch_3() -> list[ExampleDef]:
    """Batch 3: Key=value config parsing (IDs 321..330)."""
    return [
        ExampleDef(
            id=321,
            slug="321_config_skip_comments",
            course="cs104",
            topic="text_and_data_tasks",
            title="Filter Out Comment Lines in Config",
            code="""
define list config_lines: List<String> as ["# server settings", "port=8080", "# database", "timeout=30"]
define list active_lines: List<String> as empty List<String>
for each line in config_lines
    define first_ch as slice line from 0 to 1
    if first_ch != "#"
        append line to active_lines
print "Active config directives:", length of active_lines
""",
            expected_stdout_contains="Active config directives: 2",
            feature_tags=["config", "filter", "comments", "list"],
        ),
        ExampleDef(
            id=322,
            slug="322_config_parse_key",
            course="cs104",
            topic="text_and_data_tasks",
            title="Extract Key Name from Key-Value Pair",
            code="""
function get_config_key(line: String) -> String:
    define line_len as length of string line
    define key_buf as ""
    for idx from 0 to (line_len - 1)
        define ch as slice line from idx to (idx + 1)
        if ch == "="
            return key_buf
        set key_buf to key_buf + ch
    return key_buf

define directive as "max_connections=500"
define key_name as get_config_key(directive)
print "Config key name:", key_name
""",
            expected_stdout_contains="Config key name: max_connections",
            feature_tags=["config", "parser", "function", "string_slice"],
        ),
        ExampleDef(
            id=323,
            slug="323_config_parse_value",
            course="cs104",
            topic="text_and_data_tasks",
            title="Extract Value from Key-Value Pair",
            code="""
function get_config_value(line: String) -> String:
    define line_len as length of string line
    define found_eq as false
    define val_buf as ""
    for idx from 0 to (line_len - 1)
        define ch as slice line from idx to (idx + 1)
        if found_eq
            set val_buf to val_buf + ch
        if ch == "="
            set found_eq to true
    return val_buf

define directive as "database_host=db.internal.net"
define val as get_config_value(directive)
print "Config value string:", val
""",
            expected_stdout_contains="Config value string: db.internal.net",
            feature_tags=["config", "parser", "function", "string"],
        ),
        ExampleDef(
            id=324,
            slug="324_config_detect_section_header",
            course="cs104",
            topic="text_and_data_tasks",
            title="Detect INI Section Header",
            code="""
function is_section_header(line: String) -> Bool:
    define sz as length of string line
    if sz >= 2
        define start_ch as slice line from 0 to 1
        define end_ch as slice line from (sz - 1) to sz
        if start_ch == "["
            if end_ch == "]"
                return true
    return false

define header_line as "[database_cluster]"
define normal_line as "host=localhost"
print "Is header 1:", is_section_header(header_line)
print "Is header 2:", is_section_header(normal_line)
""",
            expected_stdout_contains="Is header 1: true",
            feature_tags=["config", "ini", "section", "bool"],
        ),
        ExampleDef(
            id=325,
            slug="325_config_parse_boolean_flag",
            course="cs104",
            topic="text_and_data_tasks",
            title="Parse Boolean Configuration Value",
            code="""
function parse_bool_flag(raw_val: String) -> Bool:
    if raw_val == "true"
        return true
    if raw_val == "yes"
        return true
    if raw_val == "1"
        return true
    return false

define opt1 as parse_bool_flag("true")
define opt2 as parse_bool_flag("0")
print "Parsed flag 1:", opt1
print "Parsed flag 2:", opt2
""",
            expected_stdout_contains="Parsed flag 1: true",
            feature_tags=["config", "boolean", "flags", "branching"],
        ),
        ExampleDef(
            id=326,
            slug="326_config_fallback_default",
            course="cs104",
            topic="text_and_data_tasks",
            title="Provide Default Value for Missing Config",
            code="""
function resolve_config_param(configured_val: String, default_val: String) -> String:
    if length of string configured_val == 0
        return default_val
    return configured_val

define setting as resolve_config_param("", "https://api.domain.com")
print "Resolved endpoint:", setting
""",
            expected_stdout_contains="Resolved endpoint: https://api.domain.com",
            feature_tags=["config", "fallback", "default", "function"],
        ),
        ExampleDef(
            id=327,
            slug="327_config_parse_int_timeout",
            course="cs104",
            topic="text_and_data_tasks",
            title="Convert Digit String to Integer Timeout",
            code="""
function parse_two_digit_int(digits: String) -> Int:
    define d0 as slice digits from 0 to 1
    define d1 as slice digits from 1 to 2
    define tens: Int as 0
    define ones: Int as 0
    if d0 == "3"
        set tens to 30
    if d0 == "6"
        set tens to 60
    if d1 == "5"
        set ones to 5
    return tens + ones

define timeout_sec as parse_two_digit_int("35")
print "Timeout in seconds:", timeout_sec
""",
            expected_stdout_contains="Timeout in seconds: 35",
            feature_tags=["config", "conversion", "numeric", "timeout"],
        ),
        ExampleDef(
            id=328,
            slug="328_config_check_key_exists",
            course="cs104",
            topic="text_and_data_tasks",
            title="Search for Required Configuration Key",
            code="""
define list known_keys: List<String> as ["app_name", "environment", "log_level", "api_token"]
define target_key as "api_token"
define found_key as false
for each k in known_keys
    if k == target_key
        set found_key to true
print "API token configured:", found_key
""",
            expected_stdout_contains="API token configured: true",
            feature_tags=["config", "search", "presence", "list"],
        ),
        ExampleDef(
            id=329,
            slug="329_config_strip_inline_comment",
            course="cs104",
            topic="text_and_data_tasks",
            title="Strip Inline Comment from Config Directive",
            code="""
function trim_inline_comment(directive_text: String) -> String:
    define total_len as length of string directive_text
    define clean_part as ""
    for idx from 0 to (total_len - 1)
        define sym as slice directive_text from idx to (idx + 1)
        if sym == "#"
            return clean_part
        set clean_part to clean_part + sym
    return clean_part

define raw_directive as "cache_size=1024 # megabytes"
define cleaned_directive as trim_inline_comment(raw_directive)
print "Cleaned directive:", cleaned_directive
""",
            expected_stdout_contains="Cleaned directive: cache_size=1024 ",
            feature_tags=["config", "strip", "comment", "string_slice"],
        ),
        ExampleDef(
            id=330,
            slug="330_config_summarize_directives",
            course="cs104",
            topic="text_and_data_tasks",
            title="Summarize Total Directives by Scope",
            code="""
define list scopes: List<String> as ["prod", "dev", "prod", "prod", "test"]
define prod_count: Int as 0
for each sc in scopes
    if sc == "prod"
        set prod_count to prod_count + 1
print "Production directive count:", prod_count
""",
            expected_stdout_contains="Production directive count: 3",
            feature_tags=["config", "aggregation", "scope", "counter"],
        ),
    ]


def get_batch_4() -> list[ExampleDef]:
    """Batch 4: String cleanup and formatting (IDs 331..340)."""
    return [
        ExampleDef(
            id=331,
            slug="331_string_trim_leading_spaces",
            course="cs104",
            topic="text_and_data_tasks",
            title="Trim Leading Spaces from Text",
            code="""
function ltrim(text: String) -> String:
    define n as length of string text
    define start_idx: Int as 0
    define skipping as true
    for i from 0 to (n - 1)
        define ch as slice text from i to (i + 1)
        if skipping
            if ch != " "
                set start_idx to i
                set skipping to false
    return slice text from start_idx to n

define raw as "   payload content"
define trimmed as ltrim(raw)
print "Left trimmed text:", trimmed
""",
            expected_stdout_contains="Left trimmed text: payload content",
            feature_tags=["string", "trim", "ltrim", "loop"],
        ),
        ExampleDef(
            id=332,
            slug="332_string_trim_trailing_spaces",
            course="cs104",
            topic="text_and_data_tasks",
            title="Trim Trailing Spaces from Text",
            code="""
function rtrim(text: String) -> String:
    define n as length of string text
    define last_non_space: Int as 0
    for i from 0 to (n - 1)
        define ch as slice text from i to (i + 1)
        if ch != " "
            set last_non_space to i + 1
    return slice text from 0 to last_non_space

define raw as "server_output   "
define trimmed as rtrim(raw)
print "Right trimmed text:", trimmed
""",
            expected_stdout_contains="Right trimmed text: server_output",
            feature_tags=["string", "trim", "rtrim", "slice"],
        ),
        ExampleDef(
            id=333,
            slug="333_string_pad_left_zeros",
            course="cs104",
            topic="text_and_data_tasks",
            title="Pad String Left with Leading Zeroes",
            code="""
function pad_zeroes(input_str: String, target_len: Int) -> String:
    define cur_len as length of string input_str
    define padding as ""
    define needed as target_len - cur_len
    if needed > 0
        for step from 1 to needed
            set padding to padding + "0"
    return padding + input_str

define code as pad_zeroes("742", 6)
print "Padded zero serial:", code
""",
            expected_stdout_contains="Padded zero serial: 000742",
            feature_tags=["string", "padding", "formatting", "loop"],
        ),
        ExampleDef(
            id=334,
            slug="334_string_pad_right_spaces",
            course="cs104",
            topic="text_and_data_tasks",
            title="Pad String Right with Spaces to Fixed Width",
            code="""
function pad_right(label: String, width: Int) -> String:
    define cur_len as length of string label
    define padded as label
    define diff as width - cur_len
    if diff > 0
        for s from 1 to diff
            set padded to padded + " "
    return padded

define formatted as pad_right("TOTAL", 10)
print "Formatted label width:", length of string formatted
print "Padded output tag:", formatted + "<END>"
""",
            expected_stdout_contains="Formatted label width: 10",
            feature_tags=["string", "padding", "alignment", "table"],
        ),
        ExampleDef(
            id=335,
            slug="335_string_replace_char",
            course="cs104",
            topic="text_and_data_tasks",
            title="Replace Target Character with Replacement Character",
            code="""
function replace_char(source: String, old_c: String, new_c: String) -> String:
    define len_s as length of string source
    define result as ""
    for idx from 0 to (len_s - 1)
        define cur_c as slice source from idx to (idx + 1)
        if cur_c == old_c
            set result to result + new_c
        else
            set result to result + cur_c
    return result

define slug as replace_char("my bad file name", " ", "-")
print "Transformed slug:", slug
""",
            expected_stdout_contains="Transformed slug: my-bad-file-name",
            feature_tags=["string", "replace", "slug", "loop"],
        ),
        ExampleDef(
            id=336,
            slug="336_string_count_char_occurrences",
            course="cs104",
            topic="text_and_data_tasks",
            title="Count Occurrences of Character in String",
            code="""
function count_char(blob: String, target_c: String) -> Int:
    define n as length of string blob
    define occurrences: Int as 0
    for i from 0 to (n - 1)
        define ch as slice blob from i to (i + 1)
        if ch == target_c
            set occurrences to occurrences + 1
    return occurrences

define path_str as "/usr/local/bin/python3"
define slash_count as count_char(path_str, "/")
print "Directory depth count:", slash_count
""",
            expected_stdout_contains="Directory depth count: 4",
            feature_tags=["string", "count", "frequency", "path"],
        ),
        ExampleDef(
            id=337,
            slug="337_string_truncate_ellipsis",
            course="cs104",
            topic="text_and_data_tasks",
            title="Truncate String with Ellipsis if Overlength",
            code="""
function truncate_with_ellipsis(message: String, max_len: Int) -> String:
    define msg_len as length of string message
    if msg_len > max_len
        define truncated as slice message from 0 to (max_len - 3)
        return truncated + "..."
    return message

define long_title as "Comprehensive Architectural Overview of Distributed Storage"
define short_view as truncate_with_ellipsis(long_title, 20)
print "Truncated overview:", short_view
""",
            expected_stdout_contains="Truncated overview: Comprehensive Arc...",
            feature_tags=["string", "truncate", "ellipsis", "formatting"],
        ),
        ExampleDef(
            id=338,
            slug="338_string_remove_character",
            course="cs104",
            topic="text_and_data_tasks",
            title="Filter Out Specific Character from String",
            code="""
function strip_char(src: String, bad_c: String) -> String:
    define n as length of string src
    define clean_buf as ""
    for i from 0 to (n - 1)
        define ch as slice src from i to (i + 1)
        if ch != bad_c
            set clean_buf to clean_buf + ch
    return clean_buf

define phone as "555-019-2834"
define digits_only as strip_char(phone, "-")
print "Stripped phone digits:", digits_only
""",
            expected_stdout_contains="Stripped phone digits: 5550192834",
            feature_tags=["string", "filter", "strip", "sanitize"],
        ),
        ExampleDef(
            id=339,
            slug="339_string_repeat_char",
            course="cs104",
            topic="text_and_data_tasks",
            title="Generate String of Repeated Character",
            code="""
function repeat_char(ch: String, times: Int) -> String:
    define buffer as ""
    for step from 1 to times
        set buffer to buffer + ch
    return buffer

define divider as repeat_char("=", 12)
print "Divider banner:", divider
""",
            expected_stdout_contains="Divider banner: ============",
            feature_tags=["string", "repeat", "banner", "generator"],
        ),
        ExampleDef(
            id=340,
            slug="340_string_find_char_position",
            course="cs104",
            topic="text_and_data_tasks",
            title="Find First 0-Based Position of Character",
            code="""
function find_first(haystack: String, needle: String) -> Int:
    define n as length of string haystack
    for i from 0 to (n - 1)
        define ch as slice haystack from i to (i + 1)
        if ch == needle
            return i
    return -1

define at_pos as find_first("support@company.org", "@")
print "At symbol index:", at_pos
""",
            expected_stdout_contains="At symbol index: 7",
            feature_tags=["string", "search", "index", "first"],
        ),
    ]


def get_batch_5() -> list[ExampleDef]:
    """Batch 5: Word and text tasks (IDs 341..350)."""
    return [
        ExampleDef(
            id=341,
            slug="341_word_extract_initials",
            course="cs104",
            topic="text_and_data_tasks",
            title="Extract Initials from Full Name",
            code="""
function get_initials(full_name: String) -> String:
    define n as length of string full_name
    define initials as ""
    define take_next as true
    for i from 0 to (n - 1)
        define ch as slice full_name from i to (i + 1)
        if take_next
            if ch != " "
                set initials to initials + ch
                set take_next to false
        if ch == " "
            set take_next to true
    return initials

define person as "Grace Brewster Hopper"
define init as get_initials(person)
print "Extracted person initials:", init
""",
            expected_stdout_contains="Extracted person initials: GBH",
            feature_tags=["text", "initials", "name", "words"],
        ),
        ExampleDef(
            id=342,
            slug="342_word_count_words_in_sentence",
            course="cs104",
            topic="text_and_data_tasks",
            title="Count Total Words in Single-Spaced Sentence",
            code="""
function count_words(sentence: String) -> Int:
    define n as length of string sentence
    if n == 0
        return 0
    define spaces: Int as 0
    for i from 0 to (n - 1)
        define ch as slice sentence from i to (i + 1)
        if ch == " "
            set spaces to spaces + 1
    return spaces + 1

define text_sample as "quick brown fox jumps over lazy dog"
define total_words as count_words(text_sample)
print "Total sentence words:", total_words
""",
            expected_stdout_contains="Total sentence words: 7",
            feature_tags=["text", "word_count", "sentence", "spaces"],
        ),
        ExampleDef(
            id=343,
            slug="343_word_count_vowels",
            course="cs104",
            topic="text_and_data_tasks",
            title="Count English Vowels in String",
            code="""
function count_vowels(phrase: String) -> Int:
    define n as length of string phrase
    define vowel_count: Int as 0
    for i from 0 to (n - 1)
        define ch as slice phrase from i to (i + 1)
        if ch == "a"
            set vowel_count to vowel_count + 1
        if ch == "e"
            set vowel_count to vowel_count + 1
        if ch == "i"
            set vowel_count to vowel_count + 1
        if ch == "o"
            set vowel_count to vowel_count + 1
        if ch == "u"
            set vowel_count to vowel_count + 1
    return vowel_count

define num_vowels as count_vowels("cryptographic algorithms")
print "Total lowercase vowels:", num_vowels
""",
            expected_stdout_contains="Total lowercase vowels: 6",
            feature_tags=["text", "vowels", "counter", "frequency"],
        ),
        ExampleDef(
            id=344,
            slug="344_word_count_consonants",
            course="cs104",
            topic="text_and_data_tasks",
            title="Count Letters Excluding Vowels and Spaces",
            code="""
function count_consonants(phrase: String) -> Int:
    define n as length of string phrase
    define consonants: Int as 0
    for i from 0 to (n - 1)
        define ch as slice phrase from i to (i + 1)
        define is_vowel as false
        if ch == "a"
            set is_vowel to true
        if ch == "e"
            set is_vowel to true
        if ch == "i"
            set is_vowel to true
        if ch == "o"
            set is_vowel to true
        if ch == "u"
            set is_vowel to true
        if ch == " "
            set is_vowel to true
        if not is_vowel
            set consonants to consonants + 1
    return consonants

define total_c as count_consonants("safe lock")
print "Total consonants found:", total_c
""",
            expected_stdout_contains="Total consonants found: 5",
            feature_tags=["text", "consonants", "filter", "counter"],
        ),
        ExampleDef(
            id=345,
            slug="345_word_acronym_generator",
            course="cs104",
            topic="text_and_data_tasks",
            title="Build Acronym with Trailing Dot Format",
            code="""
define list words_list: List<String> as ["Asynchronous", "Javascript", "And", "Xml"]
define acronym as ""
for each w in words_list
    define first_letter as slice w from 0 to 1
    set acronym to acronym + first_letter + "."
print "Constructed acronym:", acronym
""",
            expected_stdout_contains="Constructed acronym: A.J.A.X.",
            feature_tags=["text", "acronym", "formatting", "list"],
        ),
        ExampleDef(
            id=346,
            slug="346_word_find_longest_length",
            course="cs104",
            topic="text_and_data_tasks",
            title="Determine Maximum Word Length in List",
            code="""
define list dictionary: List<String> as ["data", "algorithm", "tree", "verification", "node"]
define max_len: Int as 0
for each word in dictionary
    define wl as length of string word
    if wl > max_len
        set max_len to wl
print "Longest word length:", max_len
""",
            expected_stdout_contains="Longest word length: 12",
            feature_tags=["text", "max", "length", "loop"],
        ),
        ExampleDef(
            id=347,
            slug="347_word_find_first_vowel_pos",
            course="cs104",
            topic="text_and_data_tasks",
            title="Locate Index of First Vowel",
            code="""
function first_vowel_index(w: String) -> Int:
    define n as length of string w
    for i from 0 to (n - 1)
        define ch as slice w from i to (i + 1)
        if ch == "a"
            return i
        if ch == "e"
            return i
        if ch == "i"
            return i
        if ch == "o"
            return i
        if ch == "u"
            return i
    return -1

define idx as first_vowel_index("rhythm")
define idx2 as first_vowel_index("spring")
print "Vowel in rhythm:", idx
print "Vowel in spring:", idx2
""",
            expected_stdout_contains="Vowel in rhythm: -1",
            feature_tags=["text", "vowels", "search", "index"],
        ),
        ExampleDef(
            id=348,
            slug="348_word_pluralize_s",
            course="cs104",
            topic="text_and_data_tasks",
            title="Basic Regular English Pluralization Rule",
            code="""
function pluralize_word(noun: String, count: Int) -> String:
    if count == 1
        return noun
    define sz as length of string noun
    define last_ch as slice noun from (sz - 1) to sz
    if last_ch == "s"
        return noun + "es"
    return noun + "s"

define p1 as pluralize_word("item", 1)
define p2 as pluralize_word("item", 5)
define p3 as pluralize_word("bus", 2)
print "Single item:", p1
print "Multiple items:", p2
print "Plural bus:", p3
""",
            expected_stdout_contains="Single item: item",
            feature_tags=["text", "pluralize", "grammar", "rules"],
        ),
        ExampleDef(
            id=349,
            slug="349_word_reverse_character_order",
            course="cs104",
            topic="text_and_data_tasks",
            title="Reverse String Characters",
            code="""
function reverse_string(orig: String) -> String:
    define n as length of string orig
    define rev as ""
    for i from 0 to (n - 1)
        define ch as slice orig from (n - 1 - i) to (n - i)
        set rev to rev + ch
    return rev

define backwards as reverse_string("stressed")
print "Backwards word:", backwards
""",
            expected_stdout_contains="Backwards word: desserts",
            feature_tags=["text", "reverse", "palindrome", "loop"],
        ),
        ExampleDef(
            id=350,
            slug="350_word_check_is_palindrome",
            course="cs104",
            topic="text_and_data_tasks",
            title="Verify if Word is Exact Palindrome",
            code="""
function is_palindrome(text: String) -> Bool:
    define n as length of string text
    for i from 0 to (n - 1)
        define front_c as slice text from i to (i + 1)
        define back_c as slice text from (n - 1 - i) to (n - i)
        if front_c != back_c
            return false
    return true

define is_pal1 as is_palindrome("radar")
define is_pal2 as is_palindrome("rocket")
print "Radar palindrome check:", is_pal1
print "Rocket palindrome check:", is_pal2
""",
            expected_stdout_contains="Radar palindrome check: true",
            feature_tags=["text", "palindrome", "bool", "verification"],
        ),
    ]


def get_batch_6() -> list[ExampleDef]:
    """Batch 6: List manipulation and filtering (IDs 351..360)."""
    return [
        ExampleDef(
            id=351,
            slug="351_list_dedupe_adjacent",
            course="cs104",
            topic="text_and_data_tasks",
            title="Deduplicate Adjacent Identical Elements",
            code="""
define list stream: List<Int> as [1, 1, 2, 3, 3, 3, 4, 2, 2]
define list deduped: List<Int> as empty List<Int>
define total_items as length of stream
for idx from 0 to (total_items - 1)
    if idx == 0
        append stream[idx] to deduped
    else
        if stream[idx] != stream[idx - 1]
            append stream[idx] to deduped
print "Deduped list length:", length of deduped
print "First deduped item:", deduped[0]
""",
            expected_stdout_contains="Deduped list length: 5",
            feature_tags=["list", "dedup", "adjacent", "loop"],
        ),
        ExampleDef(
            id=352,
            slug="352_list_chunk_into_pairs",
            course="cs104",
            topic="text_and_data_tasks",
            title="Count Pair Chunks in Even Length List",
            code="""
define list raw_points: List<Int> as [10, 20, 30, 40, 50, 60]
define num_pairs: Int as (length of raw_points) / 2
print "Total coordinate pairs:", num_pairs
""",
            expected_stdout_contains="Total coordinate pairs: 3",
            feature_tags=["list", "chunks", "pairs", "math"],
        ),
        ExampleDef(
            id=353,
            slug="353_list_flatten_two_lists",
            course="cs104",
            topic="text_and_data_tasks",
            title="Concatenate Two Lists into Single List",
            code="""
define list sub1: List<Int> as [10, 20, 30]
define list sub2: List<Int> as [40, 50]
define list merged: List<Int> as empty List<Int>
for each a in sub1
    append a to merged
for each b in sub2
    append b to merged
print "Merged list count:", length of merged
print "Last merged element:", merged[4]
""",
            expected_stdout_contains="Merged list count: 5",
            feature_tags=["list", "flatten", "concat", "append"],
        ),
        ExampleDef(
            id=354,
            slug="354_list_reverse_in_place",
            course="cs104",
            topic="text_and_data_tasks",
            title="Reverse Elements into New List",
            code="""
define list numbers: List<Int> as [1, 2, 3, 4, 5]
define list reversed_nums: List<Int> as empty List<Int>
define n as length of numbers
for i from 0 to (n - 1)
    append numbers[n - 1 - i] to reversed_nums
print "Reversed first element:", reversed_nums[0]
print "Reversed last element:", reversed_nums[4]
""",
            expected_stdout_contains="Reversed first element: 5",
            feature_tags=["list", "reverse", "indexing", "loop"],
        ),
        ExampleDef(
            id=355,
            slug="355_list_alternate_merge",
            course="cs104",
            topic="text_and_data_tasks",
            title="Alternately Interleave Two Equal Length Lists",
            code="""
define list list_x: List<String> as ["a", "b", "c"]
define list list_y: List<String> as ["1", "2", "3"]
define list interleaved: List<String> as empty List<String>
define cnt as length of list_x
for idx from 0 to (cnt - 1)
    append list_x[idx] to interleaved
    append list_y[idx] to interleaved
print "Interleaved count:", length of interleaved
print "Item at index 1:", interleaved[1]
""",
            expected_stdout_contains="Interleaved count: 6",
            feature_tags=["list", "interleave", "zip", "alternate"],
        ),
        ExampleDef(
            id=356,
            slug="356_list_rotate_left_by_one",
            course="cs104",
            topic="text_and_data_tasks",
            title="Rotate List Left by One Position",
            code="""
define list original_queue: List<Int> as [100, 200, 300, 400]
define list rotated_queue: List<Int> as empty List<Int>
define q_len as length of original_queue
for i from 1 to (q_len - 1)
    append original_queue[i] to rotated_queue
append original_queue[0] to rotated_queue
print "Head after rotation:", rotated_queue[0]
print "Tail after rotation:", rotated_queue[3]
""",
            expected_stdout_contains="Head after rotation: 200",
            feature_tags=["list", "rotation", "queue", "loop"],
        ),
        ExampleDef(
            id=357,
            slug="357_list_element_frequency",
            course="cs104",
            topic="text_and_data_tasks",
            title="Count Frequency of Target Element in List",
            code="""
function count_freq(data: List<Int>, query: Int) -> Int:
    define freq: Int as 0
    for each v in data
        if v == query
            set freq to freq + 1
    return freq

define list scores: List<Int> as [10, 20, 20, 10, 20, 30]
define f20 as count_freq(scores, 20)
print "Frequency of target 20:", f20
""",
            expected_stdout_contains="Frequency of target 20: 3",
            feature_tags=["list", "frequency", "search", "counter"],
        ),
        ExampleDef(
            id=358,
            slug="358_list_prefix_running_sum",
            course="cs104",
            topic="text_and_data_tasks",
            title="Calculate Running Prefix Sums of List",
            code="""
define list increments: List<Int> as [5, 10, 15, 20]
define list running_sums: List<Int> as empty List<Int>
define total: Int as 0
for each inc in increments
    set total to total + inc
    append total to running_sums
print "Running sum final total:", running_sums[3]
print "Running sum count:", length of running_sums
""",
            expected_stdout_contains="Running sum final total: 50",
            feature_tags=["list", "prefix_sum", "math", "accumulator"],
        ),
        ExampleDef(
            id=359,
            slug="359_list_drop_first_n",
            course="cs104",
            topic="text_and_data_tasks",
            title="Drop First N Elements from List",
            code="""
function drop_prefix(items: List<String>, count: Int) -> List<String>:
    define list remaining: List<String> as empty List<String>
    define sz as length of items
    if count < sz
        for i from count to (sz - 1)
            append items[i] to remaining
    return remaining

define list logs: List<String> as ["skip1", "skip2", "data_a", "data_b"]
define tail_logs as drop_prefix(logs, 2)
print "Remaining items count:", length of tail_logs
print "First retained log:", tail_logs[0]
""",
            expected_stdout_contains="Remaining items count: 2",
            feature_tags=["list", "drop", "slice", "function"],
        ),
        ExampleDef(
            id=360,
            slug="360_list_check_all_positive",
            course="cs104",
            topic="text_and_data_tasks",
            title="Check if All Integer List Elements are Strictly Positive",
            code="""
function all_strictly_positive(nums: List<Int>) -> Bool:
    for each x in nums
        if x <= 0
            return false
    return true

define list dataset1: List<Int> as [12, 45, 9, 3]
define list dataset2: List<Int> as [12, 0, 9, 3]
print "Dataset 1 all positive:", all_strictly_positive(dataset1)
print "Dataset 2 all positive:", all_strictly_positive(dataset2)
""",
            expected_stdout_contains="Dataset 1 all positive: true",
            feature_tags=["list", "predicate", "all", "validation"],
        ),
    ]


def get_batch_7() -> list[ExampleDef]:
    """Batch 7: Reporting and tabular summaries (IDs 361..370)."""
    return [
        ExampleDef(
            id=361,
            slug="361_report_select_top_n",
            course="cs104",
            topic="text_and_data_tasks",
            title="Select Top N Sorted Elements for Summary",
            code="""
define list scores: List<Int> as [95, 42, 88, 12, 73, 99]
sort scores descending
define list top3: List<Int> as empty List<Int>
for i from 0 to 2
    append scores[i] to top3
print "Top score 1:", top3[0]
print "Top score 2:", top3[1]
print "Top score 3:", top3[2]
""",
            expected_stdout_contains="Top score 1: 99",
            feature_tags=["report", "sort", "top_n", "summary"],
        ),
        ExampleDef(
            id=362,
            slug="362_report_format_table_pipe_row",
            course="cs104",
            topic="text_and_data_tasks",
            title="Format Row with Markdown Table Pipes",
            code="""
function make_pipe_row(c1: String, c2: String, c3: String) -> String:
    return "| " + c1 + " | " + c2 + " | " + c3 + " |"

define row_str as make_pipe_row("CPU", "85%", "NORMAL")
print "Markdown table row:", row_str
""",
            expected_stdout_contains="Markdown table row: | CPU | 85% | NORMAL |",
            feature_tags=["report", "markdown", "table", "pipes"],
        ),
        ExampleDef(
            id=363,
            slug="363_report_progress_bar",
            course="cs104",
            topic="text_and_data_tasks",
            title="Render ASCII Progress Bar String",
            code="""
function render_progress_bar(completed: Int, total_steps: Int) -> String:
    define bar as "["
    for s from 1 to total_steps
        if s <= completed
            set bar to bar + "#"
        else
            set bar to bar + "-"
    return bar + "]"

define meter as render_progress_bar(7, 10)
print "Rendered progress bar:", meter
""",
            expected_stdout_contains="Rendered progress bar: [#######---]",
            feature_tags=["report", "progress", "ascii", "meter"],
        ),
        ExampleDef(
            id=364,
            slug="364_report_key_value_line",
            course="cs104",
            topic="text_and_data_tasks",
            title="Format Key Value Summary Line with Colon",
            code="""
function format_kv(k: String, v: String) -> String:
    return k + ": " + v

define line as format_kv("Service Status", "OPERATIONAL")
print "Generated summary line:", line
""",
            expected_stdout_contains="Generated summary line: Service Status: OPERATIONAL",
            feature_tags=["report", "key_value", "formatting", "summary"],
        ),
        ExampleDef(
            id=365,
            slug="365_report_underline_header",
            course="cs104",
            topic="text_and_data_tasks",
            title="Generate Dashed Underline for Table Header",
            code="""
function underline_text(hdr: String) -> String:
    define n as length of string hdr
    define line as ""
    for i from 1 to n
        set line to line + "-"
    return line

define title_text as "Account Summary"
define underline as underline_text(title_text)
print "Header title text:", title_text
print "Header underline line:", underline
""",
            expected_stdout_contains="Header underline line: ---------------",
            feature_tags=["report", "underline", "header", "table"],
        ),
        ExampleDef(
            id=366,
            slug="366_report_pagination_offset",
            course="cs104",
            topic="text_and_data_tasks",
            title="Calculate Page Start and End Index",
            code="""
function page_offset(page_num: Int, page_size: Int) -> Int:
    return (page_num - 1) * page_size

define offset1 as page_offset(1, 20)
define offset2 as page_offset(3, 20)
print "Page 1 start offset:", offset1
print "Page 3 start offset:", offset2
""",
            expected_stdout_contains="Page 1 start offset: 0",
            feature_tags=["report", "pagination", "offset", "math"],
        ),
        ExampleDef(
            id=367,
            slug="367_report_histogram_bar",
            course="cs104",
            topic="text_and_data_tasks",
            title="Render Histogram Character Bar for Value",
            code="""
function make_bar(label: String, magnitude: Int) -> String:
    define bar_str as label + " | "
    for step from 1 to magnitude
        set bar_str to bar_str + "*"
    return bar_str

define chart_row as make_bar("HTTP 200", 8)
print "Histogram chart row:", chart_row
""",
            expected_stdout_contains="Histogram chart row: HTTP 200 | ********",
            feature_tags=["report", "histogram", "chart", "ascii"],
        ),
        ExampleDef(
            id=368,
            slug="368_report_status_badge",
            course="cs104",
            topic="text_and_data_tasks",
            title="Construct Bracketed Status Badge",
            code="""
function make_badge(status_text: String) -> String:
    return "[" + status_text + "]"

define b1 as make_badge("PASS")
define b2 as make_badge("FAIL")
print "Test badge 1:", b1
print "Test badge 2:", b2
""",
            expected_stdout_contains="Test badge 1: [PASS]",
            feature_tags=["report", "badge", "status", "string"],
        ),
        ExampleDef(
            id=369,
            slug="369_report_aggregate_min_max_span",
            course="cs104",
            topic="text_and_data_tasks",
            title="Compute Span Between Minimum and Maximum",
            code="""
define list readings: List<Int> as [45, 12, 89, 34, 67]
sort readings ascending
define min_val as readings[0]
define max_val as readings[4]
define reading_span as max_val - min_val
print "Minimum reading:", min_val
print "Maximum reading:", max_val
print "Total span range:", reading_span
""",
            expected_stdout_contains="Total span range: 77",
            feature_tags=["report", "span", "range", "min_max"],
        ),
        ExampleDef(
            id=370,
            slug="370_report_box_enclosure",
            course="cs104",
            topic="text_and_data_tasks",
            title="Wrap Alert Text in ASCII Box Header and Footer",
            code="""
define alert_msg as "CRITICAL_ALERT"
define border as "+----------------+"
print border
print "| " + alert_msg + " |"
print border
""",
            expected_stdout_contains="| CRITICAL_ALERT |",
            feature_tags=["report", "ascii_art", "box", "alert"],
        ),
    ]


if __name__ == "__main__":
    batches = [
        (5, "Word and text tasks (initials, words, vowels, consonants, reverse)", get_batch_5()),
        (6, "List manipulation (dedup, pairs, flatten, reverse, interleave, rotate)", get_batch_6()),
        (7, "Reporting and summaries (top N, table rows, progress bar, pagination, span)", get_batch_7()),
    ]
    for b_num, desc, items in batches:
        process_batch(
            batch_num=b_num,
            axis_name="cs104",
            description=desc,
            items=items,
        )
