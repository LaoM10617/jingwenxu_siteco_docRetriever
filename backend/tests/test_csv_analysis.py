from decimal import Decimal
import pytest
from app.csv_runtime import decimal_value


def test_decimal_preserves_german_money_and_rejects_ambiguous_conversion():
    assert decimal_value('1.234,50', decimal_separator=',', thousands_separator='.') == Decimal('1234.50')
    with pytest.raises(ValueError):
        decimal_value('1,234')
    assert decimal_value('', missing='exclude') is None
    with pytest.raises(ValueError):
        decimal_value('NA')


def test_exact_sum_avoids_decimal_default_precision_rounding():
    from app.csv_runtime import exact_sum
    assert exact_sum([Decimal('123456789012345678901234567890.01'), Decimal('0.02')]) == Decimal('123456789012345678901234567890.03')
    with pytest.raises(ValueError):
        exact_sum([1.20])


def test_decimal_rejects_values_already_coerced_through_float():
    with pytest.raises(ValueError):
        decimal_value(1.2)


def test_wrong_module_helper_imports_are_dropped_and_profile_reports_format():
    from app.csv_specialist import _numeric_profile, strip_shadow_imports
    script = 'from decimals import decimals\nfrom decimal import Decimal\nfrom siteco_analysis import emit\nx = 1'
    assert strip_shadow_imports(script) == 'from decimal import Decimal\nfrom siteco_analysis import emit\nx = 1'
    assert _numeric_profile(['7,41E-20', '1,43', '', '0']) == {'numeric': {'numeric_values': 3,
        'non_numeric_values': 0, 'decimal_separator': ',', 'scientific_notation': True}}
    assert _numeric_profile(['kg', '']) == {}
