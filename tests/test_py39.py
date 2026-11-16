# Il Python 3.9 dei Mac sbaglia ("Non-UTF-8 code") sulle righe lunghe con caratteri accentati se manca la riga "coding".
import os
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
raw = open(os.path.join(here, "diario_web.py"), "rb").read()
lines = raw.split(b"\n")
assert b"coding: utf-8" in lines[1], "manca la riga # -*- coding: utf-8 -*- in seconda riga"
raw.decode("utf-8")
longest = max(len(l) for l in lines)
assert longest < 20000, "riga troppo lunga: %d byte" % longest
print("TEST PYTHON 3.9 OK (riga piu' lunga: %d byte)" % longest)
