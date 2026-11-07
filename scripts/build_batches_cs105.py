"""Batch builder for CS105 batches 8 to 13 (IDs 371..430)."""

from scripts.expand_examples import ExampleDef, process_batch


def get_batch_8() -> list[ExampleDef]:
    """Batch 8: Payment card validation (IDs 371..380)."""
    return [
        ExampleDef(
            id=371,
            slug="371_card_luhn_double_digit",
            course="cs105",
            topic="validation_and_checksums",
            title="Luhn Algorithm Single Digit Doubler",
            code="""
function luhn_double(d: Int) -> Int:
    define doubled as d * 2
    if doubled > 9
        return doubled - 9
    return doubled

define r1 as luhn_double(4)
define r2 as luhn_double(7)
print "Doubled 4:", r1
print "Doubled 7:", r2
""",
            expected_stdout_contains="Doubled 4: 8",
            feature_tags=["luhn", "checksum", "card", "math"],
        ),
        ExampleDef(
            id=372,
            slug="372_card_luhn_checksum_sum",
            course="cs105",
            topic="validation_and_checksums",
            title="Calculate Luhn Checksum of Digit List",
            code="""
function is_luhn_valid(digits: List<Int>) -> Bool:
    define n as length of digits
    define total: Int as 0
    for i from 0 to (n - 1)
        define pos_from_right as n - 1 - i
        define d as digits[i]
        if pos_from_right % 2 == 1
            define doubled as d * 2
            if doubled > 9
                set total to total + doubled - 9
            else
                set total to total + doubled
        else
            set total to total + d
    return total % 10 == 0

define list sample_card: List<Int> as [4, 5, 3, 9, 1, 4, 8, 8, 0, 3, 4, 3, 6, 4, 6, 7]
print "Luhn valid check:", is_luhn_valid(sample_card)
""",
            expected_stdout_contains="Luhn valid check: true",
            feature_tags=["luhn", "checksum", "validation", "card"],
        ),
        ExampleDef(
            id=373,
            slug="373_card_prefix_visa",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Visa Starting Prefix Digit 4",
            code="""
function is_visa_number(pan: String) -> Bool:
    define n as length of string pan
    if n >= 13
        if n <= 19
            define lead as slice pan from 0 to 1
            if lead == "4"
                return true
    return false

define v1 as is_visa_number("4012888888881881")
define v2 as is_visa_number("5105105105105100")
print "Visa card match 1:", v1
print "Visa card match 2:", v2
""",
            expected_stdout_contains="Visa card match 1: true",
            feature_tags=["card", "prefix", "visa", "validation"],
        ),
        ExampleDef(
            id=374,
            slug="374_card_prefix_mastercard",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Mastercard Prefix 51 Through 55",
            code="""
function is_mastercard_prefix(pan: String) -> Bool:
    define n as length of string pan
    if n == 16
        define prefix as slice pan from 0 to 2
        if prefix == "51"
            return true
        if prefix == "52"
            return true
        if prefix == "53"
            return true
        if prefix == "54"
            return true
        if prefix == "55"
            return true
    return false

define mc1 as is_mastercard_prefix("5300123456789012")
define mc2 as is_mastercard_prefix("4000123456789012")
print "Mastercard match 1:", mc1
print "Mastercard match 2:", mc2
""",
            expected_stdout_contains="Mastercard match 1: true",
            feature_tags=["card", "prefix", "mastercard", "iin"],
        ),
        ExampleDef(
            id=375,
            slug="375_card_prefix_amex",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify American Express 15-Digit Prefix 34 or 37",
            code="""
function is_amex_number(pan: String) -> Bool:
    define n as length of string pan
    if n == 15
        define prefix as slice pan from 0 to 2
        if prefix == "34"
            return true
        if prefix == "37"
            return true
    return false

define ax1 as is_amex_number("378282246310005")
define ax2 as is_amex_number("358282246310005")
print "Amex card check 1:", ax1
print "Amex card check 2:", ax2
""",
            expected_stdout_contains="Amex card check 1: true",
            feature_tags=["card", "prefix", "amex", "iin"],
        ),
        ExampleDef(
            id=376,
            slug="376_card_prefix_discover",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Discover Card Prefix 6011",
            code="""
function is_discover_card(pan: String) -> Bool:
    define n as length of string pan
    if n == 16
        define prefix as slice pan from 0 to 4
        if prefix == "6011"
            return true
    return false

define d1 as is_discover_card("6011000990139424")
define d2 as is_discover_card("6500000990139424")
print "Discover card check 1:", d1
print "Discover card check 2:", d2
""",
            expected_stdout_contains="Discover card check 1: true",
            feature_tags=["card", "prefix", "discover", "iin"],
        ),
        ExampleDef(
            id=377,
            slug="377_card_validate_pan_length",
            course="cs105",
            topic="validation_and_checksums",
            title="Validate General Payment Card Length Range",
            code="""
function is_valid_pan_length(pan: String) -> Bool:
    define n as length of string pan
    if n >= 13
        if n <= 19
            return true
    return false

print "Length 16 valid:", is_valid_pan_length("1234567890123456")
print "Length 8 valid:", is_valid_pan_length("12345678")
""",
            expected_stdout_contains="Length 16 valid: true",
            feature_tags=["card", "length", "pan", "bounds"],
        ),
        ExampleDef(
            id=378,
            slug="378_card_expiry_month_check",
            course="cs105",
            topic="validation_and_checksums",
            title="Validate Expiration Month Between 1 and 12",
            code="""
function is_valid_expiry_month(m_str: String) -> Bool:
    define list valid_months: List<String> as ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
    for each m in valid_months
        if m == m_str
            return true
    return false

print "Month 09 valid:", is_valid_expiry_month("09")
print "Month 13 valid:", is_valid_expiry_month("13")
""",
            expected_stdout_contains="Month 09 valid: true",
            feature_tags=["card", "expiry", "month", "validation"],
        ),
        ExampleDef(
            id=379,
            slug="379_card_expiry_not_expired",
            course="cs105",
            topic="validation_and_checksums",
            title="Check If Expiration Year is Current or Future",
            code="""
function is_future_year(exp_year: Int, current_year: Int) -> Bool:
    return exp_year >= current_year

define valid_future as is_future_year(2028, 2026)
define expired_past as is_future_year(2024, 2026)
print "Card not expired 1:", valid_future
print "Card not expired 2:", expired_past
""",
            expected_stdout_contains="Card not expired 1: true",
            feature_tags=["card", "expiry", "year", "comparison"],
        ),
        ExampleDef(
            id=380,
            slug="380_card_cvv_length_check",
            course="cs105",
            topic="validation_and_checksums",
            title="Validate Security Code CVV Length",
            code="""
function is_valid_cvv(cvv: String, is_amex: Bool) -> Bool:
    define n as length of string cvv
    if is_amex
        return n == 4
    return n == 3

print "Standard CVV 3 digits:", is_valid_cvv("842", false)
print "Amex 4 digits:", is_valid_cvv("1234", true)
print "Standard bad CVV:", is_valid_cvv("12", false)
""",
            expected_stdout_contains="Standard CVV 3 digits: true",
            feature_tags=["card", "cvv", "security", "length"],
        ),
    ]


def get_batch_9() -> list[ExampleDef]:
    """Batch 9: ISBN and barcode checksums (IDs 381..390)."""
    return [
        ExampleDef(
            id=381,
            slug="381_isbn10_checksum_calculate",
            course="cs105",
            topic="validation_and_checksums",
            title="Calculate ISBN-10 Weighted Checksum",
            code="""
function isbn10_weight_sum(digits: List<Int>) -> Int:
    define total: Int as 0
    for i from 0 to 8
        define weight as 10 - i
        set total to total + (digits[i] * weight)
    return total

define list isbn_nine: List<Int> as [0, 3, 0, 6, 4, 0, 6, 1, 5]
define sum_val as isbn10_weight_sum(isbn_nine)
print "ISBN-10 weighted total:", sum_val
""",
            expected_stdout_contains="ISBN-10 weighted total: 130",
            feature_tags=["isbn10", "checksum", "weight", "math"],
        ),
        ExampleDef(
            id=382,
            slug="382_isbn10_check_digit_verify",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify ISBN-10 Check Digit Mod 11",
            code="""
function is_isbn10_valid(digits: List<Int>, check_digit: Int) -> Bool:
    define sum_weights: Int as 0
    for i from 0 to 8
        set sum_weights to sum_weights + (digits[i] * (10 - i))
    set sum_weights to sum_weights + check_digit
    return sum_weights % 11 == 0

define list d_list: List<Int> as [0, 3, 0, 6, 4, 0, 6, 1, 5]
print "ISBN-10 valid check digit:", is_isbn10_valid(d_list, 2)
""",
            expected_stdout_contains="ISBN-10 valid check digit: true",
            feature_tags=["isbn10", "check_digit", "mod11", "validation"],
        ),
        ExampleDef(
            id=383,
            slug="383_isbn13_calculate_check_digit",
            course="cs105",
            topic="validation_and_checksums",
            title="Compute ISBN-13 Check Digit Alternating 1 and 3",
            code="""
function isbn13_check_digit(d: List<Int>) -> Int:
    define total: Int as 0
    for i from 0 to 11
        if i % 2 == 0
            set total to total + d[i]
        else
            set total to total + (d[i] * 3)
    define remainder as total % 10
    if remainder == 0
        return 0
    return 10 - remainder

define list prefix12: List<Int> as [9, 7, 8, 0, 3, 0, 6, 4, 0, 6, 1, 5]
define cd as isbn13_check_digit(prefix12)
print "Calculated ISBN-13 check digit:", cd
""",
            expected_stdout_contains="Calculated ISBN-13 check digit: 7",
            feature_tags=["isbn13", "check_digit", "barcode", "math"],
        ),
        ExampleDef(
            id=384,
            slug="384_isbn13_validate_full_code",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Complete 13-Digit ISBN Code",
            code="""
function is_isbn13_valid(d: List<Int>) -> Bool:
    define total: Int as 0
    for i from 0 to 12
        if i % 2 == 0
            set total to total + d[i]
        else
            set total to total + (d[i] * 3)
    return total % 10 == 0

define list code13: List<Int> as [9, 7, 8, 0, 1, 3, 1, 4, 9, 5, 0, 5, 0]
print "ISBN-13 verification:", is_isbn13_valid(code13)
""",
            expected_stdout_contains="ISBN-13 verification: true",
            feature_tags=["isbn13", "validation", "full_code", "math"],
        ),
        ExampleDef(
            id=385,
            slug="385_ean8_check_digit_calc",
            course="cs105",
            topic="validation_and_checksums",
            title="Calculate EAN-8 Barcode Check Digit",
            code="""
function ean8_check_digit(d7: List<Int>) -> Int:
    define total: Int as 0
    for i from 0 to 6
        if i % 2 == 0
            set total to total + (d7[i] * 3)
        else
            set total to total + d7[i]
    define rem as total % 10
    if rem == 0
        return 0
    return 10 - rem

define list b7: List<Int> as [7, 3, 5, 1, 3, 5, 3]
define ean_cd as ean8_check_digit(b7)
print "EAN-8 check digit:", ean_cd
""",
            expected_stdout_contains="EAN-8 check digit: 7",
            feature_tags=["ean8", "barcode", "check_digit", "retail"],
        ),
        ExampleDef(
            id=386,
            slug="386_upc_a_check_digit",
            course="cs105",
            topic="validation_and_checksums",
            title="Calculate UPC-A 12-Digit Product Check Digit",
            code="""
function upc_check_digit(d11: List<Int>) -> Int:
    define odd_sum: Int as 0
    define even_sum: Int as 0
    for i from 0 to 10
        if i % 2 == 0
            set odd_sum to odd_sum + d11[i]
        else
            set even_sum to even_sum + d11[i]
    define total as (odd_sum * 3) + even_sum
    define rem as total % 10
    if rem == 0
        return 0
    return 10 - rem

define list upc11: List<Int> as [0, 3, 6, 0, 0, 0, 2, 4, 1, 4, 5]
define upc_cd as upc_check_digit(upc11)
print "Calculated UPC-A check digit:", upc_cd
""",
            expected_stdout_contains="Calculated UPC-A check digit: 7",
            feature_tags=["upc", "barcode", "retail", "check_digit"],
        ),
        ExampleDef(
            id=387,
            slug="387_parity_even_bit_compute",
            course="cs105",
            topic="validation_and_checksums",
            title="Compute Even Parity Bit for Byte",
            code="""
function compute_even_parity(bits: List<Int>) -> Int:
    define count_ones: Int as 0
    for each b in bits
        if b == 1
            set count_ones to count_ones + 1
    if count_ones % 2 == 1
        return 1
    return 0

define list byte_data: List<Int> as [1, 0, 1, 1, 0, 0, 1]
define p_bit as compute_even_parity(byte_data)
print "Computed parity bit:", p_bit
""",
            expected_stdout_contains="Computed parity bit: 0",
            feature_tags=["parity", "bitwise", "checksum", "data_link"],
        ),
        ExampleDef(
            id=388,
            slug="388_mod11_tax_id_check",
            course="cs105",
            topic="validation_and_checksums",
            title="Modulus 11 Checksum Verification",
            code="""
function verify_mod11(digits: List<Int>, weights: List<Int>, check_val: Int) -> Bool:
    define n as length of digits
    define total: Int as 0
    for i from 0 to (n - 1)
        set total to total + (digits[i] * weights[i])
    define rem as total % 11
    return rem == check_val

define list id_nums: List<Int> as [2, 7, 1, 8, 2, 8]
define list id_w: List<Int> as [7, 6, 5, 4, 3, 2]
print "Mod 11 valid check:", verify_mod11(id_nums, id_w, 5)
""",
            expected_stdout_contains="Mod 11 valid check: true",
            feature_tags=["mod11", "checksum", "tax_id", "math"],
        ),
        ExampleDef(
            id=389,
            slug="389_fletcher_simple_checksum",
            course="cs105",
            topic="validation_and_checksums",
            title="Calculate 8-Bit Fletcher-Style Cumulative Checksum",
            code="""
function simple_fletcher_sum(data: List<Int>) -> Int:
    define sum1: Int as 0
    define sum2: Int as 0
    for each b in data
        set sum1 to (sum1 + b) % 255
        set sum2 to (sum2 + sum1) % 255
    return sum1 + sum2

define list chunk: List<Int> as [10, 20, 30, 40]
define f_sum as simple_fletcher_sum(chunk)
print "Fletcher checksum result:", f_sum
""",
            expected_stdout_contains="Fletcher checksum result: 300",
            feature_tags=["fletcher", "checksum", "integrity", "accumulator"],
        ),
        ExampleDef(
            id=390,
            slug="390_xor_byte_block_checksum",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Longitudinal Redundancy Parity Sum",
            code="""
function longitudinal_sum(bytes_arr: List<Int>) -> Int:
    define acc: Int as 0
    for each b in bytes_arr
        set acc to (acc + b) % 256
    return acc

define list packet_payload: List<Int> as [65, 66, 67, 10]
define lrc as longitudinal_sum(packet_payload)
print "Longitudinal sum result:", lrc
""",
            expected_stdout_contains="Longitudinal sum result: 208",
            feature_tags=["checksum", "lrc", "packet", "networking"],
        ),
    ]


def get_batch_10() -> list[ExampleDef]:
    """Batch 10: Email structure validation (IDs 391..400)."""
    return [
        ExampleDef(
            id=391,
            slug="391_email_single_at_symbol",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Exactly One At Sign in Email",
            code="""
function has_single_at(email: String) -> Bool:
    define n as length of string email
    define at_count: Int as 0
    for i from 0 to (n - 1)
        define ch as slice email from i to (i + 1)
        if ch == "@"
            set at_count to at_count + 1
    return at_count == 1

print "Valid single at:", has_single_at("user@domain.com")
print "Invalid multiple at:", has_single_at("user@@domain.com")
print "Missing at:", has_single_at("userdomain.com")
""",
            expected_stdout_contains="Valid single at: true",
            feature_tags=["email", "validation", "at_symbol", "syntax"],
        ),
        ExampleDef(
            id=392,
            slug="392_email_non_empty_parts",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Non-Empty User and Domain Parts",
            code="""
function check_email_parts(email: String) -> Bool:
    define n as length of string email
    define at_idx: Int as -1
    for i from 0 to (n - 1)
        define ch as slice email from i to (i + 1)
        if ch == "@"
            set at_idx to i
    if at_idx <= 0
        return false
    if at_idx >= (n - 1)
        return false
    return true

print "Standard address valid:", check_email_parts("admin@server.org")
print "Empty user invalid:", check_email_parts("@server.org")
print "Empty domain invalid:", check_email_parts("admin@")
""",
            expected_stdout_contains="Standard address valid: true",
            feature_tags=["email", "validation", "user_part", "domain"],
        ),
        ExampleDef(
            id=393,
            slug="393_email_domain_has_dot",
            course="cs105",
            topic="validation_and_checksums",
            title="Check If Email Domain Part Contains Dot",
            code="""
function domain_has_dot(domain: String) -> Bool:
    define n as length of string domain
    for i from 0 to (n - 1)
        define ch as slice domain from i to (i + 1)
        if ch == "."
            return true
    return false

print "Domain with dot:", domain_has_dot("example.com")
print "Domain without dot:", domain_has_dot("localhost")
""",
            expected_stdout_contains="Domain with dot: true",
            feature_tags=["email", "domain", "dot", "dns"],
        ),
        ExampleDef(
            id=394,
            slug="394_email_no_spaces",
            course="cs105",
            topic="validation_and_checksums",
            title="Disallow Whitespace in Email Address",
            code="""
function has_no_whitespace(text: String) -> Bool:
    define n as length of string text
    for i from 0 to (n - 1)
        define ch as slice text from i to (i + 1)
        if ch == " "
            return false
    return true

print "No whitespace check 1:", has_no_whitespace("user@domain.com")
print "No whitespace check 2:", has_no_whitespace("user name@domain.com")
""",
            expected_stdout_contains="No whitespace check 1: true",
            feature_tags=["email", "whitespace", "sanitization", "rfc"],
        ),
        ExampleDef(
            id=395,
            slug="395_email_no_consecutive_dots",
            course="cs105",
            topic="validation_and_checksums",
            title="Reject Consecutive Dots in Email",
            code="""
function has_consecutive_dots(s: String) -> Bool:
    define n as length of string s
    if n >= 2
        for i from 0 to (n - 2)
            define pair as slice s from i to (i + 2)
            if pair == ".."
                return true
    return false

print "Has double dot 1:", has_consecutive_dots("john..doe@domain.com")
print "Has double dot 2:", has_consecutive_dots("john.doe@domain.com")
""",
            expected_stdout_contains="Has double dot 1: true",
            feature_tags=["email", "dots", "format", "consecutive"],
        ),
        ExampleDef(
            id=396,
            slug="396_email_tld_minimum_length",
            course="cs105",
            topic="validation_and_checksums",
            title="Validate Top Level Domain Minimum Length",
            code="""
function is_valid_tld_len(tld: String) -> Bool:
    define sz as length of string tld
    return sz >= 2

print "TLD org valid:", is_valid_tld_len("org")
print "TLD io valid:", is_valid_tld_len("io")
print "TLD single x invalid:", is_valid_tld_len("x")
""",
            expected_stdout_contains="TLD org valid: true",
            feature_tags=["email", "tld", "dns", "bounds"],
        ),
        ExampleDef(
            id=397,
            slug="397_email_no_leading_trailing_dots",
            course="cs105",
            topic="validation_and_checksums",
            title="Disallow Leading or Trailing Dots in Username",
            code="""
function user_dots_safe(user: String) -> Bool:
    define n as length of string user
    if n == 0
        return false
    define first_ch as slice user from 0 to 1
    define last_ch as slice user from (n - 1) to n
    if first_ch == "."
        return false
    if last_ch == "."
        return false
    return true

print "Safe user dots 1:", user_dots_safe("alex.smith")
print "Safe user dots 2:", user_dots_safe(".alex")
print "Safe user dots 3:", user_dots_safe("alex.")
""",
            expected_stdout_contains="Safe user dots 1: true",
            feature_tags=["email", "username", "dots", "validation"],
        ),
        ExampleDef(
            id=398,
            slug="398_email_disallow_special_characters",
            course="cs105",
            topic="validation_and_checksums",
            title="Disallow Forbidden Characters in Simple Email",
            code="""
function has_forbidden_chars(s: String) -> Bool:
    define n as length of string s
    for i from 0 to (n - 1)
        define ch as slice s from i to (i + 1)
        if ch == ";"
            return true
        if ch == ":"
            return true
        if ch == "<"
            return true
        if ch == ">"
            return true
        if ch == ","
            return true
    return false

print "Forbidden in clean:", has_forbidden_chars("hello@world.com")
print "Forbidden in bad:", has_forbidden_chars("hello<bad>@world.com")
""",
            expected_stdout_contains="Forbidden in clean: false",
            feature_tags=["email", "special_characters", "security", "sanitization"],
        ),
        ExampleDef(
            id=399,
            slug="399_email_extract_domain_name",
            course="cs105",
            topic="validation_and_checksums",
            title="Extract Domain Substring Following At Sign",
            code="""
function extract_email_domain(addr: String) -> String:
    define n as length of string addr
    define found_at as false
    define domain_buf as ""
    for i from 0 to (n - 1)
        define ch as slice addr from i to (i + 1)
        if found_at
            set domain_buf to domain_buf + ch
        if ch == "@"
            set found_at to true
    return domain_buf

define d as extract_email_domain("ops-alert@infra.company.com")
print "Extracted domain:", d
""",
            expected_stdout_contains="Extracted domain: infra.company.com",
            feature_tags=["email", "domain", "extraction", "string"],
        ),
        ExampleDef(
            id=400,
            slug="400_email_composite_validator",
            course="cs105",
            topic="validation_and_checksums",
            title="Combined Multi-Check Simple Email Validator",
            code="""
function is_email_valid_simple(email: String) -> Bool:
    define n as length of string email
    if n < 6
        return false
    define at_count: Int as 0
    define has_dot: Bool as false
    for i from 0 to (n - 1)
        define ch as slice email from i to (i + 1)
        if ch == " "
            return false
        if ch == "@"
            set at_count to at_count + 1
        if ch == "."
            set has_dot to true
    if at_count != 1
        return false
    if not has_dot
        return false
    return true

print "Valid email composite:", is_email_valid_simple("dev@test.io")
print "Invalid email composite:", is_email_valid_simple("dev test.io")
""",
            expected_stdout_contains="Valid email composite: true",
            feature_tags=["email", "composite", "validator", "pipeline"],
        ),
    ]


def get_batch_11() -> list[ExampleDef]:
    """Batch 11: Password policy rules (IDs 401..410)."""
    return [
        ExampleDef(
            id=401,
            slug="401_pwd_minimum_length_check",
            course="cs105",
            topic="validation_and_checksums",
            title="Enforce Minimum Password Length",
            code="""
function meets_min_length(pwd: String, min_len: Int) -> Bool:
    return length of string pwd >= min_len

print "Length check 8 char:", meets_min_length("S3cret!A", 8)
print "Length check 5 char:", meets_min_length("short", 8)
""",
            expected_stdout_contains="Length check 8 char: true",
            feature_tags=["password", "length", "policy", "security"],
        ),
        ExampleDef(
            id=402,
            slug="402_pwd_contains_numeric_digit",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Password Contains at Least One Digit",
            code="""
function has_digit(pwd: String) -> Bool:
    define n as length of string pwd
    for i from 0 to (n - 1)
        define ch as slice pwd from i to (i + 1)
        if ch == "0"
            return true
        if ch == "1"
            return true
        if ch == "2"
            return true
        if ch == "3"
            return true
        if ch == "4"
            return true
        if ch == "5"
            return true
        if ch == "6"
            return true
        if ch == "7"
            return true
        if ch == "8"
            return true
        if ch == "9"
            return true
    return false

print "Has digit in secret9:", has_digit("secret9")
print "Has digit in secret:", has_digit("secret")
""",
            expected_stdout_contains="Has digit in secret9: true",
            feature_tags=["password", "digit", "policy", "verification"],
        ),
        ExampleDef(
            id=403,
            slug="403_pwd_contains_uppercase_letter",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Password Contains Uppercase Letter",
            code="""
function has_uppercase(pwd: String) -> Bool:
    define list uppers: List<String> as ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"]
    define n as length of string pwd
    for i from 0 to (n - 1)
        define ch as slice pwd from i to (i + 1)
        for each u in uppers
            if ch == u
                return true
    return false

print "Has upper in Alpha1:", has_uppercase("Alpha1")
print "Has upper in lower1:", has_uppercase("lower1")
""",
            expected_stdout_contains="Has upper in Alpha1: true",
            feature_tags=["password", "uppercase", "policy", "security"],
        ),
        ExampleDef(
            id=404,
            slug="404_pwd_contains_special_symbol",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Password Contains Special Character",
            code="""
function has_special_symbol(pwd: String) -> Bool:
    define n as length of string pwd
    for i from 0 to (n - 1)
        define ch as slice pwd from i to (i + 1)
        if ch == "!"
            return true
        if ch == "@"
            return true
        if ch == "#"
            return true
        if ch == "$"
            return true
        if ch == "%"
            return true
        if ch == "&"
            return true
        if ch == "*"
            return true
    return false

print "Symbol check safe#:", has_special_symbol("safe#pass")
print "Symbol check safepass:", has_special_symbol("safepass")
""",
            expected_stdout_contains="Symbol check safe#: true",
            feature_tags=["password", "symbols", "policy", "security"],
        ),
        ExampleDef(
            id=405,
            slug="405_pwd_disallow_spaces",
            course="cs105",
            topic="validation_and_checksums",
            title="Reject Passwords Containing Space Characters",
            code="""
function contains_no_spaces(pwd: String) -> Bool:
    define n as length of string pwd
    for i from 0 to (n - 1)
        define ch as slice pwd from i to (i + 1)
        if ch == " "
            return false
    return true

print "No spaces in clean_pass:", contains_no_spaces("clean_pass123")
print "No spaces in space pass:", contains_no_spaces("space pass123")
""",
            expected_stdout_contains="No spaces in clean_pass: true",
            feature_tags=["password", "spaces", "policy", "sanitization"],
        ),
        ExampleDef(
            id=406,
            slug="406_pwd_disallow_common_blacklist",
            course="cs105",
            topic="validation_and_checksums",
            title="Check Password Against Blacklist of Common Passwords",
            code="""
function is_blacklisted(pwd: String) -> Bool:
    define list common: List<String> as ["password", "123456", "admin123", "qwerty", "welcome1"]
    for each bad in common
        if bad == pwd
            return true
    return false

print "Blacklist check 123456:", is_blacklisted("123456")
print "Blacklist check custom_pass:", is_blacklisted("custom_pass")
""",
            expected_stdout_contains="Blacklist check 123456: true",
            feature_tags=["password", "blacklist", "dictionary", "security"],
        ),
        ExampleDef(
            id=407,
            slug="407_pwd_calculate_strength_score",
            course="cs105",
            topic="validation_and_checksums",
            title="Calculate Multi-Factor Password Strength Score",
            code="""
function password_score(pwd: String) -> Int:
    define score: Int as 0
    define n as length of string pwd
    if n >= 8
        set score to score + 1
    if n >= 12
        set score to score + 1
    define has_dig as false
    define has_sym as false
    for i from 0 to (n - 1)
        define ch as slice pwd from i to (i + 1)
        if ch == "1"
            set has_dig to true
        if ch == "!"
            set has_sym to true
    if has_dig
        set score to score + 1
    if has_sym
        set score to score + 1
    return score

define s1 as password_score("V3ryLongSecret!1")
print "Password score result:", s1
""",
            expected_stdout_contains="Password score result: 4",
            feature_tags=["password", "score", "strength", "metrics"],
        ),
        ExampleDef(
            id=408,
            slug="408_pwd_maximum_length_bounds",
            course="cs105",
            topic="validation_and_checksums",
            title="Enforce Upper Limit on Password Length",
            code="""
function within_max_length(pwd: String, max_limit: Int) -> Bool:
    return length of string pwd <= max_limit

print "Max limit 32 check 1:", within_max_length("normal_password", 32)
print "Max limit 10 check 2:", within_max_length("this_password_is_way_too_long", 10)
""",
            expected_stdout_contains="Max limit 32 check 1: true",
            feature_tags=["password", "max_length", "bounds", "dos_prevention"],
        ),
        ExampleDef(
            id=409,
            slug="409_pwd_disallow_username_match",
            course="cs105",
            topic="validation_and_checksums",
            title="Reject Password Identical to Username",
            code="""
function password_differs_from_user(pwd: String, user: String) -> Bool:
    return pwd != user

print "Differs test 1:", password_differs_from_user("secure99!", "bob")
print "Differs test 2:", password_differs_from_user("alice", "alice")
""",
            expected_stdout_contains="Differs test 1: true",
            feature_tags=["password", "username", "policy", "security"],
        ),
        ExampleDef(
            id=410,
            slug="410_pwd_composite_policy_gate",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Combined Password Meets All Baseline Policies",
            code="""
function passes_all_policies(pwd: String) -> Bool:
    define n as length of string pwd
    if n < 8
        return false
    if n > 64
        return false
    define has_num as false
    for i from 0 to (n - 1)
        define ch as slice pwd from i to (i + 1)
        if ch == " "
            return false
        if ch == "9"
            set has_num to true
    return has_num

print "Policy gate pass:", passes_all_policies("Str0ngVault9")
print "Policy gate fail:", passes_all_policies("short")
""",
            expected_stdout_contains="Policy gate pass: true",
            feature_tags=["password", "composite", "policy", "gate"],
        ),
    ]


def get_batch_12() -> list[ExampleDef]:
    """Batch 12: Identifiers, phone numbers & UUIDs (IDs 411..420)."""
    return [
        ExampleDef(
            id=411,
            slug="411_phone_e164_leading_plus",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify International E.164 Leading Plus Sign",
            code="""
function is_e164_format(phone: String) -> Bool:
    define n as length of string phone
    if n >= 8
        if n <= 16
            define first_ch as slice phone from 0 to 1
            if first_ch == "+"
                return true
    return false

print "E.164 plus check 1:", is_e164_format("+14155552671")
print "E.164 plus check 2:", is_e164_format("14155552671")
""",
            expected_stdout_contains="E.164 plus check 1: true",
            feature_tags=["phone", "e164", "international", "prefix"],
        ),
        ExampleDef(
            id=412,
            slug="412_phone_us_10_digit_length",
            course="cs105",
            topic="validation_and_checksums",
            title="Validate US 10-Digit Standard Phone Length",
            code="""
function is_us_10_digit(num_str: String) -> Bool:
    return length of string num_str == 10

print "US 10 digit check 1:", is_us_10_digit("4155552671")
print "US 10 digit check 2:", is_us_10_digit("5552671")
""",
            expected_stdout_contains="US 10 digit check 1: true",
            feature_tags=["phone", "us_format", "nanp", "length"],
        ),
        ExampleDef(
            id=413,
            slug="413_phone_area_code_not_zero_or_one",
            course="cs105",
            topic="validation_and_checksums",
            title="Enforce NANP Area Code Leading Digit Not 0 or 1",
            code="""
function is_valid_nanp_area_code(area_code: String) -> Bool:
    define first_ch as slice area_code from 0 to 1
    if first_ch == "0"
        return false
    if first_ch == "1"
        return false
    return true

print "Area code 415 valid:", is_valid_nanp_area_code("415")
print "Area code 012 invalid:", is_valid_nanp_area_code("012")
""",
            expected_stdout_contains="Area code 415 valid: true",
            feature_tags=["phone", "area_code", "nanp", "telephony"],
        ),
        ExampleDef(
            id=414,
            slug="414_uuid_total_length_check",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Standard UUID String Length Exactly 36",
            code="""
function is_uuid_length(id_str: String) -> Bool:
    return length of string id_str == 36

define sample_uuid as "123e4567-e89b-12d3-a456-426614174000"
print "UUID length 36 check:", is_uuid_length(sample_uuid)
""",
            expected_stdout_contains="UUID length 36 check: true",
            feature_tags=["uuid", "length", "identifier", "validation"],
        ),
        ExampleDef(
            id=415,
            slug="415_uuid_hyphen_positions",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Standard UUID Hyphen Positions",
            code="""
function has_correct_uuid_hyphens(uuid: String) -> Bool:
    define n as length of string uuid
    if n == 36
        define h1 as slice uuid from 8 to 9
        define h2 as slice uuid from 13 to 14
        define h3 as slice uuid from 18 to 19
        define h4 as slice uuid from 23 to 24
        if h1 == "-"
            if h2 == "-"
                if h3 == "-"
                    if h4 == "-"
                        return true
    return false

define valid_u as "f47ac10b-58cc-4372-a567-0e02b2c3d479"
print "UUID hyphen layout check:", has_correct_uuid_hyphens(valid_u)
""",
            expected_stdout_contains="UUID hyphen layout check: true",
            feature_tags=["uuid", "hyphens", "layout", "rfc4122"],
        ),
        ExampleDef(
            id=416,
            slug="416_uuid_version_four_marker",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify UUID Version 4 Nibble Marker",
            code="""
function is_uuid_v4(uuid: String) -> Bool:
    define n as length of string uuid
    if n == 36
        define ver_char as slice uuid from 14 to 15
        return ver_char == "4"
    return false

define u4 as "c9a646d3-9c61-4cc9-bc19-4786f4cc40f4"
print "UUID v4 marker check:", is_uuid_v4(u4)
""",
            expected_stdout_contains="UUID v4 marker check: true",
            feature_tags=["uuid", "version4", "rfc4122", "inspection"],
        ),
        ExampleDef(
            id=417,
            slug="417_hex_string_validate_chars",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Hexadecimal Character Representation",
            code="""
function is_valid_hex_digit(ch: String) -> Bool:
    define list hex_chars: List<String> as ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "a", "b", "c", "d", "e", "f", "A", "B", "C", "D", "E", "F"]
    for each h in hex_chars
        if ch == h
            return true
    return false

print "Hex char f valid:", is_valid_hex_digit("f")
print "Hex char g invalid:", is_valid_hex_digit("g")
""",
            expected_stdout_contains="Hex char f valid: true",
            feature_tags=["hex", "validation", "digits", "char"],
        ),
        ExampleDef(
            id=418,
            slug="418_slug_format_validator",
            course="cs105",
            topic="validation_and_checksums",
            title="Validate URL Slug Format No Upper or Space",
            code="""
function is_clean_slug(slug_str: String) -> Bool:
    define n as length of string slug_str
    if n == 0
        return false
    for i from 0 to (n - 1)
        define ch as slice slug_str from i to (i + 1)
        if ch == " "
            return false
        if ch == "_"
            return false
    return true

print "Clean slug 1:", is_clean_slug("article-slug-format")
print "Clean slug 2:", is_clean_slug("article slug format")
""",
            expected_stdout_contains="Clean slug 1: true",
            feature_tags=["slug", "url", "formatting", "clean"],
        ),
        ExampleDef(
            id=419,
            slug="419_mac_address_colon_count",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Colon Separators in Hardware MAC Address",
            code="""
function is_mac_format(mac: String) -> Bool:
    define n as length of string mac
    if n == 17
        define colons: Int as 0
        for i from 0 to (n - 1)
            define ch as slice mac from i to (i + 1)
            if ch == ":"
                set colons to colons + 1
        return colons == 5
    return false

define mac_addr as "00:1A:2B:3C:4D:5E"
print "MAC address format valid:", is_mac_format(mac_addr)
""",
            expected_stdout_contains="MAC address format valid: true",
            feature_tags=["mac", "hardware", "networking", "colons"],
        ),
        ExampleDef(
            id=420,
            slug="420_ipv4_dot_segment_count",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify IPv4 Address Exactly Three Dot Delimiters",
            code="""
function is_ipv4_dot_count(ip: String) -> Bool:
    define n as length of string ip
    define dots: Int as 0
    for i from 0 to (n - 1)
        define ch as slice ip from i to (i + 1)
        if ch == "."
            set dots to dots + 1
    return dots == 3

print "IPv4 dot count check:", is_ipv4_dot_count("192.168.1.1")
""",
            expected_stdout_contains="IPv4 dot count check: true",
            feature_tags=["ipv4", "ip_address", "networking", "delimiters"],
        ),
    ]


def get_batch_13() -> list[ExampleDef]:
    """Batch 13: Date, time and range sanity (IDs 421..430)."""
    return [
        ExampleDef(
            id=421,
            slug="421_date_leap_year_rules",
            course="cs105",
            topic="validation_and_checksums",
            title="Determine Gregorian Calendar Leap Year",
            code="""
function is_leap_year(year: Int) -> Bool:
    if year % 400 == 0
        return true
    if year % 100 == 0
        return false
    if year % 4 == 0
        return true
    return false

print "Leap year 2024:", is_leap_year(2024)
print "Leap year 2100:", is_leap_year(2100)
print "Leap year 2000:", is_leap_year(2000)
""",
            expected_stdout_contains="Leap year 2024: true",
            feature_tags=["date", "leap_year", "calendar", "math"],
        ),
        ExampleDef(
            id=422,
            slug="422_date_month_range_check",
            course="cs105",
            topic="validation_and_checksums",
            title="Validate Month Integer in 1 to 12 Range",
            code="""
function is_valid_month(m: Int) -> Bool:
    if m >= 1
        if m <= 12
            return true
    return false

print "Month 7 valid:", is_valid_month(7)
print "Month 0 invalid:", is_valid_month(0)
print "Month 13 invalid:", is_valid_month(13)
""",
            expected_stdout_contains="Month 7 valid: true",
            feature_tags=["date", "month", "bounds", "calendar"],
        ),
        ExampleDef(
            id=423,
            slug="423_date_days_in_month_lookup",
            course="cs105",
            topic="validation_and_checksums",
            title="Determine Days in Month in Non-Leap Year",
            code="""
function days_in_month_standard(m: Int) -> Int:
    if m == 2
        return 28
    if m == 4
        return 30
    if m == 6
        return 30
    if m == 9
        return 30
    if m == 11
        return 30
    return 31

print "Days in February:", days_in_month_standard(2)
print "Days in April:", days_in_month_standard(4)
print "Days in July:", days_in_month_standard(7)
""",
            expected_stdout_contains="Days in February: 28",
            feature_tags=["date", "days", "calendar", "lookup"],
        ),
        ExampleDef(
            id=424,
            slug="424_time_24hr_hour_bounds",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify 24-Hour Time Hour Range 0 to 23",
            code="""
function is_valid_24hr_hour(h: Int) -> Bool:
    if h >= 0
        if h <= 23
            return true
    return false

print "Hour 14 valid:", is_valid_24hr_hour(14)
print "Hour 24 invalid:", is_valid_24hr_hour(24)
""",
            expected_stdout_contains="Hour 14 valid: true",
            feature_tags=["time", "hours", "24hour", "bounds"],
        ),
        ExampleDef(
            id=425,
            slug="425_time_minute_range_check",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Clock Minute in Range 0 to 59",
            code="""
function is_valid_minute(min_val: Int) -> Bool:
    if min_val >= 0
        if min_val <= 59
            return true
    return false

print "Minute 45 valid:", is_valid_minute(45)
print "Minute 60 invalid:", is_valid_minute(60)
""",
            expected_stdout_contains="Minute 45 valid: true",
            feature_tags=["time", "minutes", "bounds", "clock"],
        ),
        ExampleDef(
            id=426,
            slug="426_time_second_range_check",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify Clock Second in Range 0 to 59",
            code="""
function is_valid_second(sec: Int) -> Bool:
    if sec >= 0
        if sec <= 59
            return true
    return false

print "Second 30 valid:", is_valid_second(30)
print "Second -1 invalid:", is_valid_second(-1)
""",
            expected_stdout_contains="Second 30 valid: true",
            feature_tags=["time", "seconds", "bounds", "clock"],
        ),
        ExampleDef(
            id=427,
            slug="427_date_iso8601_length_check",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify YYYY-MM-DD Date String Length Exactly 10",
            code="""
function is_iso_date_length(d_str: String) -> Bool:
    return length of string d_str == 10

define iso_today as "2026-11-07"
print "ISO date length check:", is_iso_date_length(iso_today)
""",
            expected_stdout_contains="ISO date length check: true",
            feature_tags=["date", "iso8601", "length", "string"],
        ),
        ExampleDef(
            id=428,
            slug="428_date_iso8601_dash_separators",
            course="cs105",
            topic="validation_and_checksums",
            title="Verify ISO 8601 Dash Delimiters at Index 4 and 7",
            code="""
function has_iso_date_separators(d: String) -> Bool:
    define n as length of string d
    if n == 10
        define sep1 as slice d from 4 to 5
        define sep2 as slice d from 7 to 8
        if sep1 == "-"
            if sep2 == "-"
                return true
    return false

define test_d as "2026-05-15"
print "ISO date dash separators valid:", has_iso_date_separators(test_d)
""",
            expected_stdout_contains="ISO date dash separators valid: true",
            feature_tags=["date", "iso8601", "delimiters", "formatting"],
        ),
        ExampleDef(
            id=429,
            slug="429_range_start_precedes_end",
            course="cs105",
            topic="validation_and_checksums",
            title="Ensure Start Index Does Not Exceed End Index",
            code="""
function is_valid_interval(start_val: Int, end_val: Int) -> Bool:
    return start_val <= end_val

print "Interval 10..20 valid:", is_valid_interval(10, 20)
print "Interval 50..30 invalid:", is_valid_interval(50, 30)
""",
            expected_stdout_contains="Interval 10..20 valid: true",
            feature_tags=["range", "interval", "ordering", "bounds"],
        ),
        ExampleDef(
            id=430,
            slug="430_range_clamp_inside_limits",
            course="cs105",
            topic="validation_and_checksums",
            title="Clamp Integer Between Lower and Upper Limits",
            code="""
function clamp_int(val: Int, low_b: Int, high_b: Int) -> Int:
    if val < low_b
        return low_b
    if val > high_b
        return high_b
    return val

define c1 as clamp_int(150, 0, 100)
define c2 as clamp_int(-5, 0, 100)
define c3 as clamp_int(42, 0, 100)
print "Clamped high val:", c1
print "Clamped low val:", c2
print "Clamped inside val:", c3
""",
            expected_stdout_contains="Clamped high val: 100",
            feature_tags=["range", "clamp", "bounds", "utility"],
        ),
    ]


if __name__ == "__main__":
    batches = [
        (9, "ISBN and barcode checksums (ISBN-10, ISBN-13, EAN-8, UPC, parity, Fletcher)", get_batch_9()),
        (10, "Email structure validation (at-sign, domain, dots, whitespace, tld, composite)", get_batch_10()),
        (11, "Password policy rules (length, digits, uppercase, symbols, blacklist, score)", get_batch_11()),
        (12, "Identifiers and phone formats (E.164, US 10-digit, UUID v4, hex, slug, MAC)", get_batch_12()),
        (13, "Date, time and range sanity (leap year, days in month, 24hr, ISO date, clamp)", get_batch_13()),
    ]
    for b_num, desc, items in batches:
        process_batch(
            batch_num=b_num,
            axis_name="cs105",
            description=desc,
            items=items,
        )
