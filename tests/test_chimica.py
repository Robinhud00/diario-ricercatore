"""Strutture ChemDraw/MOL -> SMILES, ruoli dalla freccia, ricerca della reazione (PubChem simulato)."""
import os, sys, tempfile, json, re, struct
home = tempfile.mkdtemp(); os.environ["HOME"] = home
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import importlib.util
spec = importlib.util.spec_from_file_location("dw", os.path.join(here, "diario_web.py")); dw = importlib.util.module_from_spec(spec); spec.loader.exec_module(dw)
dw.open_path = lambda p: None
dw.init_db()


# --- mini lettore di SMILES per controllare che quelli generati siano validi e corretti
def read_smiles(smi):
    atoms, bonds, i, prev, stack, rings, bond = [], [], 0, None, [], {}, 1
    while i < len(smi):
        c = smi[i]
        if c == "(":
            stack.append(prev); i += 1; continue
        if c == ")":
            prev = stack.pop(); i += 1; continue
        if c in "-=#:":
            bond = {"-": 1, "=": 2, "#": 3, ":": 1.5}[c]; i += 1; continue
        if c.isdigit() or c == "%":
            if c == "%":
                d = smi[i + 1:i + 3]; i += 3
            else:
                d = c; i += 1
            if d in rings:
                a, b0 = rings.pop(d); bonds.append((a, prev, max(bond, b0) if bond != 1 or b0 != 1 else 1)); bond = 1
            else:
                rings[d] = (prev, bond); bond = 1
            continue
        if c == "[":
            j = smi.index("]", i); body = smi[i + 1:j]; i = j + 1
            m = re.match(r"(\d*)([A-Za-z][a-z]?|\*)(H\d*)?([+-]\d*)?", body)
            el = m.group(2); h = m.group(3); h = (int(h[1:] or 1) if h else 0)
            atoms.append({"el": el[0].upper() + el[1:], "arom": el[0].islower(), "h": h, "br": True})
        else:
            m = re.match(r"Cl|Br|[BCNOPSFI]|[bcnops]|\*", smi[i:])
            assert m, "SMILES non valido: " + smi[i:]
            el = m.group(0); i += len(el)
            atoms.append({"el": el[0].upper() + el[1:], "arom": el[0].islower(), "h": None, "br": False})
        cur = len(atoms) - 1
        if prev is not None:
            bonds.append((prev, cur, bond))
        bond, prev = 1, cur
    assert not rings, "anelli non chiusi in " + smi
    return atoms, bonds


def formula_of(smi):
    atoms, bonds = read_smiles(smi)
    cnt = {}
    deg = [0] * len(atoms)
    for a, b, o in bonds:
        deg[a] += o; deg[b] += o
    for k, at in enumerate(atoms):
        cnt[at["el"]] = cnt.get(at["el"], 0) + 1
        hh = at["h"] if at["br"] else max(0, {"C": 4, "N": 3, "O": 2, "S": 2, "F": 1, "Cl": 1, "Br": 1, "I": 1, "B": 3, "P": 3}.get(at["el"], 0) - int(round(deg[k] + (0.5 if at["arom"] else 0))))
        if hh:
            cnt["H"] = cnt.get("H", 0) + hh
    keys = ["C", "H"] + sorted(k for k in cnt if k not in ("C", "H"))
    return "".join(k + (str(cnt[k]) if cnt[k] > 1 else "") for k in keys if k in cnt)


# 1) CDXML: acido benzoico + metanolo -> benzoato di metile (con freccia, senza «step») e un'abbreviazione OMe espansa
def ring(x0, y0, start_id):
    ids = list(range(start_id, start_id + 6)); pts = [(x0 + 10, y0), (x0 + 20, y0 + 6), (x0 + 20, y0 + 18), (x0 + 10, y0 + 24), (x0, y0 + 18), (x0, y0 + 6)]
    ns = "".join('<n id="%d" p="%.1f %.1f"/>' % (i, p[0], p[1]) for i, p in zip(ids, pts))
    bs = "".join('<b id="%d" B="%d" E="%d"%s/>' % (500 + start_id + k, ids[k], ids[(k + 1) % 6], ' Order="2"' if k % 2 == 0 else "") for k in range(6))
    return ids, ns, bs

r1, n1, b1 = ring(0, 0, 1)
acid = ('<fragment id="100">' + n1 + '<n id="7" p="10 -12"/><n id="8" p="0 -18" Element="8"/><n id="9" p="20 -18" Element="8" NumHydrogens="1"/>'
        + b1 + '<b id="20" B="1" E="7"/><b id="21" B="7" E="8" Order="2"/><b id="22" B="7" E="9"/></fragment>')
meoh = '<fragment id="200"><n id="30" p="60 0"/><n id="31" p="70 0" Element="8"/><b id="32" B="30" E="31"/></fragment>'
r2, n2, b2 = ring(150, 0, 40)
ester = ('<fragment id="300">' + n2 + '<n id="47" p="160 -12"/><n id="48" p="150 -18" Element="8"/>'
         '<n id="49" p="170 -18" NodeType="Nickname"><fragment id="400"><n id="50" p="170 -18" Element="8"/><n id="51" p="180 -18"/>'
         '<n id="52" p="165 -18" NodeType="ExternalConnectionPoint"/><b id="53" B="52" E="50"/><b id="54" B="50" E="51"/></fragment><t><s>OMe</s></t></n>'
         + b2 + '<b id="60" B="40" E="47"/><b id="61" B="47" E="48" Order="2"/><b id="62" B="47" E="49"/></fragment>')
cdxml = ('<?xml version="1.0" encoding="UTF-8" ?><!DOCTYPE CDXML SYSTEM "http://www.cambridgesoft.com/xml/cdxml.dtd" >'
         '<CDXML><page id="1000">' + acid + meoh + ester +
         '<graphic id="900" BoundingBox="135 10 95 10" GraphicType="Line" ArrowType="FullHead"/></page></CDXML>')
mols = dw.structures_from_file("schema.cdxml", cdxml.encode())
print(mols)
assert len(mols) == 3, mols
byf = {m["formula"]: m for m in mols}
assert set(byf) == {"C7H6O2", "CH4O", "C8H8O2"}, byf.keys()
assert byf["C7H6O2"]["role"] == "reactant" and byf["CH4O"]["role"] == "reactant" and byf["C8H8O2"]["role"] == "product"
for m in mols:
    assert formula_of(m["smiles"]) == m["formula"], (m, formula_of(m["smiles"]))
    assert not m["problem"]

# con lo schema di reazione di ChemDraw (step) il metanolo sopra la freccia e' un reagente
cdxml2 = cdxml.replace("</page>", '<scheme id="950"><step id="951" ReactionStepReactants="100" ReactionStepProducts="300" ReactionStepObjectsAboveArrow="200"/></scheme></page>')
roles = {m["formula"]: m["role"] for m in dw.structures_from_file("schema.cdxml", cdxml2.encode())}
assert roles == {"C7H6O2": "reactant", "CH4O": "reagent", "C8H8O2": "product"}, roles

# abbreviazione non espansa -> segnalata
bad = '<CDXML><page><fragment id="1"><n id="2" p="0 0"/><n id="3" p="10 0" NodeType="GenericNickname"/><b B="2" E="3"/></fragment></page></CDXML>'
mb = dw.structures_from_file("x.cdxml", bad.encode())
assert len(mb) == 1 and mb[0]["problem"], mb

# 2) CDX binario costruito a mano: etanolo
def prop(tag, data): return struct.pack("<HH", tag, len(data)) + data
def obj(tag, oid, *body): return struct.pack("<HI", tag, oid) + b"".join(body) + b"\0\0"
def node(oid, x, y, el=None, h=None):
    b = prop(0x0200, struct.pack("<ii", int(y * 65536), int(x * 65536)))
    if el: b += prop(0x0402, struct.pack("<H", el))
    if h is not None: b += prop(0x042B, struct.pack("<H", h))
    return obj(0x8004, oid, b)
def bond(oid, a, b_, order=1):
    return obj(0x8005, oid, prop(0x0604, struct.pack("<I", a)), prop(0x0605, struct.pack("<I", b_)), prop(0x0600, struct.pack("<H", order)))
cdx = (b"VjCD0100" + b"\x04\x03\x02\x01" + b"\0" * 16 +
       obj(0x8000, 1, obj(0x8001, 2, obj(0x8003, 3, node(10, 0, 0), node(11, 10, 0), node(12, 20, 0, 8), bond(20, 10, 11), bond(21, 11, 12)),
                          obj(0x8003, 4, node(30, 60, 0), node(31, 70, 0), node(32, 80, 0), bond(40, 30, 31, 4), bond(41, 31, 32)))))
mc = dw.structures_from_file("clip.cdx", cdx)
print(mc)
fs = sorted(m["formula"] for m in mc)
assert fs == ["C2H6O", "C3H4"], fs
for m in mc:
    assert formula_of(m["smiles"]) == m["formula"]

# 3) MOL V2000 (come quelli del «Disegna molecola»): cicloesanone e ione ammonio
mol = """
  JSME

  7  7  0  0  0  0  0  0  0  0999 V2000
    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    1.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    1.5000    0.8000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    1.0000    1.6000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    0.0000    1.6000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
   -0.5000    0.8000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
   -1.5000    0.8000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0  0  0  0
  2  3  1  0  0  0  0
  3  4  1  0  0  0  0
  4  5  1  0  0  0  0
  5  6  1  0  0  0  0
  6  1  1  0  0  0  0
  6  7  2  0  0  0  0
M  END
$$$$

  JSME

  1  0  0  0  0  0  0  0  0  0999 V2000
    0.0000    0.0000    0.0000 N   0  0  0  0  0  0  0  0  0  0  0  0
M  CHG  1   1   1
M  END
$$$$
"""
mm = dw.structures_from_file("molecola.sdf", mol.encode())
print(mm)
assert [m["formula"] for m in mm] == ["C6H10O", "H4N"] and mm[1]["smiles"] == "[NH4+]", mm
assert formula_of(mm[0]["smiles"]) == "C6H10O"

# 4) ricerca: PubChem e PubMed simulati
calls = []
def fake_http(url, form=None, timeout=45, who="PubChem"):
    calls.append((url, form))
    if "/compound/name/property" in url:
        nm = form["name"].lower()
        db_ = {"acido benzoico": None, "benzoic acid": (243, "benzoic acid", "C7H6O2", "WPYMKLBDIGXBTP-UHFFFAOYSA-N"),
               "methanol": (887, "methanol", "CH4O", "OKKJLVBELUTLKV-UHFFFAOYSA-N"), "methyl benzoate": (7150, "methyl benzoate", "C8H8O2", "QPJVMBTYPHYUOC-UHFFFAOYSA-N")}
        v = db_.get(nm)
        if not v:
            return 404, json.dumps({"Fault": {"Code": "PUGREST.NotFound"}})
        return 200, json.dumps({"PropertyTable": {"Properties": [{"CID": v[0], "IUPACName": v[1], "MolecularFormula": v[2], "InChIKey": v[3], "SMILES": "C", "Title": v[1].title()}]}})
    if "/compound/smiles/property" in url:
        if form["smiles"] == "C(":
            return 400, json.dumps({"Fault": {"Code": "PUGREST.BadRequest"}})
        return 200, json.dumps({"PropertyTable": {"Properties": [{"CID": 0}]}})
    if "fastsimilarity_2d" in url:
        return 200, json.dumps({"PropertyTable": {"Properties": [{"CID": 7150, "IUPACName": "methyl benzoate", "Title": "Methyl benzoate"}]}})
    m = re.search(r"/cid/(\d+)/xrefs/(\w+)/", url)
    if m:
        cid, kind = int(m.group(1)), m.group(2)
        data = {(243, "PubMedID"): [1, 2, 3, 9], (887, "PubMedID"): [2, 3, 4], (7150, "PubMedID"): [3, 5, 2],
                (243, "PatentID"): ["US-1-A1"], (887, "PatentID"): ["US-1-A1"], (7150, "PatentID"): ["US-1-A1", "EP-2-B1"]}
        return 200, json.dumps({"InformationList": {"Information": [{"CID": cid, kind: data.get((cid, kind), [])}]}})
    if "esummary" in url:
        return 200, json.dumps({"result": {"3": {"title": "Fischer esterification revisited", "source": "J Org Chem", "pubdate": "2019 May", "authors": [{"name": "Rossi A"}]},
                                           "2": {"title": "Methanol and benzoic acid", "source": "Org Lett", "pubdate": "2015", "authors": []}}})
    raise AssertionError("url inattesa " + url)
dw.http_get = fake_http
r = dw.api_chem_identify({"name": "benzoic acid"}); assert r["found"] and r["cid"] == 243 and r["iupac"] == "benzoic acid", r
r = dw.api_chem_identify({"name": "acido benzoico"}); assert not r["found"], r
r = dw.api_chem_identify({"smiles": "COC(=O)c1ccccc1CCl"}); assert r.get("novel"), r
r = dw.api_chem_identify({"smiles": "C("}); assert r.get("invalid"), r
n_calls = len(calls); dw.api_chem_identify({"name": "benzoic acid"}); assert len(calls) == n_calls, "cache non usata"

e1 = dw.api_new({})["id"]; e2 = dw.api_new({})["id"]
dw.api_save({"id": e1, "name": "Esterificazione di Fischer", "date": "", "project": "", "obiettivo": "", "procedura": "Acido benzoico in metanolo con H2SO4.", "risultati": "", "note": "", "lang": ""})
items = [{"name": "benzoic acid", "role": "Reagente", "cid": 243, "inchikey": "WPYMKLBDIGXBTP-UHFFFAOYSA-N", "title": "Benzoic Acid"},
         {"name": "methanol", "role": "Reagente", "cid": 887, "inchikey": "OKKJLVBELUTLKV-UHFFFAOYSA-N", "title": "Methanol"},
         {"name": "methyl benzoate", "role": "Prodotto", "cid": 7150, "inchikey": "QPJVMBTYPHYUOC-UHFFFAOYSA-N", "title": "Methyl Benzoate"}]
res = dw.api_chem_search({"id": e1, "items": items})
print(json.dumps(res, indent=1)[:1500])
assert [a["pmid"] for a in res["articles"]][:2] == ["3", "2"] and res["articles"][0]["match"] and res["articles"][0]["n"] == 3
assert res["articles"][0]["title"].startswith("Fischer")
assert res["patents"][0]["id"] == "US-1-A1" and res["patents"][0]["match"] and res["patents"][0]["url"].endswith("/US1A1/")
# il secondo esperimento con le stesse sostanze trova il primo nel Diario
res2 = dw.api_chem_search({"id": e2, "items": items, "local_only": True})
assert res2["local"] and res2["local"][0]["id"] == e1 and res2["local"][0]["same"], res2["local"]
# prodotto nuovo (non in PubChem): si usano le molecole simili
items_new = items[:2] + [{"name": "", "smiles": "COC(=O)c1ccccc1CCl", "role": "Prodotto"}]
res3 = dw.api_chem_search({"id": e2, "items": items_new})
assert res3["similar_used"] and res3["articles"] and res3["articles"][0].get("similar") and not res3["articles"][0]["match"], res3
# rilevamento delle sostanze dall'esperimento: tabella reagenti + file ChemDraw allegato
dw.api_ds_save({"exp": e2, "title": "Reagenti", "kind": "reag", "payload": {"state": {"rows": [{"role": "Reagente", "name": "Benzoic acid"}, {"role": "Solvente", "name": "MeOH"}]}}})
dw.add_attachment(e2, "schema.cdxml", cdxml.encode())
det = dw.api_chem_detect({"id": e2})
print(det)
srcs = [i["src"] for i in det["items"]]
assert any("Reagenti" in x for x in srcs) and sum(1 for x in srcs if x == "schema.cdxml") == 3, srcs
# immagine letta dall'AI (risposta simulata)
dw.get_api_key = lambda: "sk-test"
sent = {}
def fake_curl(url, headers, body=None, timeout=150, who=""):
    sent["body"] = body
    return {"content": [{"type": "text", "text": 'Ecco: {"molecules": [{"smiles": "OC(=O)c1ccccc1", "role": "reactant", "label": "1"}, {"smiles": "COC(=O)c1ccccc1", "role": "product"}]}'}]}
dw.curl_json = fake_curl
ri = dw.api_chem_image({"image": "aGVsbG8=", "mime": "image/jpeg", "engine": "claude"})
assert [x["role"] for x in ri["items"]] == ["Reagente", "Prodotto"] and sent["body"]["messages"][0]["content"][0]["type"] == "image", ri
print("TEST CHIMICA OK")
