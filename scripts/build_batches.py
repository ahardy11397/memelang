"""Batch builder for examples expansion."""

from scripts.expand_examples import ExampleDef, process_batch


def get_batch_2() -> list[ExampleDef]:
    """Batch 2: CSV row handling (IDs 311..320) in CS104."""
    return [
        ExampleDef(
            id=311,
            slug="311_csv_split_fields",
            course="cs104",
            topic="text_and_data_tasks",
            title="CSV Line Field Extraction",
            code="""
define csv_line as "alice,developer,seattle"
define list fields: List<String> as empty List<String>
define current_field as ""
define n as length of string csv_line
for i from 0 to (n - 1)
    define ch as slice csv_line from i to (i + 1)
    if ch == ","
        append current_field to fields
        set current_field to ""
    else
        set current_field to current_field + ch
append current_field to fields
print "Field count:", length of fields
print "First field:", fields[0]
""",
            expected_stdout_contains="Field count: 3",
            feature_tags=["csv", "string_slice", "list", "loop"],
        ),
        ExampleDef(
            id=312,
            slug="312_csv_sum_numeric_row",
            course="cs104",
            topic="text_and_data_tasks",
            title="Sum Numeric Values in CSV Row",
            code="""
define row_values: List<Int> as [120, 45, 80, 210]
define total_sum: Int as 0
for each val in row_values
    set total_sum to total_sum + val
print "Row total sum:", total_sum
""",
            expected_stdout_contains="Row total sum: 455",
            feature_tags=["csv", "numeric", "loop", "sum"],
        ),
        ExampleDef(
            id=313,
            slug="313_csv_project_column",
            course="cs104",
            topic="text_and_data_tasks",
            title="Project CSV Column by Index",
            code="""
function get_column(row: List<String>, col_index: Int) -> String:
    if col_index < length of row
        return row[col_index]
    return "NOT_FOUND"

define record: List<String> as ["1042", "Widget", "99", "Warehouse A"]
define projected as get_column(record, 1)
print "Projected column:", projected
""",
            expected_stdout_contains="Projected column: Widget",
            feature_tags=["csv", "function", "projection", "list"],
        ),
        ExampleDef(
            id=314,
            slug="314_csv_strip_quotes",
            course="cs104",
            topic="text_and_data_tasks",
            title="Strip Quotes from CSV Field",
            code="""
function clean_quoted_field(raw: String) -> String:
    define len_raw as length of string raw
    if len_raw >= 2
        define first_ch as slice raw from 0 to 1
        define last_ch as slice raw from (len_raw - 1) to len_raw
        if first_ch == "'"
            if last_ch == "'"
                return slice raw from 1 to (len_raw - 1)
    return raw

define sample as "'san francisco'"
define cleaned as clean_quoted_field(sample)
print "Unquoted field:", cleaned
""",
            expected_stdout_contains="Unquoted field: san francisco",
            feature_tags=["csv", "string_slice", "function", "cleanup"],
        ),
        ExampleDef(
            id=315,
            slug="315_csv_skip_header_row",
            course="cs104",
            topic="text_and_data_tasks",
            title="Process CSV Rows Skipping Header",
            code="""
define list raw_table: List<String> as ["name,role,team", "bob,qa,core", "carol,dev,ops", "dave,pm,growth"]
define list data_rows: List<String> as empty List<String>
define total_rows as length of raw_table
for row_idx from 1 to (total_rows - 1)
    append raw_table[row_idx] to data_rows
print "Data row count:", length of data_rows
print "First data row:", data_rows[0]
""",
            expected_stdout_contains="Data row count: 3",
            feature_tags=["csv", "table", "header_skip", "list"],
        ),
        ExampleDef(
            id=316,
            slug="316_csv_validate_field_count",
            course="cs104",
            topic="text_and_data_tasks",
            title="Validate CSV Record Length",
            code="""
function is_row_valid(row: List<String>, required_cols: Int) -> Bool:
    return length of row == required_cols

define valid_row: List<String> as ["alpha", "beta", "gamma", "delta"]
define invalid_row: List<String> as ["alpha", "beta"]
print "Row 1 valid:", is_row_valid(valid_row, 4)
print "Row 2 valid:", is_row_valid(invalid_row, 4)
""",
            expected_stdout_contains="Row 1 valid: true",
            feature_tags=["csv", "validation", "function", "bool"],
        ),
        ExampleDef(
            id=317,
            slug="317_csv_filter_by_status",
            course="cs104",
            topic="text_and_data_tasks",
            title="Filter CSV Records by Column Value",
            code="""
define list statuses: List<String> as ["active", "suspended", "active", "pending", "active"]
define active_count: Int as 0
for each st in statuses
    if st == "active"
        set active_count to active_count + 1
print "Active records:", active_count
""",
            expected_stdout_contains="Active records: 3",
            feature_tags=["csv", "filter", "status", "counter"],
        ),
        ExampleDef(
            id=318,
            slug="318_csv_format_row",
            course="cs104",
            topic="text_and_data_tasks",
            title="Serialize Fields into Delimited Row",
            code="""
function join_with_comma(parts: List<String>) -> String:
    define out_line as ""
    define cnt as length of parts
    for idx from 0 to (cnt - 1)
        if idx > 0
            set out_line to out_line + ","
        set out_line to out_line + parts[idx]
    return out_line

define cells: List<String> as ["prod-99", "Keyboard", "49", "In Stock"]
define serialized as join_with_comma(cells)
print "Serialized line:", serialized
""",
            expected_stdout_contains="Serialized line: prod-99,Keyboard,49,In Stock",
            feature_tags=["csv", "formatting", "serialization", "string"],
        ),
        ExampleDef(
            id=319,
            slug="319_csv_find_max_metric",
            course="cs104",
            topic="text_and_data_tasks",
            title="Locate Maximum Value in CSV Metric Column",
            code="""
define metric_column: List<Int> as [420, 890, 150, 930, 610]
define highest_metric: Int as metric_column[0]
for each metric in metric_column
    if metric > highest_metric
        set highest_metric to metric
print "Highest metric found:", highest_metric
""",
            expected_stdout_contains="Highest metric found: 930",
            feature_tags=["csv", "metrics", "max", "loop"],
        ),
        ExampleDef(
            id=320,
            slug="320_csv_escape_commas",
            course="cs104",
            topic="text_and_data_tasks",
            title="Quote Wrap Field Containing Delimiter",
            code="""
function quote_if_comma_present(field_text: String) -> String:
    define text_len as length of string field_text
    define has_delimiter: Bool as false
    for pos from 0 to (text_len - 1)
        define ch as slice field_text from pos to (pos + 1)
        if ch == ","
            set has_delimiter to true
    if has_delimiter
        return "'" + field_text + "'"
    return field_text

define f1 as quote_if_comma_present("standard_val")
define f2 as quote_if_comma_present("smith, john")
print "Field 1 escaped:", f1
print "Field 2 escaped:", f2
""",
            expected_stdout_contains="Field 2 escaped: 'smith, john'",
            feature_tags=["csv", "escaping", "delimiter", "string_slice"],
        ),
    ]


if __name__ == "__main__":
    process_batch(
        batch_num=2,
        axis_name="cs104",
        description="CSV row handling (field extraction, sums, projections, unquoting, escaping)",
        items=get_batch_2(),
    )
