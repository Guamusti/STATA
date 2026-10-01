import io
import json
import math
import os
import threading
import time
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import Workspace, table

app = FastAPI(title='STATA Studio', docs_url=None, redoc_url=None)
ROOT = Path(__file__).parent.parent
sessions = {}
lock = threading.RLock()
MAX_UPLOAD = 20 * 1024 * 1024


def clean(value):
    if isinstance(value, dict): return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [clean(v) for v in value]
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (float, np.floating)): return float(value) if math.isfinite(value) else None
    if isinstance(value, (pd.Timestamp,)): return value.isoformat()
    if isinstance(value, np.bool_): return bool(value)
    return value


@app.middleware('http')
async def local_only(request: Request, call_next):
    # Prevent drive-by writes to a localhost service from a different website.
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD') and origin and origin != str(request.base_url).rstrip('/'):
        return Response('Origen no permitido', status_code=403)
    host = request.url.hostname
    if host not in ('127.0.0.1', 'localhost', 'testserver'):
        return Response('Servidor local', status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    return response


def workspace(request, response):
    sid = request.cookies.get('studio_session')
    with lock:
        # Idle browser workspaces expire after 24 hours. No uploaded data is written to disk.
        now = time.monotonic()
        expired = [key for key, (_, used) in sessions.items() if now-used > 86400]
        for key in expired: del sessions[key]
        if sid not in sessions:
            if len(sessions) >= 32: raise HTTPException(503, 'Demasiadas sesiones abiertas.')
            sid = uuid.uuid4().hex
            sessions[sid] = (Workspace(), now)
            response.set_cookie('studio_session', sid, httponly=True, samesite='strict')
        ws = sessions[sid][0]
        sessions[sid] = (ws, now)
    return ws


def state(ws, page=0, search=''):
    df = ws.df
    if search and len(df.columns):
        selected = df.astype(str).apply(lambda c: c.str.contains(search, case=False, regex=False)).any(axis=1)
        df = df.loc[selected]
    shown = df.iloc[page*100:(page+1)*100]
    return clean({'name': ws.name, 'rows': len(ws.df), 'filteredRows': len(df), 'page': page,
        'variables': [{'name': c, 'type': 'number' if pd.api.types.is_numeric_dtype(ws.df[c]) else 'text',
                       'missing': int(ws.df[c].isna().sum()), 'unique': int(ws.df[c].nunique())} for c in ws.df],
        'data': table(shown), 'indices': shown.index.tolist(), 'missing': int(ws.df.isna().sum().sum()),
        'history': ws.history, 'canUndo': bool(ws.backups)})


@app.get('/api/state')
def get_state(request: Request, response: Response, page: int = Query(0, ge=0), search: str = ''):
    with lock: return state(workspace(request, response), page, search)


@app.get('/api/help')
def help_reference():
    return Workspace().execute('help')


class Command(BaseModel):
    command: str = Field(min_length=1, max_length=4000)


@app.post('/api/command')
def run_command(body: Command, request: Request, response: Response):
    with lock:
        ws = workspace(request, response)
        try:
            result = ws.run(body.command)
            return clean({'result': result, 'state': state(ws)})
        except (ValueError, SyntaxError, TypeError, KeyError, ZeroDivisionError, OverflowError, np.linalg.LinAlgError) as exc:
            message = str(exc) or 'No se ha podido ejecutar el comando.'
            ws.history.append({'command': body.command, 'error': message})
            raise HTTPException(400, message) from exc


@app.post('/api/demo')
def demo(request: Request, response: Response):
    rng = np.random.default_rng(17)
    n = 240
    education = rng.integers(8, 22, n)
    experience = rng.integers(0, 35, n)
    df = pd.DataFrame({'id': range(1, n+1), 'edad': experience+education+6, 'educacion': education,
        'experiencia': experience, 'salario': np.round(650+education*105+experience*43+rng.normal(0, 310, n), 2),
        'sector': rng.choice(['Servicios', 'Industria', 'Tecnología'], n), 'teletrabajo': rng.integers(0, 2, n)})
    df.loc[[12, 58, 109, 201], 'salario'] = np.nan
    with lock:
        ws = workspace(request, response); ws.load(df, 'mercado_laboral · ejemplo sintético')
        ws.history.append({'command': '* Datos de ejemplo: semilla 17, 240 observaciones', 'result': {'title': 'Ejemplo cargado', 'message': 'Datos sintéticos para explorar las funciones; no representan una encuesta real.'}})
        return state(ws)


async def read_upload(file):
    data = await file.read(MAX_UPLOAD+1)
    if len(data) > MAX_UPLOAD: raise HTTPException(413, 'El archivo supera el límite de 20 MB.')
    return data


@app.post('/api/sheets')
async def sheets(file: UploadFile = File(...)):
    raw = await read_upload(file)
    try:
        with pd.ExcelFile(io.BytesIO(raw), engine='openpyxl') as book:
            return {'sheets': book.sheet_names}
    except Exception as exc: raise HTTPException(400, 'No se puede abrir este libro XLSX.') from exc


@app.post('/api/import')
async def import_file(request: Request, response: Response, file: UploadFile = File(...), sheet: str = '', delimiter: str = ',', decimal: str = '.'):
    raw = await read_upload(file)
    name = Path(file.filename or 'datos').name
    ext = Path(name).suffix.lower()
    try:
        if ext == '.xlsx':
            df = pd.read_excel(io.BytesIO(raw), sheet_name=sheet or 0, engine='openpyxl', nrows=250001)
        elif ext in ('.csv', '.tsv'):
            if delimiter not in (',', ';', '\t') or decimal not in ('.', ','): raise ValueError('Separador no válido.')
            df = pd.read_csv(io.BytesIO(raw), sep='\t' if ext == '.tsv' else delimiter, decimal=decimal, nrows=250001)
        else: raise ValueError('Usa un archivo XLSX, CSV o TSV.')
        if not len(df.columns): raise ValueError('El archivo no contiene columnas.')
        with lock:
            ws = workspace(request, response); ws.load(df, name)
            ws.history.append({'command': f'* Importado {name}' + (f' · hoja {sheet}' if sheet else ''), 'result': {'title': 'Datos importados', 'message': f'{len(df)} observaciones. Los encabezados se han normalizado para usarlos como variables.'}})
            return state(ws)
    except Exception as exc: raise HTTPException(400, f'No se pudo importar: {exc}') from exc


class Cell(BaseModel):
    row: int = Field(ge=0)
    column: str
    value: str = Field(max_length=10000)


@app.patch('/api/cell')
def edit_cell(body: Cell, request: Request, response: Response):
    with lock:
        ws = workspace(request, response)
        if body.column not in ws.df or body.row not in ws.df.index: raise HTTPException(400, 'Celda no válida.')
        value = body.value if body.value else np.nan
        if pd.api.types.is_numeric_dtype(ws.df[body.column]) and body.value:
            try:
                value = float(body.value)
                if not math.isfinite(value): raise ValueError()
            except ValueError: raise HTTPException(400, 'Esta variable solo admite números finitos.')
        new = ws.df.copy(deep=True)
        if pd.api.types.is_numeric_dtype(new[body.column]): new[body.column] = new[body.column].astype(float)
        new.at[body.row, body.column] = value
        ws.save(); ws.df = new
        ws.history.append({'command': f'* Edición manual: fila {body.row+1}, variable {body.column}', 'result': {'title': 'Celda actualizada'}})
        return state(ws)


@app.get('/api/export/{kind}')
def export(kind: str, request: Request, response: Response):
    with lock:
        ws = workspace(request, response)
        if kind == 'do':
            content = '* STATA Studio: subconjunto de comandos. Importe los datos originales antes de ejecutar.\n' + '\n'.join(h['command'] if not h.get('error') else '* ERROR: '+h['command'] for h in ws.history)
            return Response(content, media_type='text/plain', headers={'Content-Disposition': 'attachment; filename="analisis.do"'})
        if kind == 'project':
            content = json.dumps(clean({'version': 1, 'name': ws.name, 'data': table(ws.df), 'history': ws.history}), ensure_ascii=False)
            return Response(content, media_type='application/json', headers={'Content-Disposition': 'attachment; filename="proyecto.studio.json"'})
        if kind not in ('csv', 'xlsx'): raise HTTPException(404)
        # Neutralize spreadsheet formulas in text cells on export.
        df = ws.df.copy()
        for c in df:
            if not pd.api.types.is_numeric_dtype(df[c]):
                df[c] = df[c].map(lambda v: "'"+v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v)
        buffer = io.BytesIO()
        if kind == 'csv': buffer.write(df.to_csv(index=False).encode('utf-8-sig'))
        else: df.to_excel(buffer, index=False, engine='openpyxl')
        buffer.seek(0)
        return StreamingResponse(buffer, media_type='text/csv' if kind == 'csv' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': f'attachment; filename="datos.{kind}"'})


@app.post('/api/project')
async def restore_project(request: Request, response: Response, file: UploadFile = File(...)):
    raw = await read_upload(file)
    try:
        obj = json.loads(raw)
        if obj.get('version') != 1: raise ValueError('Versión no admitida.')
        df = pd.DataFrame(obj['data']['rows'], columns=obj['data']['columns'])
        history = obj.get('history', [])
        if not isinstance(history, list) or any(not isinstance(h, dict) or not isinstance(h.get('command'), str) for h in history): raise ValueError('Historial no válido.')
        with lock:
            ws = workspace(request, response); ws.load(df, str(obj['name'])); ws.history = history
            return state(ws)
    except Exception as exc: raise HTTPException(400, f'Proyecto no válido: {exc}') from exc


@app.get('/')
def index(): return FileResponse(ROOT / 'static' / 'index.html')


app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
