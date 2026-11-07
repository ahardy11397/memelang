"""Batch builder for CS106 batches 14 to 19 (IDs 431..491)."""

from scripts.expand_examples import ExampleDef, process_batch


def get_batch_14() -> list[ExampleDef]:
    """Batch 14: Statistics utility library (IDs 431..440)."""
    return [
        ExampleDef(
            id=431,
            slug="431_stat_calculate_mean",
            course="cs106",
            topic="small_reusable_libraries",
            title="Compute Arithmetic Mean of Integer Dataset",
            code="""
function compute_mean(data: List<Int>) -> Int:
    define total: Int as 0
    for each x in data
        set total to total + x
    return total / (length of data)

define list samples: List<Int> as [10, 20, 30, 40, 50]
define avg as compute_mean(samples)
print "Calculated dataset mean:", avg
""",
            expected_stdout_contains="Calculated dataset mean: 30",
            feature_tags=["stats", "mean", "math", "average"],
        ),
        ExampleDef(
            id=432,
            slug="432_stat_median_odd_length",
            course="cs106",
            topic="small_reusable_libraries",
            title="Determine Median Value for Odd Sized List",
            code="""
function median_odd(items: List<Int>) -> Int:
    sort items ascending
    define mid_idx as (length of items) / 2
    return items[mid_idx]

define list nums: List<Int> as [12, 3, 45, 18, 9]
define med as median_odd(nums)
print "Calculated odd median:", med
""",
            expected_stdout_contains="Calculated odd median: 12",
            feature_tags=["stats", "median", "sort", "odd"],
        ),
        ExampleDef(
            id=433,
            slug="433_stat_median_even_length",
            course="cs106",
            topic="small_reusable_libraries",
            title="Determine Average of Middle Two for Even Sized List",
            code="""
function median_even(items: List<Int>) -> Int:
    sort items ascending
    define n as length of items
    define mid_right as n / 2
    define mid_left as mid_right - 1
    return (items[mid_left] + items[mid_right]) / 2

define list dataset: List<Int> as [10, 20, 30, 40]
define med_e as median_even(dataset)
print "Calculated even median:", med_e
""",
            expected_stdout_contains="Calculated even median: 25",
            feature_tags=["stats", "median", "even", "sort"],
        ),
        ExampleDef(
            id=434,
            slug="434_stat_population_variance",
            course="cs106",
            topic="small_reusable_libraries",
            title="Compute Integer Approximation of Population Variance",
            code="""
function variance_approx(vals: List<Int>, avg: Int) -> Int:
    define sum_sq_diff: Int as 0
    for each v in vals
        define diff as v - avg
        set sum_sq_diff to sum_sq_diff + (diff * diff)
    return sum_sq_diff / (length of vals)

define list observations: List<Int> as [10, 20, 30]
define var_val as variance_approx(observations, 20)
print "Population variance approx:", var_val
""",
            expected_stdout_contains="Population variance approx: 66",
            feature_tags=["stats", "variance", "dispersion", "math"],
        ),
        ExampleDef(
            id=435,
            slug="435_stat_integer_square_root",
            course="cs106",
            topic="small_reusable_libraries",
            title="Approximate Integer Square Root for StdDev",
            code="""
function int_sqrt(n: Int) -> Int:
    if n <= 0
        return 0
    define root: Int as 1
    while ((root + 1) * (root + 1)) <= n
        set root to root + 1
    return root

define s1 as int_sqrt(64)
define s2 as int_sqrt(66)
print "Int sqrt 64:", s1
print "Int sqrt 66:", s2
""",
            expected_stdout_contains="Int sqrt 64: 8",
            feature_tags=["stats", "sqrt", "math", "approximation"],
        ),
        ExampleDef(
            id=436,
            slug="436_stat_data_range_spread",
            course="cs106",
            topic="small_reusable_libraries",
            title="Compute Range Spread Between High and Low",
            code="""
function data_spread(arr: List<Int>) -> Int:
    sort arr ascending
    define n as length of arr
    define min_v as arr[0]
    define max_v as arr[n - 1]
    return max_v - min_v

define list measures: List<Int> as [5, 12, 3, 22, 9]
define spread as data_spread(measures)
print "Dataset range spread:", spread
""",
            expected_stdout_contains="Dataset range spread: 19",
            feature_tags=["stats", "range", "spread", "dispersion"],
        ),
        ExampleDef(
            id=437,
            slug="437_stat_interquartile_range",
            course="cs106",
            topic="small_reusable_libraries",
            title="Compute Interquartile Range from Q1 and Q3",
            code="""
function compute_iqr(q1: Int, q3: Int) -> Int:
    return q3 - q1

define iqr_val as compute_iqr(25, 75)
print "Interquartile range:", iqr_val
""",
            expected_stdout_contains="Interquartile range: 50",
            feature_tags=["stats", "iqr", "quartiles", "summary"],
        ),
        ExampleDef(
            id=438,
            slug="438_stat_percentile_rank_count",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Percentage of Elements Below Threshold",
            code="""
function percentile_rank_int(scores: List<Int>, threshold: Int) -> Int:
    define below_count: Int as 0
    for each s in scores
        if s < threshold
            set below_count to below_count + 1
    return (below_count * 100) / (length of scores)

define list exam_scores: List<Int> as [50, 60, 70, 80, 90]
define rank as percentile_rank_int(exam_scores, 80)
print "Percentile rank of 80:", rank
""",
            expected_stdout_contains="Percentile rank of 80: 60",
            feature_tags=["stats", "percentile", "rank", "counting"],
        ),
        ExampleDef(
            id=439,
            slug="439_stat_moving_average_three_point",
            course="cs106",
            topic="small_reusable_libraries",
            title="Compute 3-Point Moving Average",
            code="""
function moving_avg_3(p1: Int, p2: Int, p3: Int) -> Int:
    return (p1 + p2 + p3) / 3

define ma as moving_avg_3(30, 40, 50)
print "Moving average of 30 40 50:", ma
""",
            expected_stdout_contains="Moving average of 30 40 50: 40",
            feature_tags=["stats", "moving_average", "smoothing", "time_series"],
        ),
        ExampleDef(
            id=440,
            slug="440_stat_find_peak_frequency_bin",
            course="cs106",
            topic="small_reusable_libraries",
            title="Identify Index of Histogram Bin with Highest Frequency",
            code="""
function highest_frequency_bin(bins: List<Int>) -> Int:
    define best_idx: Int as 0
    define max_count: Int as bins[0]
    define n as length of bins
    for i from 1 to (n - 1)
        if bins[i] > max_count
            set max_count to bins[i]
            set best_idx to i
    return best_idx

define list bin_counts: List<Int> as [12, 45, 98, 23, 10]
define peak_bin as highest_frequency_bin(bin_counts)
print "Peak frequency bin index:", peak_bin
""",
            expected_stdout_contains="Peak frequency bin index: 2",
            feature_tags=["stats", "mode", "histogram", "peak"],
        ),
    ]


def get_batch_15() -> list[ExampleDef]:
    """Batch 15: Finance utility library (IDs 441..450)."""
    return [
        ExampleDef(
            id=441,
            slug="441_fin_simple_interest_yield",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Simple Interest Yield",
            code="""
function calc_simple_interest(principal: Int, rate_pct: Int, years: Int) -> Int:
    return (principal * rate_pct * years) / 100

define yield_amt as calc_simple_interest(10000, 5, 3)
print "Simple interest yield:", yield_amt
""",
            expected_stdout_contains="Simple interest yield: 1500",
            feature_tags=["finance", "interest", "simple", "math"],
        ),
        ExampleDef(
            id=442,
            slug="442_fin_compound_interest_annual",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Annual Compound Balance Growth",
            code="""
function compound_annual(principal: Int, rate_pct: Int, years: Int) -> Int:
    define balance as principal
    for y from 1 to years
        define earned as (balance * rate_pct) / 100
        set balance to balance + earned
    return balance

define final_bal as compound_annual(1000, 10, 3)
print "Compounded final balance:", final_bal
""",
            expected_stdout_contains="Compounded final balance: 1331",
            feature_tags=["finance", "compound", "investment", "growth"],
        ),
        ExampleDef(
            id=443,
            slug="443_fin_future_value_monthly_deposit",
            course="cs106",
            topic="small_reusable_libraries",
            title="Compute Savings Accumulation with Monthly Deposits",
            code="""
function savings_with_deposit(monthly_dep: Int, months: Int) -> Int:
    define accumulated: Int as 0
    for m from 1 to months
        set accumulated to accumulated + monthly_dep
    return accumulated

define saved as savings_with_deposit(250, 12)
print "Annual savings accumulation:", saved
""",
            expected_stdout_contains="Annual savings accumulation: 3000",
            feature_tags=["finance", "savings", "annuity", "deposit"],
        ),
        ExampleDef(
            id=444,
            slug="444_fin_estimated_monthly_payment",
            course="cs106",
            topic="small_reusable_libraries",
            title="Estimate Monthly Principal Payment with Fee",
            code="""
function estimate_monthly_loan(amount: Int, months: Int, service_fee: Int) -> Int:
    define base_monthly as amount / months
    return base_monthly + service_fee

define monthly as estimate_monthly_loan(12000, 24, 15)
print "Estimated monthly installment:", monthly
""",
            expected_stdout_contains="Estimated monthly installment: 515",
            feature_tags=["finance", "loan", "amortization", "payment"],
        ),
        ExampleDef(
            id=445,
            slug="445_fin_net_profit_margin_pct",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Net Profit Margin Percentage",
            code="""
function profit_margin_percent(revenue: Int, cost: Int) -> Int:
    define profit as revenue - cost
    return (profit * 100) / revenue

define margin as profit_margin_percent(50000, 35000)
print "Net profit margin percentage:", margin
""",
            expected_stdout_contains="Net profit margin percentage: 30",
            feature_tags=["finance", "margin", "profit", "accounting"],
        ),
        ExampleDef(
            id=446,
            slug="446_fin_break_even_unit_volume",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Break-Even Unit Volume",
            code="""
function break_even_volume(fixed_costs: Int, unit_price: Int, unit_cost: Int) -> Int:
    define margin_per_unit as unit_price - unit_cost
    return fixed_costs / margin_per_unit

define be_units as break_even_volume(20000, 50, 30)
print "Break-even unit volume:", be_units
""",
            expected_stdout_contains="Break-even unit volume: 1000",
            feature_tags=["finance", "break_even", "cost", "unit"],
        ),
        ExampleDef(
            id=447,
            slug="447_fin_apply_discount_percentage",
            course="cs106",
            topic="small_reusable_libraries",
            title="Apply Percentage Discount to Price",
            code="""
function discount_price(original: Int, pct_off: Int) -> Int:
    define deduction as (original * pct_off) / 100
    return original - deduction

define discounted as discount_price(80, 25)
print "Discounted purchase price:", discounted
""",
            expected_stdout_contains="Discounted purchase price: 60",
            feature_tags=["finance", "discount", "retail", "price"],
        ),
        ExampleDef(
            id=448,
            slug="448_fin_calc_sales_tax_amount",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Regional Sales Tax Amount",
            code="""
function sales_tax(base_amt: Int, tax_pct: Int) -> Int:
    return (base_amt * tax_pct) / 100

define tax as sales_tax(200, 8)
print "Calculated sales tax:", tax
""",
            expected_stdout_contains="Calculated sales tax: 16",
            feature_tags=["finance", "tax", "sales", "percentage"],
        ),
        ExampleDef(
            id=449,
            slug="449_fin_calculate_tip_share",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Gratuity Amount on Bill",
            code="""
function calculate_tip(bill_subtotal: Int, tip_pct: Int) -> Int:
    return (bill_subtotal * tip_pct) / 100

define tip as calculate_tip(150, 18)
print "Calculated gratuity tip:", tip
""",
            expected_stdout_contains="Calculated gratuity tip: 27",
            feature_tags=["finance", "tip", "gratuity", "restaurant"],
        ),
        ExampleDef(
            id=450,
            slug="450_fin_rule_of_72_doubling_years",
            course="cs106",
            topic="small_reusable_libraries",
            title="Estimate Investment Doubling Time Using Rule of 72",
            code="""
function doubling_years(interest_rate: Int) -> Int:
    return 72 / interest_rate

define years_needed as doubling_years(6)
print "Years to double investment:", years_needed
""",
            expected_stdout_contains="Years to double investment: 12",
            feature_tags=["finance", "rule_of_72", "doubling", "compound"],
        ),
    ]


def get_batch_16() -> list[ExampleDef]:
    """Batch 16: Date and time arithmetic library (IDs 451..460)."""
    return [
        ExampleDef(
            id=451,
            slug="451_time_seconds_between_moments",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Elapsed Seconds Between Two Clock Times",
            code="""
function to_seconds(h: Int, m: Int, s: Int) -> Int:
    return (h * 3600) + (m * 60) + s

function elapsed_seconds(h1: Int, m1: Int, s1: Int, h2: Int, m2: Int, s2: Int) -> Int:
    define t1 as to_seconds(h1, m1, s1)
    define t2 as to_seconds(h2, m2, s2)
    return t2 - t1

define diff_sec as elapsed_seconds(9, 15, 0, 10, 30, 45)
print "Elapsed duration in seconds:", diff_sec
""",
            expected_stdout_contains="Elapsed duration in seconds: 4545",
            feature_tags=["time", "elapsed", "seconds", "math"],
        ),
        ExampleDef(
            id=452,
            slug="452_time_format_seconds_to_hms",
            course="cs106",
            topic="small_reusable_libraries",
            title="Decompose Total Seconds into Hours Minutes and Seconds",
            code="""
define total_sec as 3665
define hours as total_sec / 3600
define rem as total_sec % 3600
define minutes as rem / 60
define seconds as rem % 60
print "Hours component:", hours
print "Minutes component:", minutes
print "Seconds component:", seconds
""",
            expected_stdout_contains="Hours component: 1",
            feature_tags=["time", "hms", "decomposition", "clock"],
        ),
        ExampleDef(
            id=453,
            slug="453_time_add_minutes_to_clock",
            course="cs106",
            topic="small_reusable_libraries",
            title="Add Minutes to 24-Hour Clock Time",
            code="""
function add_mins(h: Int, m: Int, delta_m: Int) -> Int:
    define total_m as (h * 60) + m + delta_m
    define new_h as (total_m / 60) % 24
    return new_h

define later_hour as add_mins(22, 30, 120)
print "Later hour result:", later_hour
""",
            expected_stdout_contains="Later hour result: 0",
            feature_tags=["time", "addition", "clock", "modulo"],
        ),
        ExampleDef(
            id=454,
            slug="454_date_days_between_same_month",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Days Between Calendar Dates in Same Month",
            code="""
function days_diff(day_start: Int, day_end: Int) -> Int:
    return day_end - day_start

define span as days_diff(4, 21)
print "Days in interval span:", span
""",
            expected_stdout_contains="Days in interval span: 17",
            feature_tags=["date", "interval", "days", "calendar"],
        ),
        ExampleDef(
            id=455,
            slug="455_date_estimate_day_of_year",
            course="cs106",
            topic="small_reusable_libraries",
            title="Estimate Day of Year from Month and Day",
            code="""
function day_of_year_approx(month: Int, day: Int) -> Int:
    define days_before as (month - 1) * 30
    return days_before + day

define doy as day_of_year_approx(4, 15)
print "Approximate day of year:", doy
""",
            expected_stdout_contains="Approximate day of year: 105",
            feature_tags=["date", "day_of_year", "calendar", "math"],
        ),
        ExampleDef(
            id=456,
            slug="456_date_business_days_in_weeks",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Total Business Days in Multi-Week Span",
            code="""
function business_days(weeks: Int) -> Int:
    return weeks * 5

define b_days as business_days(6)
print "Total business days:", b_days
""",
            expected_stdout_contains="Total business days: 30",
            feature_tags=["date", "business_days", "workweek", "schedule"],
        ),
        ExampleDef(
            id=457,
            slug="457_time_countdown_remaining",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Remaining Minutes in Countdown Timer",
            code="""
function countdown_remaining(total_mins: Int, elapsed_mins: Int) -> Int:
    define rem as total_mins - elapsed_mins
    if rem < 0
        return 0
    return rem

define left as countdown_remaining(60, 42)
print "Minutes remaining on timer:", left
""",
            expected_stdout_contains="Minutes remaining on timer: 18",
            feature_tags=["time", "countdown", "timer", "bounds"],
        ),
        ExampleDef(
            id=458,
            slug="458_time_minutes_to_hour_fraction",
            course="cs106",
            topic="small_reusable_libraries",
            title="Split Minutes into Hours and Leftover Minutes",
            code="""
function split_minutes(total_m: Int) -> Int:
    return total_m % 60

define leftover_m as split_minutes(135)
print "Leftover minutes:", leftover_m
""",
            expected_stdout_contains="Leftover minutes: 15",
            feature_tags=["time", "minutes", "modulo", "breakdown"],
        ),
        ExampleDef(
            id=459,
            slug="459_time_round_to_nearest_quarter_hour",
            course="cs106",
            topic="small_reusable_libraries",
            title="Round Minutes to Nearest 15-Minute Block",
            code="""
function round_quarter_hour(m: Int) -> Int:
    return ((m + 7) / 15) * 15

print "Round 22 min:", round_quarter_hour(22)
print "Round 39 min:", round_quarter_hour(39)
""",
            expected_stdout_contains="Round 22 min: 15",
            feature_tags=["time", "rounding", "quarter_hour", "billing"],
        ),
        ExampleDef(
            id=460,
            slug="460_time_epoch_to_hour_of_day",
            course="cs106",
            topic="small_reusable_libraries",
            title="Extract Hour of Day from Unix Epoch Timestamp",
            code="""
function epoch_hour(epoch_seconds: Int) -> Int:
    define total_hours as epoch_seconds / 3600
    return total_hours % 24

define hour_val as epoch_hour(86400 + 36000)
print "Extracted hour of day:", hour_val
""",
            expected_stdout_contains="Extracted hour of day: 10",
            feature_tags=["time", "epoch", "timestamp", "clock"],
        ),
    ]


def get_batch_17() -> list[ExampleDef]:
    """Batch 17: Unit conversion routines (IDs 461..470)."""
    return [
        ExampleDef(
            id=461,
            slug="461_unit_km_to_miles_approx",
            course="cs106",
            topic="small_reusable_libraries",
            title="Convert Kilometers to Miles Using Ratio 62/100",
            code="""
function km_to_miles(km: Int) -> Int:
    return (km * 62) / 100

define mi as km_to_miles(100)
print "100 km in miles:", mi
""",
            expected_stdout_contains="100 km in miles: 62",
            feature_tags=["units", "distance", "metric", "imperial"],
        ),
        ExampleDef(
            id=462,
            slug="462_unit_miles_to_km_approx",
            course="cs106",
            topic="small_reusable_libraries",
            title="Convert Miles to Kilometers Using Ratio 161/100",
            code="""
function miles_to_km(mi: Int) -> Int:
    return (mi * 161) / 100

define km_val as miles_to_km(50)
print "50 miles in km:", km_val
""",
            expected_stdout_contains="50 miles in km: 80",
            feature_tags=["units", "distance", "imperial", "metric"],
        ),
        ExampleDef(
            id=463,
            slug="463_unit_celsius_to_fahrenheit",
            course="cs106",
            topic="small_reusable_libraries",
            title="Convert Celsius Temperature to Fahrenheit",
            code="""
function c_to_f(c: Int) -> Int:
    return ((c * 9) / 5) + 32

define f_temp as c_to_f(25)
print "25 C in Fahrenheit:", f_temp
""",
            expected_stdout_contains="25 C in Fahrenheit: 77",
            feature_tags=["units", "temperature", "celsius", "fahrenheit"],
        ),
        ExampleDef(
            id=464,
            slug="464_unit_fahrenheit_to_celsius",
            course="cs106",
            topic="small_reusable_libraries",
            title="Convert Fahrenheit Temperature to Celsius",
            code="""
function f_to_c(f: Int) -> Int:
    return ((f - 32) * 5) / 9

define c_temp as f_to_c(77)
print "77 F in Celsius:", c_temp
""",
            expected_stdout_contains="77 F in Celsius: 25",
            feature_tags=["units", "temperature", "fahrenheit", "celsius"],
        ),
        ExampleDef(
            id=465,
            slug="465_unit_kg_to_pounds_approx",
            course="cs106",
            topic="small_reusable_libraries",
            title="Convert Kilograms to Pounds Using Factor 22/10",
            code="""
function kg_to_lbs(kg: Int) -> Int:
    return (kg * 22) / 10

define lbs as kg_to_lbs(70)
print "70 kg in pounds:", lbs
""",
            expected_stdout_contains="70 kg in pounds: 154",
            feature_tags=["units", "weight", "mass", "conversion"],
        ),
        ExampleDef(
            id=466,
            slug="466_unit_pounds_to_kg_approx",
            course="cs106",
            topic="small_reusable_libraries",
            title="Convert Pounds to Kilograms Using Factor 10/22",
            code="""
function lbs_to_kg(lbs: Int) -> Int:
    return (lbs * 10) / 22

define kg_amt as lbs_to_kg(154)
print "154 lbs in kg:", kg_amt
""",
            expected_stdout_contains="154 lbs in kg: 70",
            feature_tags=["units", "weight", "imperial", "metric"],
        ),
        ExampleDef(
            id=467,
            slug="467_unit_liters_to_gallons_approx",
            course="cs106",
            topic="small_reusable_libraries",
            title="Convert Liters to US Gallons Using Ratio 264/1000",
            code="""
function liters_to_gal(liters: Int) -> Int:
    return (liters * 264) / 1000

define gal as liters_to_gal(100)
print "100 liters in gallons:", gal
""",
            expected_stdout_contains="100 liters in gallons: 26",
            feature_tags=["units", "volume", "liquid", "conversion"],
        ),
        ExampleDef(
            id=468,
            slug="468_unit_gallons_to_liters_approx",
            course="cs106",
            topic="small_reusable_libraries",
            title="Convert Gallons to Liters Using Ratio 3785/1000",
            code="""
function gal_to_liters(gal: Int) -> Int:
    return (gal * 3785) / 1000

define lit as gal_to_liters(10)
print "10 gallons in liters:", lit
""",
            expected_stdout_contains="10 gallons in liters: 37",
            feature_tags=["units", "volume", "gallons", "liters"],
        ),
        ExampleDef(
            id=469,
            slug="469_unit_meters_to_feet_approx",
            course="cs106",
            topic="small_reusable_libraries",
            title="Convert Meters to Feet Using Ratio 328/100",
            code="""
function meters_to_feet(m: Int) -> Int:
    return (m * 328) / 100

define ft as meters_to_feet(10)
print "10 meters in feet:", ft
""",
            expected_stdout_contains="10 meters in feet: 32",
            feature_tags=["units", "length", "meters", "feet"],
        ),
        ExampleDef(
            id=470,
            slug="470_unit_feet_to_inches",
            course="cs106",
            topic="small_reusable_libraries",
            title="Convert Feet to Total Inches",
            code="""
function feet_to_inches(ft: Int) -> Int:
    return ft * 12

define in_val as feet_to_inches(6)
print "6 feet in inches:", in_val
""",
            expected_stdout_contains="6 feet in inches: 72",
            feature_tags=["units", "length", "inches", "feet"],
        ),
    ]


def get_batch_18() -> list[ExampleDef]:
    """Batch 18: Commerce and cart ledger (IDs 471..480)."""
    return [
        ExampleDef(
            id=471,
            slug="471_cart_line_item_total",
            course="cs106",
            topic="small_reusable_libraries",
            title="Compute Line Item Price Multiplied by Quantity",
            code="""
function line_item_subtotal(unit_cents: Int, qty: Int) -> Int:
    return unit_cents * qty

define sub as line_item_subtotal(450, 3)
print "Line item subtotal in cents:", sub
""",
            expected_stdout_contains="Line item subtotal in cents: 1350",
            feature_tags=["commerce", "cart", "pricing", "calculation"],
        ),
        ExampleDef(
            id=472,
            slug="472_cart_sum_line_items",
            course="cs106",
            topic="small_reusable_libraries",
            title="Sum Multiple Line Item Totals in Shopping Cart",
            code="""
define list item_totals: List<Int> as [1200, 450, 890, 2300]
define cart_total: Int as 0
for each itm in item_totals
    set cart_total to cart_total + itm
print "Total shopping cart subtotal:", cart_total
""",
            expected_stdout_contains="Total shopping cart subtotal: 4840",
            feature_tags=["commerce", "cart", "subtotal", "sum"],
        ),
        ExampleDef(
            id=473,
            slug="473_cart_tier_discount_calc",
            course="cs106",
            topic="small_reusable_libraries",
            title="Apply Tiered Volume Discount by Cart Amount",
            code="""
function tier_discount_pct(cart_amt: Int) -> Int:
    if cart_amt >= 200
        return 20
    if cart_amt >= 100
        return 10
    if cart_amt >= 50
        return 5
    return 0

print "Tier discount 250:", tier_discount_pct(250)
print "Tier discount 120:", tier_discount_pct(120)
print "Tier discount 30:", tier_discount_pct(30)
""",
            expected_stdout_contains="Tier discount 250: 20",
            feature_tags=["commerce", "discount", "tiers", "pricing"],
        ),
        ExampleDef(
            id=474,
            slug="474_cart_apply_coupon_code",
            course="cs106",
            topic="small_reusable_libraries",
            title="Evaluate Promotional Coupon Code Deduction",
            code="""
function coupon_deduction(code: String) -> Int:
    if code == "SAVE10"
        return 10
    if code == "SUMMER25"
        return 25
    return 0

define off as coupon_deduction("SUMMER25")
print "Promotional coupon deduction:", off
""",
            expected_stdout_contains="Promotional coupon deduction: 25",
            feature_tags=["commerce", "coupon", "promotion", "discount"],
        ),
        ExampleDef(
            id=475,
            slug="475_cart_shipping_rate_by_weight",
            course="cs106",
            topic="small_reusable_libraries",
            title="Determine Shipping Fee Tier by Package Weight",
            code="""
function shipping_cost(weight_kg: Int) -> Int:
    if weight_kg > 10
        return 25
    if weight_kg > 5
        return 15
    return 8

print "Shipping 12kg:", shipping_cost(12)
print "Shipping 3kg:", shipping_cost(3)
""",
            expected_stdout_contains="Shipping 12kg: 25",
            feature_tags=["commerce", "shipping", "logistics", "tiers"],
        ),
        ExampleDef(
            id=476,
            slug="476_cart_grand_total_assembly",
            course="cs106",
            topic="small_reusable_libraries",
            title="Assemble Order Grand Total with Tax and Shipping",
            code="""
function order_grand_total(subtotal: Int, discount: Int, tax: Int, shipping: Int) -> Int:
    return subtotal - discount + tax + shipping

define total as order_grand_total(100, 15, 8, 12)
print "Order final grand total:", total
""",
            expected_stdout_contains="Order final grand total: 105",
            feature_tags=["commerce", "order", "total", "billing"],
        ),
        ExampleDef(
            id=477,
            slug="477_cart_decrement_inventory_stock",
            course="cs106",
            topic="small_reusable_libraries",
            title="Decrement Warehouse Inventory Level on Fulfillment",
            code="""
function fulfill_stock(current_stock: Int, qty_ordered: Int) -> Int:
    if current_stock >= qty_ordered
        return current_stock - qty_ordered
    return 0

define rem_stock as fulfill_stock(50, 12)
print "Remaining inventory stock:", rem_stock
""",
            expected_stdout_contains="Remaining inventory stock: 38",
            feature_tags=["commerce", "inventory", "stock", "fulfillment"],
        ),
        ExampleDef(
            id=478,
            slug="478_cart_low_stock_warning",
            course="cs106",
            topic="small_reusable_libraries",
            title="Trigger Reorder Warning for Low Stock Items",
            code="""
function is_stock_low(count: Int, threshold: Int) -> Bool:
    return count <= threshold

print "Stock 4 alert:", is_stock_low(4, 5)
print "Stock 15 alert:", is_stock_low(15, 5)
""",
            expected_stdout_contains="Stock 4 alert: true",
            feature_tags=["commerce", "inventory", "reorder", "alert"],
        ),
        ExampleDef(
            id=479,
            slug="479_cart_deduct_store_credit",
            course="cs106",
            topic="small_reusable_libraries",
            title="Apply Store Credit Balance Against Invoice Due",
            code="""
function apply_credit(due: Int, credit: Int) -> Int:
    if credit >= due
        return 0
    return due - credit

define out1 as apply_credit(100, 40)
define out2 as apply_credit(50, 75)
print "Remaining due after credit 1:", out1
print "Remaining due after credit 2:", out2
""",
            expected_stdout_contains="Remaining due after credit 1: 60",
            feature_tags=["commerce", "store_credit", "balance", "invoice"],
        ),
        ExampleDef(
            id=480,
            slug="480_cart_reward_points_accrual",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Loyalty Reward Points on Qualified Spend",
            code="""
function loyalty_points(spend_dollars: Int) -> Int:
    return spend_dollars / 10

define points as loyalty_points(245)
print "Accrued loyalty points:", points
""",
            expected_stdout_contains="Accrued loyalty points: 24",
            feature_tags=["commerce", "loyalty", "points", "rewards"],
        ),
    ]


def get_batch_19() -> list[ExampleDef]:
    """Batch 19: Queues, ring buffers & workflows (IDs 481..491)."""
    return [
        ExampleDef(
            id=481,
            slug="481_queue_enqueue_job",
            course="cs106",
            topic="small_reusable_libraries",
            title="Enqueue Work Job ID to Back of Task Queue",
            code="""
define list task_queue: List<Int> as [101, 102, 103]
append 104 to task_queue
print "Queue size after enqueue:", length of task_queue
print "Enqueued tail element:", task_queue[3]
""",
            expected_stdout_contains="Queue size after enqueue: 4",
            feature_tags=["queue", "fifo", "enqueue", "append"],
        ),
        ExampleDef(
            id=482,
            slug="482_queue_advance_head_pointer",
            course="cs106",
            topic="small_reusable_libraries",
            title="Advance Queue Head Pointer on Dequeue",
            code="""
function advance_head(current_head: Int, max_capacity: Int) -> Int:
    if current_head < (max_capacity - 1)
        return current_head + 1
    return 0

define next_head as advance_head(2, 10)
print "Advanced queue head:", next_head
""",
            expected_stdout_contains="Advanced queue head: 3",
            feature_tags=["queue", "head", "dequeue", "pointer"],
        ),
        ExampleDef(
            id=483,
            slug="483_buffer_ring_write_slot",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Next Ring Buffer Circular Write Index",
            code="""
function next_write_slot(head: Int, ring_size: Int) -> Int:
    return (head + 1) % ring_size

define w1 as next_write_slot(3, 8)
define w2 as next_write_slot(7, 8)
print "Next slot from 3:", w1
print "Wrap slot from 7:", w2
""",
            expected_stdout_contains="Next slot from 3: 4",
            feature_tags=["ring_buffer", "circular", "modulo", "index"],
        ),
        ExampleDef(
            id=484,
            slug="484_buffer_ring_read_slot",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Next Ring Buffer Circular Read Index",
            code="""
function next_read_slot(tail: Int, ring_size: Int) -> Int:
    return (tail + 1) % ring_size

define r1 as next_read_slot(0, 4)
define r2 as next_read_slot(3, 4)
print "Read next slot 1:", r1
print "Read wrap slot 2:", r2
""",
            expected_stdout_contains="Read next slot 1: 1",
            feature_tags=["ring_buffer", "circular", "read", "tail"],
        ),
        ExampleDef(
            id=485,
            slug="485_stack_push_operation",
            course="cs106",
            topic="small_reusable_libraries",
            title="Push Element to Top of Execution Stack",
            code="""
define list exec_stack: List<Int> as [10, 20]
append 99 to exec_stack
define top_idx as (length of exec_stack) - 1
print "Stack depth:", length of exec_stack
print "Pushed top value:", exec_stack[top_idx]
""",
            expected_stdout_contains="Pushed top value: 99",
            feature_tags=["stack", "lifo", "push", "operations"],
        ),
        ExampleDef(
            id=486,
            slug="486_stack_peek_top_element",
            course="cs106",
            topic="small_reusable_libraries",
            title="Inspect Top Value of Non-Empty Stack",
            code="""
function stack_peek(st: List<Int>) -> Int:
    define n as length of st
    return st[n - 1]

define list call_stack: List<Int> as [500, 600, 750]
define top_val as stack_peek(call_stack)
print "Peeked stack top:", top_val
""",
            expected_stdout_contains="Peeked stack top: 750",
            feature_tags=["stack", "peek", "inspection", "lifo"],
        ),
        ExampleDef(
            id=487,
            slug="487_workflow_triage_priority_score",
            course="cs106",
            topic="small_reusable_libraries",
            title="Compute Incident Triage Priority Score",
            code="""
function incident_score(severity: Int, urgency: Int) -> Int:
    return severity * urgency

define p_score as incident_score(4, 5)
print "Calculated incident triage score:", p_score
""",
            expected_stdout_contains="Calculated incident triage score: 20",
            feature_tags=["workflow", "triage", "priority", "incident"],
        ),
        ExampleDef(
            id=488,
            slug="488_workflow_round_robin_worker",
            course="cs106",
            topic="small_reusable_libraries",
            title="Assign Next Task in Round Robin Dispatch",
            code="""
function next_worker_id(current_w: Int, total_w: Int) -> Int:
    return (current_w + 1) % total_w

define w_next as next_worker_id(2, 3)
print "Next round robin worker id:", w_next
""",
            expected_stdout_contains="Next round robin worker id: 0",
            feature_tags=["workflow", "round_robin", "scheduler", "dispatch"],
        ),
        ExampleDef(
            id=489,
            slug="489_workflow_status_transition",
            course="cs106",
            topic="small_reusable_libraries",
            title="Transition Pipeline Job to Next Valid State",
            code="""
function advance_state(state: String) -> String:
    if state == "QUEUED"
        return "RUNNING"
    if state == "RUNNING"
        return "SUCCESS"
    return "UNKNOWN"

define s1 as advance_state("QUEUED")
define s2 as advance_state("RUNNING")
print "State transition 1:", s1
print "State transition 2:", s2
""",
            expected_stdout_contains="State transition 1: RUNNING",
            feature_tags=["workflow", "state_machine", "transition", "status"],
        ),
        ExampleDef(
            id=490,
            slug="490_workflow_exponential_backoff_delay",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Exponential Backoff Delay Interval",
            code="""
function backoff_delay_ms(base_ms: Int, attempt: Int) -> Int:
    define delay as base_ms
    if attempt > 1
        for a from 2 to attempt
            set delay to delay * 2
    return delay

define d1 as backoff_delay_ms(100, 1)
define d3 as backoff_delay_ms(100, 3)
print "Backoff attempt 1 ms:", d1
print "Backoff attempt 3 ms:", d3
""",
            expected_stdout_contains="Backoff attempt 3 ms: 400",
            feature_tags=["workflow", "backoff", "retry", "network"],
        ),
        ExampleDef(
            id=491,
            slug="491_workflow_stopwatch_split_delta",
            course="cs106",
            topic="small_reusable_libraries",
            title="Calculate Split Lap Delta from Stopwatch Marks",
            code="""
function split_delta(mark_a: Int, mark_b: Int) -> Int:
    return mark_b - mark_a

define lap_time as split_delta(12400, 15850)
print "Recorded lap split time ms:", lap_time
""",
            expected_stdout_contains="Recorded lap split time ms: 3450",
            feature_tags=["workflow", "stopwatch", "timer", "lap"],
        ),
    ]


if __name__ == "__main__":
    batches = [
        (14, "Statistics utility library (mean, median, variance, range, IQR, moving avg)", get_batch_14()),
        (15, "Finance utility library (interest, compound, loan, margin, break-even, tax, tip)", get_batch_15()),
        (16, "Date and time arithmetic (elapsed sec, HMS, clock add, business days, countdown)", get_batch_16()),
        (17, "Unit conversions (km/miles, C/F, kg/lbs, liters/gal, meters/feet, inches)", get_batch_17()),
        (18, "Commerce and cart ledger (line totals, tier discount, coupon, shipping, stock)", get_batch_18()),
        (19, "Queues, ring buffers & workflows (enqueue, ring slot, stack peek, backoff, splits)", get_batch_19()),
    ]
    for b_num, desc, items in batches:
        process_batch(
            batch_num=b_num,
            axis_name="cs106",
            description=desc,
            items=items,
        )
