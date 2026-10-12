"""Deterministic suggestions only: never coerce stored CSV strings."""
from datetime import date
import re


def profile(parsed):
    columns = []
    for index, name in enumerate(parsed.headers):
        raw = [record.raw_values[index] for record in parsed.records]
        values = [value.strip() for value in raw if value.strip()]
        candidate, ambiguous = 'string', False
        if values and all(re.fullmatch(r'[+-]?(?:0|[1-9][0-9]*)', value) for value in values):
            candidate = 'integer'
        elif values and all(re.fullmatch(r'[+-]?[0-9]+[.,][0-9]+', value) for value in values):
            candidate, ambiguous = 'decimal', True
        elif values and all(re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value) for value in values):
            try:
                for value in values:
                    date.fromisoformat(value)
                candidate = 'date'
            except ValueError:
                ambiguous = True
        elif any(re.fullmatch(r'[0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4}', value) for value in values):
            ambiguous = True
        columns.append({'name': name, 'type_candidate': candidate,
                        'requires_clarification': ambiguous,
                        'blank_count': len(raw) - len(values),
                        'distinct_count': len(set(raw)),
                        'examples': list(dict.fromkeys(raw))[:3]})
    return {'record_count': parsed.record_count, 'columns': columns}
