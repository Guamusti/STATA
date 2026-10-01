import io
import json

import pandas as pd
from fastapi.testclient import TestClient

from app.main import app


def client():
    c = TestClient(app)
    assert c.get('/api/state').status_code == 200
    return c


def test_full_excel_analysis_export_restore():
    c = client()
    book = io.BytesIO()
    with pd.ExcelWriter(book, engine='openpyxl') as writer:
        pd.DataFrame({'ignored': [1]}).to_excel(writer, sheet_name='Inicio', index=False)
        pd.DataFrame({'Año': [2020,2021,2022,2023,2024], 'Ventas': [12,13,18,19,24]}).to_excel(writer, sheet_name='Análisis', index=False)
    raw = book.getvalue()
    assert c.post('/api/sheets', files={'file': ('sample.xlsx',raw)}).json()['sheets'] == ['Inicio','Análisis']
    response = c.post('/api/import?sheet=An%C3%A1lisis', files={'file': ('sample.xlsx', raw)})
    assert response.status_code == 200
    assert response.json()['rows'] == 5
    assert response.json()['variables'][0]['name'] == 'Ano'
    result = c.post('/api/command', json={'command':'regress Ventas Ano, robust'})
    assert result.status_code == 200, result.text
    assert result.json()['result']['metrics']['N'] == 5
    assert c.patch('/api/cell',json={'row':0,'column':'Ventas','value':'12.5'}).status_code == 200
    exported = c.get('/api/export/xlsx')
    assert pd.read_excel(io.BytesIO(exported.content)).iloc[0]['Ventas'] == 12.5
    saved = c.get('/api/export/project').content
    other = client()
    restored = other.post('/api/project',files={'file':('project.json',saved)})
    assert restored.status_code == 200
    assert restored.json()['data']['rows'][0][1] == 12.5
    assert len(restored.json()['history']) == 3
    assert 'regress Ventas Ano, robust' in other.get('/api/export/do').text


def test_csv_decimal_pagination_search_and_isolation():
    c = client()
    csv = 'nombre;valor\nAna;1,5\nBea;2,5\n'
    result = c.post('/api/import?delimiter=%3B&decimal=%2C',files={'file':('datos.csv',csv.encode())})
    assert result.status_code == 200
    assert result.json()['data']['rows'][0][1] == 1.5
    assert c.get('/api/state?search=Bea').json()['filteredRows'] == 1
    assert client().get('/api/state').json()['rows'] == 0
    assert c.post('/api/demo').status_code == 200
    assert len(c.get('/api/state?page=2').json()['data']['rows']) == 40


def test_failed_import_preserves_data_and_error_history():
    c=client(); c.post('/api/demo')
    assert c.post('/api/import',files={'file':('broken.xlsx',b'bad data')}).status_code == 400
    assert c.get('/api/state').json()['rows'] == 240
    assert c.post('/api/command',json={'command':'regress salario sector'}).status_code == 400
    assert c.get('/api/state').json()['history'][-1]['error']


def test_cross_origin_protection():
    c=client()
    assert c.post('/api/demo',headers={'Origin':'https://untrusted.example'}).status_code == 403
    assert c.get('/',headers={'Host':'untrusted.example'}).status_code == 403


def test_formula_export_and_missing_values():
    c=client()
    c.post('/api/import',files={'file':('datos.csv',b'name,value\n=1+1,\nnormal,4\n')})
    output=c.get('/api/export/xlsx')
    data=pd.read_excel(io.BytesIO(output.content))
    assert data.iloc[0]['name'] == "'=1+1"
    assert c.get('/api/state').json()['data']['rows'][0][1] is None
