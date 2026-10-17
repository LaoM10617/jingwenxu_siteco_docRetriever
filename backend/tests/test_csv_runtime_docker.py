"""Real pandas/helper checks, enabled with SITECO_DOCKER_TESTS and runner digest."""
import os
import json

import pytest

from app.python_executor import PythonExecutor


pytestmark = pytest.mark.skipif(
    os.getenv('SITECO_DOCKER_TESTS') != '1' or not os.getenv('SITECO_RUNNER_IMAGE'),
    reason='requires enabled Docker and a pinned pandas runner image')


def execute(tmp_path, script):
    result = PythonExecutor(tmp_path, image=os.environ['SITECO_RUNNER_IMAGE']).execute(script, {})
    assert result.status == 'completed', result.diagnostic
    assert result.cleaned_up
    assert not list(tmp_path.iterdir())
    return result.value


def test_real_pandas_merge_cardinality_and_expansion(tmp_path):
    value = execute(tmp_path, '''import json
import pandas as pd
from siteco_analysis import merge
left = pd.DataFrame({'id':['001','001'], 'left':[1,2]})
right = pd.DataFrame({'id':['001','001'], 'right':[3,4]})
try:
    merge(left, right, on='id', cardinality='one_to_one')
    rejected = False
except pd.errors.MergeError:
    rejected = True
result, diagnostic = merge(left, right, on='id', cardinality='many_to_many')
print(json.dumps({'rejected':rejected, 'ids':result['id'].tolist(),
    'pairs':result[['left','right']].values.tolist(), 'diagnostic':diagnostic}))
''')
    assert value['rejected']
    assert value['ids'] == ['001'] * 4
    assert value['pairs'] == [[1, 3], [1, 4], [2, 3], [2, 4]]
    assert value['diagnostic']['expanded']
    assert value['diagnostic']['result_rows'] == 4
    assert value['diagnostic']['left_rows'] == value['diagnostic']['right_rows'] == 2


def test_real_pandas_merge_blank_keys_are_explicit(tmp_path):
    value = execute(tmp_path, '''import json
import pandas as pd
from siteco_analysis import merge
left = pd.DataFrame({'id':['001','',None,'  ']})
right = pd.DataFrame({'id':['001','',None]})
try:
    merge(left, right, on='id', cardinality='one_to_one', null_keys='reject')
    rejected = False
except ValueError:
    rejected = True
result, diagnostic = merge(left, right, on='id', cardinality='one_to_one', null_keys='exclude')
print(json.dumps({'rejected':rejected, 'ids':result['id'].tolist(), 'diagnostic':diagnostic}))
''')
    assert value['rejected']
    assert value['ids'] == ['001']
    assert value['diagnostic']['left_blank_keys'] == 3
    assert value['diagnostic']['right_blank_keys'] == 2
    assert value['diagnostic']['null_keys'] == 'exclude'
    assert not value['diagnostic']['expanded']


def test_real_pandas_decimal_tail_and_literal_na(tmp_path):
    value = execute(tmp_path, '''import json
import pandas as pd
from siteco_analysis import decimals, exact_sum
values = decimals(pd.Series(['123456789012345678901234567890,01','0,02','']),
    decimal_separator=',', missing='exclude')
try:
    decimals(pd.Series(['NA']), missing='exclude')
    rejected = False
except ValueError:
    rejected = True
print(json.dumps({'sum':str(exact_sum(values)), 'na_rejected':rejected,
    'blank_excluded':values.iloc[2] is None, 'pandas_version':pd.__version__}))
''')
    assert value['sum'] == '123456789012345678901234567890.03'
    assert value['na_rejected']
    assert value['blank_excluded']
    assert value['pandas_version'] == '3.0.6'


def test_load_artifacts_keeps_complete_prior_result_and_raw_values(tmp_path):
    source = tmp_path / 'artifacts.json'
    rows = [[f'{index:04}', 'NA' if index == 149 else '1.20'] for index in range(150)]
    source.write_text(json.dumps([{'artifact_id': 'previous', 'payload': {
        'columns': ['id', 'value'], 'rows': rows}}]), encoding='utf-8')
    before = source.read_bytes()
    jobs_dir = tmp_path / 'jobs'
    jobs_dir.mkdir()
    result = PythonExecutor(jobs_dir, image=os.environ['SITECO_RUNNER_IMAGE']).execute('''import json
from siteco_analysis import load_artifacts
frame = load_artifacts()['previous']
print(json.dumps({'count':len(frame), 'first':frame.iloc[0].tolist(),
                  'last':frame.iloc[-1].tolist()}))
''', {'artifacts.json': source})
    assert result.status == 'completed', result.diagnostic
    assert result.cleaned_up and not list(jobs_dir.iterdir())
    assert result.value == {'count': 150, 'first': ['0000', '1.20'], 'last': ['0149', 'NA']}
    assert source.read_bytes() == before


def test_auto_separator_scientific_notation_mean_and_tied_top_n(tmp_path):
    value = execute(tmp_path, '''import json
from decimal import Decimal
import pandas as pd
from siteco_analysis import decimals, exact_mean, top_n
parsed = decimals(pd.Series(['7,41E-20', '1,43', '0', '']), missing='exclude')
try:
    decimals(pd.Series(['1,5', '2.5']))
    mixed_rejected = False
except ValueError:
    mixed_rejected = True
frame = pd.DataFrame({'k': list('abcde'), 'v': [Decimal(3), None, Decimal(2), Decimal(2), Decimal(1)]})
best, diagnostic = top_n(frame, 'v', 2)
try:
    top_n(pd.DataFrame({'v': ['92', '618']}), 'v', 1)
    text_rejected = False
except ValueError:
    text_rejected = True
print(json.dumps({'text_rejected': text_rejected, 'threshold': str(decimals('100')), 'empty_thousands': str(decimals(pd.Series(['1,5']), thousands_separator='')[0]), 'ints': [str(v) for v in decimals(pd.Series([100, Decimal(7)]))], 'parsed': [None if v is None else str(v) for v in parsed], 'mixed_rejected': mixed_rejected,
    'mean': str(exact_mean([Decimal(1), Decimal(2), None])), 'top': list(best['k']), 'diagnostic': diagnostic}))
''')
    assert value['parsed'] == ['7.41E-20', '1.43', '0', None]
    assert value['mixed_rejected']
    assert value['mean'] == '1.5'
    assert value['text_rejected'] and value['threshold'] == '100' and value['ints'] == ['100', '7']
    assert value['empty_thousands'] == '1.5'
    assert value['top'] == ['a', 'c', 'd']
    assert value['diagnostic']['excluded_missing'] == 1 and value['diagnostic']['ties_included'] == 1
