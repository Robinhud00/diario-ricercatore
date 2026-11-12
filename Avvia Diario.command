#!/bin/bash
# Doppio clic per avviare il Diario del Ricercatore. Si apre nel browser.
cd "$(dirname "$0")"

problema() {
  echo ""
  echo "⚠️  $1"
  echo ""
  read -n 1 -s -r -p "Premi un tasto per chiudere…"
  exit 1
}

PY="$(command -v python3)"
if [ -z "$PY" ] || ! "$PY" --version >/dev/null 2>&1; then
  echo "Il Mac sta chiedendo di installare gli strumenti per sviluppatori (contengono Python)."
  echo "Nella finestra che compare premi «Installa», aspetta la fine, poi rifai doppio clic su «Avvia Diario»."
  xcode-select --install >/dev/null 2>&1
  problema "Python non e' ancora installato. In alternativa scaricalo da https://www.python.org/downloads/macos/"
fi
[ -f diario_web.py ] || problema "Non trovo diario_web.py: deve stare nella stessa cartella di questo file."

if "$PY" diario_web.py; then
  # Il Diario gira in background: chiudo questa finestra del Terminale da solo.
  (sleep 2; osascript -e 'tell application "Terminal" to close (every window whose name contains "Avvia Diario")' >/dev/null 2>&1) &
  exit 0
fi
problema "Il Diario non e' partito (vedi sopra). Copia il testo e mandalo a chi ti ha dato il Diario."
