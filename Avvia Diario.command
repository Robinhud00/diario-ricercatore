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

MACOS="$(sw_vers -productVersion 2>/dev/null)"
MAC_MAJ="$(echo "$MACOS" | cut -d. -f1)"
MAC_MIN="$(echo "$MACOS" | cut -d. -f2)"

# Quale Python consigliare per questo Mac (gli installer di python.org recenti
# richiedono macOS 10.15 o successivo).
consiglio_python() {
  if [ "$MAC_MAJ" = "10" ] && [ -n "$MAC_MIN" ] && [ "$MAC_MIN" -lt 13 ] 2>/dev/null; then
    echo "3.12"
  elif [ "$MAC_MAJ" = "10" ] && [ -n "$MAC_MIN" ] && [ "$MAC_MIN" -lt 15 ] 2>/dev/null; then
    echo "3.13 oppure 3.12"
  else
    echo "3.12 o piu' recente"
  fi
}

python_troppo_nuovo() {
  # $1 = percorso del Python che si e' bloccato
  VER="$("$1" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)"
  if [ -z "$VER" ]; then
    VER="$(basename "$(dirname "$(dirname "$(readlink "$1" 2>/dev/null || echo "$1")")")")"
    case "$VER" in 3.*) ;; *) VER="$(basename "$1" | sed 's/^python//')";; esac
    case "$VER" in 3.*) ;; *) VER="";; esac
  fi
  echo ""
  echo "=================================================================="
  echo "⚠️  CAMBIA LA VERSIONE DI PYTHON"
  echo ""
  echo "Il Python installato su questo Mac ($1, versione ${VER:-?})"
  echo "e' troppo NUOVO per questo macOS (${MACOS:-sconosciuto}) e si blocca subito."
  echo "Il Diario non c'entra: va solo installato un Python piu' vecchio."
  echo ""
  echo "Cosa fare:"
  echo "  1. Vai su  https://www.python.org/downloads/macos/"
  echo "  2. Scarica il «macOS 64-bit universal2 installer» di Python $(consiglio_python)"
  echo "     (sotto ogni installer c'e' scritto «for macOS 10.x and later»:"
  echo "      scegli quello compatibile con il tuo macOS ${MACOS})"
  echo "  3. Installalo e rifai doppio clic su «Avvia Diario»."
  echo ""
  echo "Consigliato: cestina la versione troppo nuova (Applicazioni → «Python ${VER:-3.x}»"
  echo "e /Library/Frameworks/Python.framework/Versions/${VER:-3.x})."
  echo "=================================================================="
}

# Un Python va bene se parte davvero, e' almeno 3.9 e ha sqlite3/ssl.
python_ok() {
  { ( "$1" -c 'import sys, sqlite3, ssl, json, threading; sys.exit(0 if sys.version_info >= (3, 9) else 3)' ) >/dev/null 2>&1; } 2>/dev/null
}

# Provo tutte le versioni installate, dalla piu' nuova alla piu' vecchia.
CANDIDATI=""
for v in "" 3.14 3.13 3.12 3.11 3.10 3.9; do
  p="$(command -v "python$v" 2>/dev/null)"
  [ -z "$v" ] && p="$(command -v python3 2>/dev/null)"
  [ -n "$p" ] && CANDIDATI="$CANDIDATI
$p"
done
for p in /Library/Frameworks/Python.framework/Versions/*/bin/python3 \
         /usr/local/bin/python3 /opt/homebrew/bin/python3 /opt/local/bin/python3; do
  [ -x "$p" ] && CANDIDATI="$CANDIDATI
$p"
done

PY=""
ROTTO=""
while IFS= read -r c; do
  [ -z "$c" ] && continue
  python_ok "$c"
  rc=$?
  if [ $rc -eq 0 ]; then PY="$c"; break; fi
  # Codice >= 128 = il Python si e' bloccato (es. «Abort trap: 6» / dyld):
  # tipicamente e' una versione costruita per un macOS piu' recente.
  [ $rc -ge 128 ] && [ -z "$ROTTO" ] && ROTTO="$c"
done <<< "$(echo "$CANDIDATI" | awk 'NF && !seen[$0]++')"

# Ultima spiaggia: il Python di Apple (sui Mac vecchi puo' chiedere di
# installare gli strumenti per sviluppatori).
if [ -z "$PY" ] && [ -x /usr/bin/python3 ] && xcode-select -p >/dev/null 2>&1; then
  python_ok /usr/bin/python3 && PY=/usr/bin/python3
fi

if [ -z "$PY" ]; then
  if [ -n "$ROTTO" ]; then
    python_troppo_nuovo "$ROTTO"
    problema "Python da cambiare (vedi sopra)."
  fi
  echo "Il Mac sta chiedendo di installare gli strumenti per sviluppatori (contengono Python)."
  echo "Nella finestra che compare premi «Installa», aspetta la fine, poi rifai doppio clic su «Avvia Diario»."
  xcode-select --install >/dev/null 2>&1
  problema "Python non e' ancora installato. In alternativa scaricalo da https://www.python.org/downloads/macos/ (per questo Mac: Python $(consiglio_python))"
fi
[ -f diario_web.py ] || problema "Non trovo diario_web.py: deve stare nella stessa cartella di questo file."

"$PY" diario_web.py
rc=$?
if [ $rc -eq 0 ]; then
  # Il Diario gira in background: chiudo questa finestra del Terminale da solo.
  (sleep 2; osascript -e 'tell application "Terminal" to close (every window whose name contains "Avvia Diario")' >/dev/null 2>&1) &
  exit 0
fi
if [ $rc -ge 128 ]; then
  # Python si e' bloccato a meta' (es. «Symbol not found: ____chkstk_darwin»).
  python_troppo_nuovo "$PY"
  problema "Python da cambiare (vedi sopra)."
fi
problema "Il Diario non e' partito (vedi sopra). Copia il testo e mandalo a chi ti ha dato il Diario."
