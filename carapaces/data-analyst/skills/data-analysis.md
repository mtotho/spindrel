---
name: Data Analysis Patterns
description: Advanced data analysis patterns — pivot tables, time series, statistical tests, data cleaning, joins, and report generation
---
# SKILL: Data Analysis Patterns

**All scripts use Python stdlib only** (csv, json, math, collections, datetime). No pandas, numpy, or third-party packages unless you confirm they're available.

## File Reading

Handle encoding issues upfront. Many real-world CSVs have BOM markers or non-UTF-8 encoding.

```python
import csv, sys

def open_csv(path):
    """Open a CSV with encoding fallback."""
    for enc in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            f = open(path, encoding=enc)
            reader = csv.DictReader(f)
            first = next(reader)  # test read
            f.seek(0)
            return csv.DictReader(f)
        except (UnicodeDecodeError, StopIteration):
            f.close()
    raise ValueError(f"Cannot decode {path}")
```

## Data Inspection

Always start by understanding the data before analyzing it.

### CSV Inspection Script
```python
import csv, sys
from collections import Counter

with open(sys.argv[1], encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

if not rows:
    print("Empty dataset")
    sys.exit(0)

columns = list(rows[0].keys())
print(f"Rows: {len(rows)}")
print(f"Columns ({len(columns)}): {', '.join(columns)}")
print()

for col in columns:
    values = [r[col] for r in rows]
    non_empty = [v for v in values if v.strip()]
    nulls = len(values) - len(non_empty)
    unique = len(set(non_empty))
    sample = list(set(non_empty))[:5]
    print(f"  {col}: {unique} unique, {nulls} nulls, sample: {sample}")
```

### JSON Inspection
```python
import json, sys

with open(sys.argv[1], encoding='utf-8-sig') as f:
    data = json.load(f)

if isinstance(data, list):
    print(f"Array of {len(data)} items")
    if data and isinstance(data[0], dict):
        print(f"First item keys: {list(data[0].keys())}")
    elif data:
        print(f"First item type: {type(data[0]).__name__}")
elif isinstance(data, dict):
    print(f"Object with {len(data)} keys: {list(data.keys())[:20]}")
```

## Aggregation Patterns

### Group-by with Multiple Metrics
```python
from collections import defaultdict

groups = defaultdict(list)
for row in rows:
    key = row['category']  # or tuple for multi-key
    groups[key].append(float(row['amount']))

print(f"{'Category':<20} {'Count':>8} {'Sum':>12} {'Avg':>10} {'Min':>10} {'Max':>10}")
print("-" * 72)
for key in sorted(groups, key=lambda k: -sum(groups[k])):
    vals = groups[key]
    print(f"{key:<20} {len(vals):>8} {sum(vals):>12,.2f} {sum(vals)/len(vals):>10,.2f} {min(vals):>10,.2f} {max(vals):>10,.2f}")
```

### Pivot Table (2D cross-tabulation)
```python
from collections import defaultdict

pivot = defaultdict(lambda: defaultdict(float))
row_keys = set()
col_keys = set()

for row in rows:
    rk = row['row_field']
    ck = row['col_field']
    pivot[rk][ck] += float(row['value_field'])
    row_keys.add(rk)
    col_keys.add(ck)

col_keys = sorted(col_keys)
header = f"{'':>20}" + "".join(f"{c:>15}" for c in col_keys) + f"{'Total':>15}"
print(header)
for rk in sorted(row_keys):
    vals = [pivot[rk][ck] for ck in col_keys]
    line = f"{rk:>20}" + "".join(f"{v:>15,.2f}" for v in vals) + f"{sum(vals):>15,.2f}"
    print(line)
```

### Frequency Distribution
```python
from collections import Counter

values = [row['field'] for row in rows]
counts = Counter(values).most_common(20)

print(f"{'Value':<30} {'Count':>8} {'%':>8}")
print("-" * 48)
total = len(values)
for val, count in counts:
    print(f"{str(val):<30} {count:>8} {count/total*100:>7.1f}%")
```

## Time Series Analysis

### Period-over-Period Changes
```python
from collections import defaultdict
from datetime import datetime

# Group by period (month)
periods = defaultdict(float)
for row in rows:
    dt = datetime.strptime(row['date'], '%Y-%m-%d')
    period = dt.strftime('%Y-%m')
    periods[period] += float(row['amount'])

sorted_periods = sorted(periods.keys())
print(f"{'Period':<10} {'Value':>12} {'Change':>12} {'% Change':>10}")
print("-" * 46)
prev = None
for p in sorted_periods:
    val = periods[p]
    if prev is not None:
        change = val - prev
        pct = (change / prev * 100) if prev != 0 else 0
        print(f"{p:<10} {val:>12,.2f} {change:>+12,.2f} {pct:>+9.1f}%")
    else:
        print(f"{p:<10} {val:>12,.2f} {'---':>12} {'---':>10}")
    prev = val
```

### Moving Average
```python
def moving_average(values, window=3):
    """Trailing moving average. First (window-1) values use partial windows."""
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        window_vals = values[start:i+1]
        result.append(sum(window_vals) / len(window_vals))
    return result
```

### Trend Detection
```python
import math

def linear_trend(xs, ys):
    """Simple linear regression. Returns (slope, intercept, r_squared)."""
    n = len(xs)
    if n < 2:
        return 0, ys[0] if ys else 0, 0
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x*y for x, y in zip(xs, ys))
    sum_x2 = sum(x*x for x in xs)
    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return 0, sum_y / n, 0
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    # R-squared
    mean_y = sum_y / n
    ss_tot = sum((y - mean_y)**2 for y in ys)
    ss_res = sum((y - (slope * x + intercept))**2 for x, y in zip(xs, ys))
    r_sq = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return slope, intercept, r_sq

# Usage
slope, intercept, r_sq = linear_trend(range(len(values)), values)
direction = "increasing" if slope > 0 else "decreasing" if slope < 0 else "flat"
print(f"Trend: {direction} ({slope:+.2f} per period, R²={r_sq:.3f})")
```

## Statistical Analysis

### Descriptive Statistics (no dependencies)
```python
import math

def percentile(sorted_vals, p):
    """Compute p-th percentile (0-100) using linear interpolation."""
    n = len(sorted_vals)
    if n == 0:
        return 0
    if n == 1:
        return sorted_vals[0]
    k = (p / 100) * (n - 1)
    lo = int(math.floor(k))
    hi = min(lo + 1, n - 1)
    frac = k - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])

def describe(values):
    """Descriptive stats. Uses sample variance (n-1) for std_dev."""
    if not values:
        return {"count": 0, "mean": 0, "median": 0, "std_dev": 0,
                "min": 0, "max": 0, "q1": 0, "q3": 0, "iqr": 0}
    n = len(values)
    sorted_v = sorted(values)
    mean = sum(values) / n
    median = percentile(sorted_v, 50)
    variance = sum((x - mean) ** 2 for x in values) / max(n - 1, 1)
    std_dev = math.sqrt(variance)
    q1 = percentile(sorted_v, 25)
    q3 = percentile(sorted_v, 75)

    return {
        "count": n,
        "mean": mean,
        "median": median,
        "std_dev": std_dev,
        "min": sorted_v[0],
        "max": sorted_v[-1],
        "q1": q1,
        "q3": q3,
        "iqr": q3 - q1,
    }
```

### Outlier Detection (IQR method)
```python
stats = describe(values)
lower_bound = stats['q1'] - 1.5 * stats['iqr']
upper_bound = stats['q3'] + 1.5 * stats['iqr']
outliers = [(i, v) for i, v in enumerate(values) if v < lower_bound or v > upper_bound]
print(f"Outliers ({len(outliers)}): values outside [{lower_bound:.2f}, {upper_bound:.2f}]")
for i, v in outliers:
    print(f"  Row {i}: {v}")
```

### Correlation (Pearson, no dependencies)
```python
def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return 0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x)**2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y)**2 for y in ys))
    if den_x == 0 or den_y == 0:
        return 0
    return num / (den_x * den_y)

# Interpretation: |r| > 0.7 strong, 0.4-0.7 moderate, < 0.4 weak
```

## Data Cleaning

### Common Cleaning Operations
```python
# Remove duplicates
seen = set()
deduped = []
for row in rows:
    key = (row['id'],)  # or tuple of uniqueness columns
    if key not in seen:
        seen.add(key)
        deduped.append(row)
print(f"Removed {len(rows) - len(deduped)} duplicates")

# Normalize whitespace
for row in rows:
    for key in row:
        if isinstance(row[key], str):
            row[key] = ' '.join(row[key].split())

# Parse dates consistently
from datetime import datetime
DATE_FORMATS = ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d', '%B %d, %Y']
def parse_date(s):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None

# Fill missing values
for row in rows:
    if not row.get('category'):
        row['category'] = 'Unknown'
```

### Data Quality Report
```python
print("DATA QUALITY REPORT")
print("=" * 60)
total_cells = len(rows) * len(columns)
null_cells = sum(1 for row in rows for col in columns if not row.get(col, '').strip())
print(f"Total cells: {total_cells}")
print(f"Null/empty: {null_cells} ({null_cells/total_cells*100:.1f}%)")
print(f"Complete rows: {sum(1 for row in rows if all(row.get(c, '').strip() for c in columns))}")

# Per-column quality
for col in columns:
    values = [row.get(col, '') for row in rows]
    nulls = sum(1 for v in values if not v.strip())
    uniques = len(set(v.strip() for v in values if v.strip()))
    print(f"  {col}: {nulls} nulls, {uniques} unique values")
```

## Joining / Merging Data

### Join Two CSVs on a Key Column
```python
import csv, sys

# Read both files into dicts keyed by join column
def read_keyed(path, key_col, encoding='utf-8-sig'):
    with open(path, encoding=encoding) as f:
        rows = list(csv.DictReader(f))
    return {row[key_col]: row for row in rows}

left = read_keyed(sys.argv[1], 'id')
right = read_keyed(sys.argv[2], 'id')

# Inner join
joined = []
for key in left:
    if key in right:
        merged = {**left[key], **right[key]}
        joined.append(merged)

print(f"Left: {len(left)}, Right: {len(right)}, Joined: {len(joined)}")

# Left join (keep all left rows, fill missing right columns with '')
all_right_cols = set()
for row in right.values():
    all_right_cols.update(row.keys())

left_joined = []
for key, lrow in left.items():
    rrow = right.get(key, {})
    merged = {**lrow, **{c: rrow.get(c, '') for c in all_right_cols}}
    left_joined.append(merged)
```

## Filtering and Export

### Filter Rows and Write Output
```python
import csv, sys

with open(sys.argv[1], encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

# Filter example — adapt the condition
filtered = [r for r in rows if float(r.get('amount', 0) or 0) > 100]
print(f"Filtered: {len(filtered)} of {len(rows)} rows")

# Write filtered CSV
if filtered:
    with open('filtered_output.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=filtered[0].keys())
        writer.writeheader()
        writer.writerows(filtered)
    print(f"Wrote filtered_output.csv")
```

### CSV to JSON Conversion
```python
import csv, json, sys

with open(sys.argv[1], encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

with open('output.json', 'w') as f:
    json.dump(rows, f, indent=2)
print(f"Converted {len(rows)} rows to output.json")
```

## Report Templates

### Analysis Report Structure
When saving analysis to a workspace file:

```markdown
# {Analysis Title} — {Date}

## Summary
One paragraph with the key finding and its significance.

## Data Overview
- **Source**: {file name or description}
- **Records**: {count}
- **Date range**: {earliest} to {latest}
- **Data quality**: {good/fair/poor} — {details}

## Key Findings

### Finding 1: {Headline}
{Description with specific numbers}

| Metric | Value |
|--------|-------|
| ... | ... |

### Finding 2: {Headline}
...

## Methodology
- {How the analysis was performed}
- {Assumptions made}
- {Filters applied}

## Caveats
- {Data quality issues}
- {Missing data impact}
- {Limitations of analysis}

## Appendix
{Detailed tables, full distributions, raw outputs}
```

### Comparison Report
```markdown
# {A} vs {B} Comparison — {Date}

## Verdict
{One sentence — which is better and why, or key difference}

| Dimension | {A} | {B} | Winner |
|-----------|-----|-----|--------|
| Metric 1 | val | val | A/B/Tie |
| Metric 2 | val | val | A/B/Tie |
| ... | ... | ... | ... |

## Detail
### {Dimension 1}
...
```

## Large Dataset Patterns

### Streaming CSV Processing (for files too large for memory)
```python
import csv, sys

stats = {'count': 0, 'sum': 0.0}
with open(sys.argv[1], encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        stats['count'] += 1
        try:
            stats['sum'] += float(row.get('amount', 0) or 0)
        except ValueError:
            pass  # skip non-numeric values

print(f"Processed {stats['count']} rows")
print(f"Total: {stats['sum']:,.2f}")
if stats['count'] > 0:
    print(f"Average: {stats['sum']/stats['count']:,.2f}")
```

### Sampling for Quick Estimates
```python
import random
sample_size = min(1000, len(rows))
sample = random.sample(rows, sample_size)
# Analyze sample, then note: "Based on {sample_size} sample of {len(rows)} total rows"
```

## Key Principles

1. **Show your work** — print intermediate results so the user can verify.
2. **Validate before transforming** — check data types, handle nulls, report anomalies before aggregating.
3. **Size awareness** — for files >10K rows, use streaming. For >100K rows, sample first to validate approach, then full run.
4. **Reproducibility** — save scripts to workspace files so analysis can be re-run with updated data.
