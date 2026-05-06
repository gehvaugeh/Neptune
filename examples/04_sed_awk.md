# Neptune Guide: Text-Processing mit sed & awk

Dieses Notebook demonstriert die Mächtigkeit von Stream-Editoren (`sed`) und Pattern-Scanning-Languages (`awk`). Dank Neptune bleibt unser Arbeitsverzeichnis und unsere Variablen über alle Schritte hinweg erhalten.

---

## 1. Setup: Testdaten generieren
Wir erstellen eine CSV-ähnliche Logdatei, mit der wir arbeiten können. Sie enthält User-IDs, Namen, Rollen und Login-Zeiten.
```bash
# Erstelle eine Beispieldatenbank
cat << EOF > users.db
101:admin:root:2026-05-01
102:jules:developer:2026-05-03
103:gemmi:ai_copilot:2026-05-04
104:guest:visitor:2026-04-20
105:proteus:architect:2026-05-04
EOF
echo "Testdaten in users.db geschrieben."
```

---

## 2. sed: Suchen und Ersetzen (RegExp)
`sed` ist perfekt für Zeilen-basierte Transformationen. Wir nutzen Regex, um das Datumsformat zu ändern und Rollen-Namen zu maskieren.
```bash
# Ersetze 'developer' durch 'engineer' und ändere das Trennzeichen : zu |
# Syntax: s/pattern/replacement/g
sed 's/developer/engineer/g; s/:/ | /g' users.db
```

---

## 3. sed: Fortgeschrittene Filterung
Wir löschen Zeilen, die nicht dem aktuellen Monat (Mai) entsprechen, und nutzen Gruppen-Referenzierung (`\1`), um nur die Namen zu extrahieren.
```bash
# Lösche Zeilen mit April (04) und extrahiere den Namen (zweites Feld)
# Wir nutzen -E für Extended Regex
cat users.db | sed -E '/-04$/d; s/^[0-9]+:([^:]+):.*/User: \1/'
```

---

## 4. awk: Spaltenbasierte Analyse
Während `sed` zeilenorientiert ist, denkt `awk` in Feldern. Hier berechnen wir Statistiken oder filtern nach Logik.

```bash
# Setze Feldtrenner auf ':' (-F) und drucke Name (2) und Rolle (3)
# Aber nur, wenn die ID ($1) größer als 102 ist
awk -F: '$1 > 102 { print "ID: " $1 " -> Name: " $2 " (Role: " $3 ")" }' users.db
```

---

## 5. awk: Advanced Stuff (Begins & Ends)
`awk` ist eine vollständige Programmiersprache. Wir nutzen `BEGIN` für Header und `END` für eine Zusammenfassung (Counter).
```bash
# Zähle Einträge und formatiere die Ausgabe professionell
awk -F: '
  BEGIN { print "--- USER REPORT ---"; count=0 }
  { count++; printf "%-10s | %s\n", $2, $3 }
  END { print "-------------------"; print "Total Users: " count }
' users.db
```

---

## 6. Die Power-Pipeline: sed + awk kombiniert
Hier verketten wir alles: Wir nutzen `sed` zur Vorreinigung der Daten und `awk` zur finalen Berichterstattung.
```bash
# 1. Filtere alle Nicht-Admins (via sed)
# 2. Wandle Namen in Großbuchstaben um (via awk)
# 3. Speichere das Ergebnis in einer Neptune-Variable
REPORT=$(sed -n '/admin\|ai_copilot/p' users.db | awk -F: '{ print toupper($2) " ist autorisiert." }')

echo "Finaler Report Status:"
echo "$REPORT"
```

---

## 7. Persistenz-Check
Da Neptune den State hält, können wir die in Block 1 erstellte Datei und die Variable aus Block 6 jederzeit wieder aufrufen.

```bash
# Teste, ob die Variable aus dem vorherigen Block noch lebt
if [ -n "$REPORT" ]; then
    echo "Neptune Persistenz-Check: SUCCESS"
    echo "Inhalt: $REPORT"
else
    echo "Check: FAILED"
fi
```