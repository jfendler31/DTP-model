"""Write cached results into the Betting Sheet's header-row array formulas.

Google Sheets' xlsx import shows the cached value of every cell an array formula fills instead of recalculating it on
import, so an array saved by openpyxl (formula only, no cached values) imports blank. This mirrors Google's own export:
the anchor cell carries its header as a string result and each filled cell carries its computed value.

Columns (Betting Sheet tab): B away, C home, F market home spread, G raw model home spread, H size-adjusted model
(array), I edge (array), J adjustment, L size-curve flag (1 = applies), E label (array). Size curve: SIZE_K pts per point of model spread beyond SIZE_KNEE.
"""
import re, shutil, tempfile, zipfile, posixpath
from xml.sax.saxutils import escape
import openpyxl


def _vals(ws, size_k, size_knee):
    out = {}
    num = lambda v: v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    for r in range(2, ws.max_row + 1):
        b, c, f, g, j, sc = (ws[f'{x}{r}'].value for x in 'BCFGJL')
        if not b and g is None: continue
        f, g, j = num(f), num(g), num(j) or 0.0
        h = '' if g is None else round(g + (1 if g > 0 else -1 if g < 0 else 0) * size_k * max(abs(g) - size_knee, 0) * (1 if sc == 1 else 0), 1)
        if f is None or h == '':
            e = i = ''
        else:
            d = f - (h + j)
            i = round(abs(d), 1)
            e = '-' if abs(d) < 0.05 else f"{c if d > 0 else b} {abs(d):.1f}"
        out[r] = {'E': e, 'H': h, 'I': i}
    return out


def _cell_xml(ref, style, v):
    s = f' s="{style}"' if style else ''
    if isinstance(v, str):
        return f'<c r="{ref}"{s} t="inlineStr"><is><t>{escape(v)}</t></is></c>'
    return f'<c r="{ref}"{s}><v>{v}</v></c>'


def cache_betting_sheet(path, sheet_name, size_k=0.2, size_knee=10):
    wb = openpyxl.load_workbook(path)
    ws = wb[sheet_name]
    headers = {c: ws[f'{c}1'].value for c in 'EHI'}
    heads = {c: (headers[c].text if hasattr(headers[c], 'text') else str(headers[c])) for c in 'EHI'}
    heads = {c: re.search(r'\{"([^"]*)"', t).group(1) for c, t in heads.items()}
    vals = _vals(ws, size_k, size_knee)
    # locate the sheet's XML part
    z = zipfile.ZipFile(path)
    wbx = z.read('xl/workbook.xml').decode()
    rid = re.search(rf'<sheet [^>]*name="{re.escape(escape(sheet_name, {chr(34): "&quot;"}))}"[^>]*r:id="([^"]+)"', wbx).group(1)
    rels = z.read('xl/_rels/workbook.xml.rels').decode()
    target = re.search(rf'<Relationship [^>]*Id="{rid}"[^>]*Target="([^"]+)"', rels) or \
             re.search(rf'<Relationship [^>]*Target="([^"]+)"[^>]*Id="{rid}"', rels)
    part = posixpath.normpath(posixpath.join('xl', target.group(1).lstrip('/').replace('xl/', '', 1)))
    xml = z.read(part).decode()
    # anchors: string result = header text. Tolerant of both serializers (lxml writes <v></v>, the pure-Python writer
    # GitHub's runner uses writes <v />) and of a t= attribute anywhere in the open tag.
    for c in 'EHI':
        m = re.search(rf'<c r="{c}1"(?P<attrs>[^>]*)>(?P<f>\s*<f t="array"[^>]*>.*?</f>)\s*(?:<v>.*?</v>|<v\s*/>)?\s*</c>', xml, flags=re.S)
        assert m, f'anchor {c}1 not found'
        attrs = re.sub(r'\s+t="[^"]*"', '', m.group('attrs'))
        xml = xml[:m.start()] + f'<c r="{c}1"{attrs} t="str">{m.group("f")}<v>{escape(heads[c])}</v></c>' + xml[m.end():]
    # filled cells
    for r, row in vals.items():
        for c in 'EHI':
            ref = f'{c}{r}'
            m = re.search(rf'<c r="{ref}"(?P<attrs>[^>]*?)(?:/>|>.*?</c>)', xml, flags=re.S)
            if m:
                st_ = re.search(r's="(\d+)"', m.group('attrs'))
                xml = xml[:m.start()] + _cell_xml(ref, st_.group(1) if st_ else None, row[c]) + xml[m.end():]
            else:   # cell element missing: insert it in column order within its row
                rm = re.search(rf'<row r="{r}"[^>]*>(.*?)</row>', xml, flags=re.S)
                if not rm: continue
                cells = rm.group(1); new = _cell_xml(ref, None, row[c])
                col = ord(c)
                pos = None
                for cm in re.finditer(r'<c r="([A-Z]+)\d+"', cells):
                    if ord(cm.group(1)[0]) > col and len(cm.group(1)) == 1: pos = cm.start(); break
                cells = cells[:pos] + new + cells[pos:] if pos is not None else cells + new
                xml = xml[:rm.start(1)] + cells + xml[rm.end(1):]
    tmp = tempfile.mktemp(suffix='.xlsx')
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = xml.encode() if item.filename == part else zin.read(item.filename)
            zout.writestr(item, data)
    shutil.move(tmp, path)
    return len(vals)
