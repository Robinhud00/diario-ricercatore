# Le impostazioni non si perdono quando piu' parti del Diario le salvano insieme.
import os, sys, tempfile, threading, importlib.util, json
os.environ["HOME"] = tempfile.mkdtemp()
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("dw", os.path.join(here, "diario_web.py")); dw = importlib.util.module_from_spec(spec); spec.loader.exec_module(dw)
dw.init_db()
c = dw.load_cfg(); c["claude_key"] = "sk-ant-segreta"; c["sync_dir"] = "/drive"; dw.save_cfg(c)
errs = []
def worker(i):
    try:
        for n in range(60):
            c = dw.load_cfg(); c["k%d" % i] = n; dw.save_cfg(c)
            dw.install_id(); dw.diary_id()
            assert dw.load_cfg().get("claude_key") == "sk-ant-segreta"
    except Exception as ex:
        errs.append(repr(ex))
ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
[t.start() for t in ts]; [t.join() for t in ts]
final = json.load(open(dw.CFG_PATH, encoding="utf-8"))
assert not errs, errs[:3]
assert final["claude_key"] == "sk-ant-segreta" and final["sync_dir"] == "/drive", final
assert all(final["k%d" % i] == 59 for i in range(8)), final
c = dw.load_cfg(); c.pop("sync_dir"); dw.save_cfg(c); assert "sync_dir" not in dw.load_cfg() and dw.load_cfg()["claude_key"]
print("TEST IMPOSTAZIONI OK")
