"""Deterministic operations bound to a single prepared question's evidence."""
from copy import deepcopy
from decimal import Decimal, localcontext
import operator
import re
from typing import Annotated, Literal

from pydantic import Field

from app.questions import Identity, StrictModel, validated


class FactRef(StrictModel):
    citation_id: Identity
    parameter: Literal['price', 'power', 'length', 'mass', 'luminous_flux', 'color_temperature']
    product: Identity | None = None
    span_index: Annotated[int, Field(ge=0)] | None = None


class Comparison(StrictModel):
    tool: Literal['compare']
    left: FactRef
    operator: Literal['eq', 'ne', 'lt', 'le', 'gt', 'ge']
    right: FactRef


Unit = Literal['W', 'kW', 'mm', 'cm', 'm', 'g', 'kg', 'lm', 'K']


class Conversion(StrictModel):
    tool: Literal['convert']
    fact: FactRef
    unit: Unit


class NumericOperation(StrictModel):
    operation: Annotated[Comparison | Conversion, Field(discriminator='tool')]


# Each multiplier is an exact power of ten to the base unit.
UNITS = {'W': ('power', 0), 'kW': ('power', 3),
         'mm': ('length', -3), 'cm': ('length', -2), 'm': ('length', 0),
         'g': ('mass', -3), 'kg': ('mass', 0),
         'lm': ('luminous_flux', 0), 'K': ('color_temperature', 0)}
LABELS = {'power': r'power|rated power|Leistung|Nennleistung|Systemleistung',
          'length': r'length|Länge', 'mass': r'mass|weight|Gewicht',
          'luminous_flux': r'luminous flux|Lichtstrom',
          'color_temperature': r'color temperature|colour temperature|Farbtemperatur'}


def converted(fact, unit):
    original = fact['unit']
    if original not in UNITS or UNITS[original][0] != UNITS[unit][0]:
        raise Unavailable('incompatible_unit')
    power = UNITS[original][1] - UNITS[unit][1]
    value = Decimal(fact['value'])
    with localcontext() as context:
        context.prec = max(28, len(value.as_tuple().digits) + abs(power) + 2)
        factor = Decimal(10) ** power
        result = value * factor
    text = format(result, 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return {'value': text, 'unit': unit, 'factor': format(factor, 'f'),
            'basis': f'{original} to {unit}: multiply by 10^{power}'}


class Unavailable(Exception):
    def __init__(self, reason):
        self.reason = reason


class EvidenceTools:
    """Construct only from a backend-prepared bundle, never an HTTP request body."""
    def __init__(self, bundle):
        self.sources = {e['citation_id']: deepcopy(e['source']) for e in bundle['evidence']}

    def _fact(self, reference):
        source = self.sources.get(reference.citation_id)
        if source is None:
            raise Unavailable('unknown_citation')
        origin = {'citation_id': reference.citation_id, 'document_id': source['document_id'],
                  'evidence_id': source['evidence_id'], 'locator': deepcopy(source['locator'])}
        if source['locator']['kind'] != 'csv':
            spans = source.get('source_spans', [])
            if (reference.parameter not in LABELS or reference.product is None or
                    reference.span_index is None or reference.span_index >= len(spans)):
                raise Unavailable('unverified_relationship')
            if source.get('context') or len(spans) != 1:
                # Other spans may qualify/negate the statement. Preserve them for
                # partial answers, but do not infer their applicability to arithmetic.
                raise Unavailable('unverified_context')
            # The whole retained span must make one explicit assertion. Substring
            # presence across rows/headers never establishes product ownership.
            span = spans[reference.span_index]
            pattern = (re.escape(reference.product) + r'\s+(?P<label>(?i:' + LABELS[reference.parameter] +
                       r'))\s*:\s*(?P<value>[+-]?[0-9]+(?:[.,][0-9]+)?)\s*'
                       r'(?P<unit>kW|W|mm|cm|m|kg|g|lm|K)'
                       r'(?:\s+\((?P<qualifiers>[^()\n]+)\))?')
            match = re.fullmatch(pattern, span['text'].strip())
            if match is None:
                raise Unavailable('unverified_relationship')
            raw, unit = match['value'], match['unit']
            if len(raw) > 1000 or re.fullmatch(r'[+-]?[1-9][0-9]{0,2}[.,][0-9]{3}', raw):
                raise Unavailable('ambiguous_numeric_format')
            if UNITS[unit][0] != reference.parameter:
                raise Unavailable('incompatible_unit')
            return {**origin, 'product': reference.product, 'parameter': reference.parameter,
                    'value': str(Decimal(raw.replace(',', '.'))), 'raw_value': raw, 'unit': unit,
                    'raw_parameter': match['label'], 'qualifiers': match['qualifiers'] or '', 'span': deepcopy(span),
                    'context': deepcopy(source.get('context', []))}
        if (reference.parameter != 'price' or reference.span_index is not None or
                reference.product is not None and reference.product != source['order_id']):
            raise Unavailable('unverified_relationship')
        if source['price_status'] != 'valid':
            raise Unavailable('price_' + source['price_status'])
        return {**origin,
                'product': source['order_id'], 'parameter': 'price', 'raw_parameter': 'Listenpreis',
                'qualifiers': source['raw_values'][source['headers'].index('gültig ab')],
                'value': source['price'], 'raw_value': source['raw_values'][source['headers'].index('Listenpreis')],
                'unit': None}

    def execute(self, operation):
        operation = validated(NumericOperation, {'operation': operation}, 'invalid_numeric_tool').operation
        try:
            if isinstance(operation, Conversion):
                fact = self._fact(operation.fact)
                return {'status': 'ok', 'fact': fact, 'converted': converted(fact, operation.unit)}
            left, right = self._fact(operation.left), self._fact(operation.right)
            if (left['parameter'] != right['parameter'] or left['qualifiers'] != right['qualifiers']
                    or left['raw_parameter'].casefold() != right['raw_parameter'].casefold()):
                raise Unavailable('incomparable_facts')
            if left['parameter'] == 'price' and left['document_id'] != right['document_id']:
                raise Unavailable('price_basis_unknown')
            comparable = (converted(right, left['unit']) if left['unit'] is not None else
                          {'value': right['value'], 'unit': None, 'factor': '1',
                           'basis': 'Stored numeric prices only; currency, tax and discounts are not inferred.'})
            return {'status': 'ok', 'left': left, 'right': right, 'operator': operation.operator,
                    'result': getattr(operator, operation.operator)(Decimal(left['value']), Decimal(comparable['value'])),
                    'right_converted': comparable, 'basis': comparable['basis']}
        except Unavailable as exc:
            return {'status': 'unavailable', 'reason': exc.reason}
