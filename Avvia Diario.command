#!/bin/bash
# Doppio clic per avviare il Diario del Ricercatore (si apre nel browser).
# Non serve installare nulla: usa il Python 3 che hai già.
cd "$(dirname "$0")"

fine() {
  echo ""
  echo "⚠️  $1"
  echo ""
  echo "Copia tutto il testo di questa finestra e mandalo a Claude."
  read -n 1 -s -r -p "Premi un tasto per chiudere…"
  exit 1
}

PY="$(command -v python3)" || fine "Python 3 non trovato. Installalo da https://www.python.org/downloads/macos/ e riprova."
[ -f diario_web.py ] || fine "Non trovo diario_web.py: deve stare nella stessa cartella di questo file."

echo "Avvio del Diario con $("$PY" --version)…"
"$PY" diario_web.py
fine "Il Diario si è fermato (vedi sopra)."
