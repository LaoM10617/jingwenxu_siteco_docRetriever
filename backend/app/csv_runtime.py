"""Pandas helpers shipped into the sandbox; diagnostics are not a security boundary."""
from decimal import Decimal, InvalidOperation, localcontext
import json
from pathlib import Path
import re


def decimal_value(value, *, decimal_separator='.', thousands_separator=None, missing='reject'):
    if not isinstance(value, str):
        raise ValueError('Decimal conversion requires original string values')
    if decimal_separator not in ('.', ',') or thousands_separator not in (None, '.', ',', ' '):
        raise ValueError('Unsupported numeric separators')
    if thousands_separator == decimal_separator or missing not in ('reject', 'exclude', 'zero'):
        raise ValueError('Explicit distinct separators and missing policy required')
    text = value.strip()
    if not text:
        if missing == 'exclude':
            return None
        if missing == 'zero':
            return Decimal(0)
        raise ValueError('Blank numeric value')
    integer = r'[0-9]+'
    if thousands_separator:
        sep = re.escape(thousands_separator)
        integer = rf'(?:[0-9]+|[0-9]{{1,3}}(?:{sep}[0-9]{{3}})+)'
    if not re.fullmatch(rf'[+-]?{integer}(?:{re.escape(decimal_separator)}[0-9]+)?', text):
        raise ValueError('Numeric value does not match the declared separators')
    if thousands_separator:
        text = text.replace(thousands_separator, '')
    try:
        result = Decimal(text.replace(decimal_separator, '.'))
    except InvalidOperation as exc:
        raise ValueError('Invalid decimal') from exc
    if not result.is_finite():
        raise ValueError('Nonfinite decimal')
    return result


def load_tables(path='/inputs/datasets.json'):
    import pandas as pd
    tables = json.loads(Path(path).read_text(encoding='utf-8'))
    return {table['source']['version_id']: pd.DataFrame(
        [row['values'] for row in table['rows']], columns=table['headers'],
        index=pd.Index([row['row_id'] for row in table['rows']], name='source_row_id'), dtype=object)
        for table in tables}


def load_artifacts(path='/inputs/artifacts.json'):
    """Load complete, externally authorized prior results for follow-up analysis."""
    import pandas as pd
    artifacts = json.loads(Path(path).read_text(encoding='utf-8'))
    return {item['artifact_id']: pd.DataFrame(item['payload']['rows'],
        columns=item['payload']['columns'], dtype=object) for item in artifacts}


def decimals(series, *, decimal_separator='.', thousands_separator=None, missing='reject'):
    return series.map(lambda value: decimal_value(value, decimal_separator=decimal_separator,
        thousands_separator=thousands_separator, missing=missing))


def exact_sum(values):
    """Sum Decimal values without the default 28-digit context rounding money."""
    values = [v for v in values if v is not None]
    if any(not isinstance(v, Decimal) or not v.is_finite() for v in values):
        raise ValueError('exact_sum requires finite Decimal values')
    if not values:
        return Decimal(0)
    integer_digits = max(max(1, v.adjusted() + 1) for v in values)
    fractional_digits = max(max(0, -v.as_tuple().exponent) for v in values)
    with localcontext() as context:
        context.prec = integer_digits + fractional_digits + len(str(len(values))) + 1
        return sum(values, Decimal(0))


def merge(left, right, *, on, cardinality, null_keys='reject', how='inner'):
    if cardinality not in ('one_to_one', 'one_to_many', 'many_to_one', 'many_to_many'):
        raise ValueError('Explicit join cardinality required')
    if null_keys not in ('reject', 'exclude', 'match'):
        raise ValueError('Explicit null-key policy required')
    keys = [on] if isinstance(on, str) else list(on)
    def blank(frame):
        return frame[keys].isna().any(axis=1) | frame[keys].apply(lambda s: s.map(lambda v: isinstance(v, str) and not v.strip())).any(axis=1)
    lb, rb = blank(left), blank(right)
    if null_keys == 'reject' and (lb.any() or rb.any()):
        raise ValueError('Join keys contain blanks')
    l, r = (left.loc[~lb], right.loc[~rb]) if null_keys == 'exclude' else (left, right)
    result = l.merge(r, on=keys, how=how, validate=cardinality)
    diagnostic = {'operation': 'merge', 'left_rows': len(left), 'right_rows': len(right),
        'left_blank_keys': int(lb.sum()), 'right_blank_keys': int(rb.sum()),
        'result_rows': len(result), 'cardinality': cardinality, 'null_keys': null_keys,
        'expanded': len(result) > max(len(l), len(r))}
    return result, diagnostic


def emit(frame, *, chart=None, diagnostics=None):
    """Print a finite table; Decimal values remain exact strings."""
    import pandas as pd
    if len(frame) > 20000 or len(frame.columns) > 100:
        raise ValueError('Result too large; request an explicit narrower result')
    def cell(value):
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError('Nonfinite result')
            return str(value)
        if value is None or value is pd.NA:
            return None
        if hasattr(value, 'item'):
            value = value.item()
        if not isinstance(value, (str, int, float, bool)):
            raise ValueError('Unsupported result cell; format dates explicitly')
        return value
    print(json.dumps({'columns': [str(c) for c in frame.columns],
        'rows': [[cell(v) for v in row] for row in frame.itertuples(index=False, name=None)],
        'chart': chart, 'diagnostics': diagnostics or []}, ensure_ascii=False, allow_nan=False))
