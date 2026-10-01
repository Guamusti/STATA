import numpy as np
import pandas as pd
import pytest
from scipy import stats

from app.engine import Workspace, expression, normalize_columns


@pytest.fixture
def ws():
    w = Workspace()
    w.load(pd.DataFrame({'x': [1., 2., 3., 4., 5., 6.], 'y': [3., 5., 6., 9., 11., np.nan], 'group': ['A', 'A', 'A', 'B', 'B', 'B']}), 'test')
    return w


def test_summary_sample_standard_deviation(ws):
    out = ws.run('summarize y')['table']
    row = dict(zip(out['columns'], out['rows'][0]))
    assert row['N'] == 5
    assert row['Media'] == pytest.approx(6.8)
    assert row['Desv. est.'] == pytest.approx(np.std([3, 5, 6, 9, 11], ddof=1))


def test_regression_matches_independent_scipy(ws):
    result = ws.run('regress y x')
    ref = stats.linregress([1, 2, 3, 4, 5], [3, 5, 6, 9, 11])
    slope = dict(zip(result['table']['columns'], result['table']['rows'][1]))
    assert slope['Coeficiente'] == pytest.approx(ref.slope)
    assert slope['Error est.'] == pytest.approx(ref.stderr)
    assert slope['p'] == pytest.approx(ref.pvalue)
    assert result['metrics']['N'] == 5
    assert result['metrics']['R²'] == pytest.approx(ref.rvalue**2)
    robust = ws.run('regress y x, robust')
    assert robust['table']['rows'][1][1] == pytest.approx(ref.slope)
    assert robust['table']['rows'][1][2] != pytest.approx(ref.stderr)


def test_mutations_and_undo(ws):
    original = ws.df.copy()
    ws.run('generate double = x * 2')
    assert ws.df['double'].tolist() == [2, 4, 6, 8, 10, 12]
    ws.run('replace double = 0 if group == "A"')
    assert ws.df['double'].tolist()[:3] == [0, 0, 0]
    ws.run('keep if x > 3 & group == "B"')
    assert len(ws.df) == 3
    ws.run('undo'); ws.run('undo'); ws.run('undo')
    pd.testing.assert_frame_equal(ws.df, original)


def test_invalid_command_does_not_mutate(ws):
    original = ws.df.copy()
    with pytest.raises(ValueError): ws.run('drop x unknown')
    pd.testing.assert_frame_equal(ws.df, original)


@pytest.mark.parametrize('expr', ['__import__("os").system("whoami")', 'x.__class__', 'x[0]', '[v for v in x]', 'open("file")', '2 ** 10000'])
def test_unsafe_expressions_rejected(ws, expr):
    with pytest.raises(ValueError): expression(expr, ws.df)


def test_missing_comparisons_and_functions(ws):
    assert expression('y != 3', ws.df).sum() == 4
    assert expression('missing(y)', ws.df).sum() == 1
    ws.run('generate z = log(x)')
    assert ws.df['z'].iloc[0] == 0


def test_normalization():
    df = normalize_columns(pd.DataFrame([[1, 2, 3, 4]], columns=['Año', 'Año', '1 valor', '']))
    assert df.columns.tolist() == ['Ano', 'Ano_2', 'v_1_valor', 'variable']


def test_singular_model_rejected(ws):
    ws.run('generate z = x * 2')
    with pytest.raises(ValueError, match='colinealidad'): ws.run('regress y x z')


def test_welch_and_charts(ws):
    result = ws.run('ttest x, by(group)')
    expected = stats.ttest_ind([1, 2, 3], [4, 5, 6], equal_var=False)
    assert result['metrics']['p bilateral'] == pytest.approx(expected.pvalue)
    histogram = ws.run('histogram x')['chart']['points']
    assert sum(p[2] for p in histogram) == 6
    assert len(ws.run('scatter y x')['chart']['points']) == 5


def test_correlation_uses_complete_cases(ws):
    result = ws.run('correlate x y')
    assert result['table']['rows'][0][2] == pytest.approx(np.corrcoef([1,2,3,4,5], [3,5,6,9,11])[0,1])


def test_strings_integer_updates_and_quoted_if():
    ws = Workspace(); ws.load(pd.DataFrame({'x': [1,2,3]}), 'test')
    ws.run('replace x = 1.5 if x == 1')
    assert ws.df.x.iloc[0] == 1.5
    ws.run('generate label = "a if b, c"')
    assert ws.df.label.tolist() == ['a if b, c'] * 3
    ws.run('replace label = "A & B | C^2!"')
    assert ws.df.label.tolist() == ['A & B | C^2!'] * 3


def test_canonical_stata_options_and_filter(ws):
    a = ws.run('regress y x if x < 5, robust')
    b = ws.run('regress y x, robust if x < 5')
    assert a == b
    assert a['metrics']['N'] == 4
