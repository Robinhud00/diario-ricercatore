# Ogni Diario ha la SUA cartella in Drive e non scrive mai in quella di un altro.
import os, sys, tempfile, json, importlib.util, shutil
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def load(tag, name, base):
    os.environ["HOME"] = tempfile.mkdtemp()
    spec = importlib.util.spec_from_file_location("dw_" + tag, os.path.join(here, "diario_web.py")); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m.open_path = lambda p: None; m.init_db()
    c = m.load_cfg(); c["owner_name"] = name
    if base: c["sync_dir"] = base
    m.save_cfg(c); return m
def tree(d): return sorted(os.path.relpath(os.path.join(a, f), d) for a, _, fs in os.walk(d) for f in fs)
def newexp(m, name):
    e = m.api_new({})["id"]; m.api_save({"id": e, "name": name, "date": "16/11/2026", "project": "", "obiettivo": "x", "procedura": "y", "risultati": "", "note": "", "lang": ""}); return e

# --- 1) IL CASO DI OGGI: nel Drive del supervisore c'e' la scorciatoia «Diario del Ricercatore» dello studente
#        (qui: la stessa cartella vista dai due computer) e il supervisore ha come cartella Drive «Il mio Drive».
drive_stud = tempfile.mkdtemp(prefix="drive-stud-"); drive_sup = tempfile.mkdtemp(prefix="drive-sup-")
stud = load("stud", "Federico Mascanzone", drive_stud)
newexp(stud, "Coupling FM"); stud.sync_to_drive()
sroot = stud.drive_root(); assert os.path.basename(sroot) == "Diario del Ricercatore - Federico Mascanzone"
os.symlink(sroot, os.path.join(drive_sup, "Diario del Ricercatore"))          # la scorciatoia, con il vecchio nome
before = {f: open(os.path.join(sroot, f), "rb").read() for f in tree(sroot)}
sup = load("sup", "Tiziano", drive_sup)
newexp(sup, "Nuovo esperimento"); sup.sync_to_drive()
myroot = sup.drive_root()
assert os.path.basename(myroot) == "Diario del Ricercatore - Tiziano" and os.path.realpath(myroot) != os.path.realpath(sroot), myroot
after = {f: open(os.path.join(sroot, f), "rb").read() for f in tree(sroot)}
assert before == after, "il Diario del supervisore ha toccato la cartella dello studente!"
S = json.load(open(os.path.join(sroot, "stato.json"), encoding="utf-8")); assert S["owner"] == "Federico Mascanzone" and S["experiments"][0]["name"] == "Coupling FM"
# il supervisore collega lo studente: sia scegliendo la scorciatoia sia «Il mio Drive» (dove c'e' anche la sua cartella)
r = sup.api_lab_add({"name": "Federico", "path": drive_sup}); assert r["found"]
v = sup.api_lab_get({}); assert v["members"][0]["owner"] == "Federico Mascanzone" and v["my_folder"] == "Diario del Ricercatore - Tiziano", v
try: sup.api_lab_add({"name": "io", "path": myroot}); raise SystemExit("deve rifiutare la propria cartella")
except RuntimeError as e: assert "TUA" in str(e)
try: sup.api_lab_add({"name": "doppio", "path": os.path.join(drive_sup, "Diario del Ricercatore")}); raise SystemExit("deve rifiutare il doppione")
except RuntimeError as e: assert "gia' collegata" in str(e)
# messaggi: finiscono nella cartella dello studente, in un file del supervisore, senza toccare il resto
sup.api_lab_send({"member": r["id"], "exp": None, "text": "ciao"}); stud.sync_to_drive(); sup.sync_to_drive()
assert stud.api_msg_status({})["total"] == 1
assert json.load(open(os.path.join(sroot, "stato.json"), encoding="utf-8"))["owner"] == "Federico Mascanzone"
assert not any("Nuovo esperimento" in f for f in tree(sroot)), tree(sroot)

# --- 2) chi aveva gia' la vecchia cartella «Diario del Ricercatore» (sua): viene rinominata sul posto, niente doppioni
d2 = tempfile.mkdtemp(prefix="drive-old-"); old = load("old", "Sara Conti", d2)
newexp(old, "Vecchio esperimento"); old.sync_to_drive()
cur = old.drive_root(); legacy = os.path.join(d2, "Diario del Ricercatore")
os.rename(cur, legacy); os.remove(os.path.join(legacy, old.OWNER_MARK)); old._root_cache.update({"root": None})   # come lasciata da una versione precedente
c = old.load_cfg(); c.pop("drive_folder", None); old.save_cfg(c)
old.sync_to_drive()
assert sorted(os.listdir(d2)) == ["Diario del Ricercatore - Sara Conti"], os.listdir(d2)
assert old._is_my_root(old.drive_root())

# --- 3) due supervisori per lo stesso studente e due studenti per lo stesso supervisore
sup2 = load("sup2", "Prof. Neri", None)
r2 = sup2.api_lab_add({"name": "Federico", "path": sroot}); sup2.api_lab_send({"member": r2["id"], "exp": None, "text": "da Neri"})
stud.msg_scan(); assert {m["author"] for m in stud.api_msg_thread({"exp": None})["messages"]} == {"Tiziano", "Prof. Neri"}
assert len([f for f in os.listdir(os.path.join(sroot, "Messaggi")) if f.startswith("supervisore-")]) == 2
r3 = sup.api_lab_add({"name": "Sara", "path": old.drive_root()}); assert r3["found"] and len(sup.api_lab_get({})["members"]) == 2
print("TEST CARTELLE SEPARATE OK")
