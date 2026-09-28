"""Fast, low-memory row reader for large .xlsx files (standard library only).

openpyxl is too slow for the item-performance workbooks (hundreds of MB of outlet x SKU
rows), so this streams the first worksheet's XML with iterparse and yields plain lists.
"""
import re
import zipfile
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_COL = re.compile(r"([A-Z]+)")


def _col_index(ref):
    m = _COL.match(ref or "")
    n = 0
    for ch in (m.group(1) if m else "A"):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _shared_strings(zf):
    try:
        data = zf.open("xl/sharedStrings.xml")
    except KeyError:
        return []
    out = []
    for _, el in ET.iterparse(data):
        if el.tag == NS + "si":
            out.append("".join(t.text or "" for t in el.iter(NS + "t")))
            el.clear()
    return out


def _sheets(zf):
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels}
    out = []
    for s in wb.iter(NS + "sheet"):
        t = target.get(s.get(RNS + "id"), "")
        t = t.lstrip("/")
        out.append((s.get("name"), t if t.startswith("xl/") else "xl/" + t))
    return out


def rows(path, sheet_index=0):
    """Yield each row of a worksheet as a list of values (str or float)."""
    with zipfile.ZipFile(path) as zf:
        strings = _shared_strings(zf)
        sheets = _sheets(zf)
        if not sheets:
            return
        with zf.open(sheets[min(sheet_index, len(sheets) - 1)][1]) as fh:
            for _, el in ET.iterparse(fh):
                if el.tag != NS + "row":
                    continue
                vals = []
                for c in el.iter(NS + "c"):
                    i = _col_index(c.get("r"))
                    while len(vals) < i:
                        vals.append(None)
                    t = c.get("t")
                    v = c.find(NS + "v")
                    if t == "s" and v is not None:
                        x = strings[int(v.text)]
                    elif t == "inlineStr":
                        x = "".join(tt.text or "" for tt in c.iter(NS + "t"))
                    elif v is None or v.text is None:
                        x = None
                    elif t in ("str", "e"):
                        x = v.text
                    else:
                        try:
                            x = float(v.text)
                        except ValueError:
                            x = v.text
                    vals.append(x)
                el.clear()
                yield vals
