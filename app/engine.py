"""Explicit, restricted Stata-like grammar. Never executes Python or shell input."""
import ast
import operator
import re
import unicodedata

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats


HELP = {
    'describe': 'Tipos de variables y valores ausentes.',
    'summarize [variables]': 'Media, desviación estándar muestral, percentiles y rango.',
    'count [if expresión]': 'Número de observaciones.',
    'list [variables] [if expresión]': 'Primeras 200 observaciones.',
    'tabulate variable': 'Frecuencias, incluidos los valores ausentes.',
    'correlate var1 var2 ...': 'Correlación de Pearson con casos completos.',
    'regress y x1 x2 [, robust]': 'Mínimos cuadrados con constante; robust usa HC1.',
    'ttest variable, by(grupo)': 'Prueba t de Welch entre dos grupos.',
    'histogram variable': 'Histograma de una variable numérica.',
    'scatter y x': 'Diagrama de dispersión (máximo 5.000 puntos).',
    'generate nueva = expresión': 'Crear variable: + - * / **, log(), sqrt(), abs(), exp().',
    'replace variable = expresión [if condición]': 'Cambiar valores de una variable.',
    'keep if condición': 'Conservar observaciones que cumplen la condición.',
    'drop if condición': 'Eliminar observaciones que cumplen la condición.',
    'keep var1 var2 / drop var1 var2': 'Conservar o eliminar variables.',
    'rename anterior nueva': 'Renombrar una variable.',
    'sort var1 [var2]': 'Orden ascendente; los ausentes quedan al final.',
    'undo': 'Deshacer el último cambio de datos (hasta 20 cambios).',
    'help': 'Ver esta referencia. if: summarize, count, list, tabulate, correlate, regress, ttest, histogram, scatter, generate, replace, keep, drop.',
}


def normalize_columns(df):
    names, seen = [], set()
    for col in df.columns:
        name = unicodedata.normalize('NFKD', str(col)).encode('ascii', 'ignore').decode()
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name).strip('_') or 'variable'
        if name[0].isdigit():
            name = 'v_' + name
        base, i = name, 2
        while name in seen:
            name = f'{base}_{i}'
            i += 1
        names.append(name)
        seen.add(name)
    df.columns = names
    return df


def table(df):
    return {'columns': list(df.columns), 'rows': df.astype(object).where(pd.notna(df), None).values.tolist()}


def expression(text, df):
    """Small AST interpreter: no attributes, indexing, imports, eval or arbitrary calls."""
    # Translate Stata operators only outside string literals.
    parts = re.split(r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')''', text)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r'!(?!=)', ' not ', parts[i].replace('^', '**'))
        parts[i] = parts[i].replace('&', ' and ').replace('|', ' or ')
    text = ''.join(parts)
    if len(text) > 2000:
        raise ValueError('La expresión es demasiado larga.')
    node = ast.parse(text.strip(), mode='eval')
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
           ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
           ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
    funcs = {'log': np.log, 'ln': np.log, 'sqrt': np.sqrt, 'abs': np.abs, 'exp': np.exp,
             'missing': pd.isna}
    def walk(n):
        if isinstance(n, ast.Expression): return walk(n.body)
        if isinstance(n, ast.Constant) and type(n.value) in (int, float, str, bool): return n.value
        if isinstance(n, ast.Name) and n.id in df: return df[n.id]
        if isinstance(n, ast.BinOp) and type(n.op) in ops:
            left, right = walk(n.left), walk(n.right)
            if isinstance(left, str) or isinstance(right, str):
                raise ValueError('Las operaciones aritméticas requieren números.')
            if isinstance(n.op, ast.Pow) and (np.asarray(right) > 100).any():
                raise ValueError('El exponente máximo es 100.')
            return ops[type(n.op)](left, right)
        if isinstance(n, ast.UnaryOp):
            val = walk(n.operand)
            if isinstance(n.op, ast.USub): return -val
            if isinstance(n.op, ast.UAdd): return +val
            if isinstance(n.op, (ast.Not, ast.Invert)): return ~val if isinstance(val, pd.Series) else not val
        if isinstance(n, ast.BoolOp):
            vals = [walk(v) for v in n.values]
            out = vals[0]
            for val in vals[1:]: out = (out & val) if isinstance(n.op, ast.And) else (out | val)
            return out
        if isinstance(n, ast.Compare):
            left, out = walk(n.left), True
            for op, nxt in zip(n.ops, n.comparators):
                right = walk(nxt)
                if type(op) not in ops: break
                compared = ops[type(op)](left, right)
                # Missing values never satisfy comparisons, including !=.
                compared = compared & pd.notna(left) & pd.notna(right)
                out = out & compared
                left = right
            else: return out
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in funcs and len(n.args) == 1 and not n.keywords:
            return funcs[n.func.id](walk(n.args[0]))
        raise ValueError('Expresión no admitida. Usa variables, operaciones y funciones de la ayuda.')
    with np.errstate(all='ignore'):
        result = walk(node)
    if isinstance(result, pd.Series): return result.replace([np.inf, -np.inf], np.nan)
    if isinstance(result, (float, np.floating)) and not np.isfinite(result): return np.nan
    return result


def split_unquoted(text, separator):
    """Split at a token outside quoted strings, preserving literal commas and ' if '."""
    quote, escaped = None, False
    for i, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == '\\' and quote:
            escaped = True
            continue
        if quote:
            if char == quote: quote = None
        elif char in ('"', "'"):
            quote = char
        elif text.startswith(separator, i):
            return text[:i], separator, text[i+len(separator):]
    return text, '', ''


class Workspace:
    def __init__(self):
        self.df = pd.DataFrame()
        self.name = 'Sin datos'
        self.history = []
        self.backups = []

    def save(self):
        self.backups.append((self.df.copy(deep=True), self.name))
        self.backups = self.backups[-20:]

    def load(self, df, name):
        if len(df) > 250000 or len(df.columns) > 500:
            raise ValueError('Límite: 250.000 filas y 500 variables por archivo.')
        self.save()
        self.df, self.name = normalize_columns(df.reset_index(drop=True).replace([np.inf, -np.inf], np.nan)), name

    def variables(self, names, numeric=False, minimum=1):
        if len(names) < minimum: raise ValueError(f'Selecciona al menos {minimum} variables.')
        if len(set(names)) != len(names): raise ValueError('No repitas variables.')
        for name in names:
            if name not in self.df: raise ValueError(f'No existe la variable «{name}».')
            if numeric and not pd.api.types.is_numeric_dtype(self.df[name]):
                raise ValueError(f'«{name}» debe ser numérica.')
        return names

    def run(self, command):
        command = command.strip()
        if not command: raise ValueError('Escribe un comando.')
        result = self.execute(command)
        self.history.append({'command': command, 'result': result})
        return result

    def execute(self, command):
        head, _, args = command.partition(' ')
        head = {'sum': 'summarize', 'summ': 'summarize', 'reg': 'regress', 'gen': 'generate',
                'tab': 'tabulate', 'corr': 'correlate', 'hist': 'histogram', 'desc': 'describe'}.get(head.lower(), head.lower())
        if head == 'help': return {'title': 'Referencia de comandos', 'table': table(pd.DataFrame(HELP.items(), columns=['Comando', 'Descripción']))}
        if head == 'undo':
            if not self.backups: raise ValueError('No hay cambios que deshacer.')
            self.df, self.name = self.backups.pop()
            return {'title': 'Cambio deshecho', 'message': 'Se ha restaurado la versión anterior de los datos.'}
        if not len(self.df.columns): raise ValueError('Importa un archivo o carga los datos de ejemplo.')
        # Accept both canonical Stata "... if condition, options" and the guided form.
        if head in ('regress', 'ttest'):
            spec, comma, options = split_unquoted(args, ',')
            if comma and ' if ' in spec:
                spec, _, cond = split_unquoted(spec, ' if ')
                args = spec + ', ' + options.strip() + ' if ' + cond
        base, sep, condition = split_unquoted(args, ' if ')
        if args.startswith('if '): base, sep, condition = '', ' if ', args[3:]
        mask = pd.Series(True, index=self.df.index)
        if sep:
            mask = expression(condition, self.df)
            if not isinstance(mask, pd.Series) or not pd.api.types.is_bool_dtype(mask):
                raise ValueError('La condición debe comparar variables, por ejemplo edad >= 30.')
            mask = mask.fillna(False)
        data = self.df.loc[mask]
        names = base.split()
        if head == 'describe':
            if args: raise ValueError('Usa describe sin argumentos.')
            return {'title': 'Diccionario de variables', 'table': table(pd.DataFrame([
                {'Variable': c, 'Tipo': str(self.df[c].dtype), 'Observaciones': int(self.df[c].count()), 'Ausentes': int(self.df[c].isna().sum())} for c in self.df]))}
        if head == 'count':
            if base: raise ValueError('Usa count o count if condición.')
            return {'title': 'Observaciones', 'message': f'{len(data):,} observaciones cumplen la selección.'}
        if head == 'list':
            names = self.variables(names or list(data.columns))
            return {'title': 'Listado de datos', 'table': table(data[names].head(200)), 'message': f'Mostrando hasta 200 de {len(data)} filas.'}
        if head == 'summarize':
            names = self.variables(names or list(data.select_dtypes(include='number').columns), numeric=True)
            out = data[names].describe().T.rename(columns={'count': 'N', 'mean': 'Media', 'std': 'Desv. est.', 'min': 'Mínimo', 'max': 'Máximo'})
            out.insert(0, 'Variable', out.index)
            return {'title': 'Estadísticos descriptivos', 'table': table(out), 'message': 'Cada variable excluye sus valores ausentes. Desviación estándar muestral (n − 1).'}
        if head == 'tabulate':
            self.variables(names)
            if len(names) != 1: raise ValueError('Usa tabulate variable.')
            counts = data[names[0]].astype(object).fillna('(ausente)').value_counts(dropna=False)
            out = pd.DataFrame({names[0]: counts.index, 'Frecuencia': counts.values, 'Porcentaje': counts.values / max(len(data), 1) * 100})
            return {'title': f'Frecuencias · {names[0]}', 'table': table(out)}
        if head == 'correlate':
            self.variables(names, numeric=True, minimum=2)
            complete = data[names].dropna()
            if len(complete) < 2: raise ValueError('Se necesitan al menos dos casos completos.')
            out = complete.corr(); out.insert(0, 'Variable', out.index)
            return {'title': 'Correlación de Pearson', 'table': table(out), 'message': f'{len(complete)} casos completos; {len(data)-len(complete)} excluidos.'}
        if head == 'regress':
            spec, comma, option = base.partition(',')
            if comma and option.strip() != 'robust': raise ValueError('La única opción admitida es , robust.')
            names = self.variables(spec.split(), numeric=True, minimum=2)
            complete = data[names].dropna().astype(float)
            x = sm.add_constant(complete[names[1:]], has_constant='add')
            if len(complete) <= x.shape[1]: raise ValueError('Faltan observaciones para estimar el modelo y su error.')
            if np.linalg.matrix_rank(x) < x.shape[1]: raise ValueError('Hay colinealidad perfecta o predictores constantes.')
            model = sm.OLS(complete[names[0]], x).fit(cov_type='HC1' if comma else 'nonrobust', use_t=True)
            ci = model.conf_int()
            out = pd.DataFrame({'Variable': model.params.index, 'Coeficiente': model.params.values, 'Error est.': model.bse.values,
                't': model.tvalues.values, 'p': model.pvalues.values, 'IC 95% inferior': ci[0].values, 'IC 95% superior': ci[1].values})
            return {'title': f'Regresión lineal · {names[0]}', 'table': table(out), 'metrics': {'N': int(model.nobs), 'R²': model.rsquared, 'R² ajustado': model.rsquared_adj},
                'message': f'Constante incluida. Errores {"robustos HC1" if comma else "convencionales"}. {len(data)-len(complete)} casos excluidos por valores ausentes.'}
        if head == 'ttest':
            match = re.fullmatch(r'(\w+)\s*,\s*by\((\w+)\)', base)
            if not match: raise ValueError('Usa ttest variable, by(grupo).')
            y, group = match.groups(); self.variables([y], numeric=True); self.variables([group])
            complete = data[[y, group]].dropna(); groups = list(complete.groupby(group, observed=True))
            if len(groups) != 2 or any(len(g) < 2 for _, g in groups): raise ValueError('Se requieren dos grupos con al menos dos casos cada uno.')
            a, b = groups[0][1][y], groups[1][1][y]
            test = stats.ttest_ind(a, b, equal_var=False)
            if not np.isfinite(test.statistic): raise ValueError('La prueba no está definida para estos grupos constantes.')
            return {'title': 'Prueba t de Welch', 'metrics': {'t': test.statistic, 'p bilateral': test.pvalue, 'Grados de libertad': test.df},
                    'table': table(pd.DataFrame([{'Grupo': str(key), 'N': len(g), 'Media': g[y].mean(), 'Desv. est.': g[y].std()} for key, g in groups]))}
        if head in ('histogram', 'scatter'):
            self.variables(names, numeric=True, minimum=1 if head == 'histogram' else 2)
            if len(names) != (1 if head == 'histogram' else 2): raise ValueError('Número de variables incorrecto.')
            complete = data[names].dropna()
            if complete.empty: raise ValueError('No hay valores válidos para representar.')
            if head == 'histogram':
                counts, edges = np.histogram(complete[names[0]], bins='auto')
                return {'title': f'Distribución · {names[0]}', 'chart': {'type': 'histogram', 'x': names[0], 'y': 'Frecuencia', 'points': [[float(edges[i]), float(edges[i+1]), int(v)] for i, v in enumerate(counts)]}}
            sampled = complete.sample(min(len(complete), 5000), random_state=42)
            return {'title': f'{names[0]} frente a {names[1]}', 'chart': {'type': 'scatter', 'x': names[1], 'y': names[0], 'points': sampled[[names[1], names[0]]].values.tolist()}, 'message': f'{len(sampled)} puntos de {len(complete)} casos completos.'}
        new = self.df.copy(deep=True)
        if head in ('generate', 'replace'):
            match = re.fullmatch(r'([A-Za-z_]\w*)\s*=\s*(.+)', base)
            if not match: raise ValueError('Usa generate nueva = expresión o replace variable = expresión.')
            name, formula = match.groups()
            if head == 'generate' and name in new: raise ValueError('La variable ya existe. Usa replace.')
            if head == 'replace': self.variables([name])
            values = expression(formula, self.df)
            is_text = isinstance(values, str) or (isinstance(values, pd.Series) and not pd.api.types.is_numeric_dtype(values))
            if name not in new: new[name] = pd.Series(None, index=new.index, dtype=object) if is_text else np.nan
            if is_text: new[name] = new[name].astype(object)
            elif pd.api.types.is_integer_dtype(new[name]): new[name] = new[name].astype(float)
            new.loc[mask, name] = values.loc[mask] if isinstance(values, pd.Series) else values
        elif head in ('keep', 'drop'):
            if sep:
                if base: raise ValueError('No combines lista de variables y condición.')
                new = new.loc[mask if head == 'keep' else ~mask].reset_index(drop=True)
            else:
                self.variables(names)
                new = new[names] if head == 'keep' else new.drop(columns=names)
                if not len(new.columns): raise ValueError('Debe quedar al menos una variable.')
        elif head == 'rename':
            if len(names) != 2: raise ValueError('Usa rename anterior nueva.')
            self.variables(names[:1])
            if names[1] in new or not re.fullmatch(r'[A-Za-z_]\w*', names[1]): raise ValueError('El nuevo nombre no es válido o ya existe.')
            new = new.rename(columns={names[0]: names[1]})
        elif head == 'sort':
            self.variables(names); new = new.sort_values(names, kind='stable').reset_index(drop=True)
        else: raise ValueError(f'Comando «{head}» no reconocido. Escribe help para ver los disponibles.')
        if head in ('sort', 'rename') and sep: raise ValueError('Este comando no admite if.')
        self.save(); self.df = new
        return {'title': 'Datos actualizados', 'message': f'{len(new):,} observaciones · {len(new.columns)} variables. Puedes deshacer este cambio.'}
