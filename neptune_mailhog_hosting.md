# MailHog Reverse Proxy – Interaktives Tutorial

Erstellt am 26.06.2026 für qs-web.hio.rub.de

---

## 1. Überblick

MailHog läuft bereits auf dem Webserver und stellt einen SMTP-Server (Port 1025) sowie eine WebUI (Port 8025) bereit.
Ziel dieses Tutorials: Die WebUI via Apache Reverse Proxy unter einem URL-Pfad erreichbar machen.

### Dienste

| Service          | Adresse                         | Zugriff         |
|------------------|----------------------------------|-----------------|
| WebUI (via Proxy)| `http://qs-web.hio.rub.de/mailhog/` | öffentlich      |
| WebUI (direkt)   | `http://localhost:8025/`         | nur lokal        |
| SMTP             | `localhost:1025`                 | nur lokal        |
| Apache           | `http://qs-web.hio.rub.de:80` | öffentlich      |

### Beteiligte Maschinen

| Alias in diesem Tutorial | Adresse                        |
|--------------------------|--------------------------------|
| `qs-web` (uid:1)     | `qs-web.hio.rub.de`        |

Alle Kommandos laufen auf `qs-web`. Sollte ein zweites Terminal nötig sein (z.B. um Requests parallel zu beobachten), wird `uid:2` verwendet.

---

## 2. Voraussetzungen prüfen

Bevor wir Änderungen vornehmen, prüfen wir den aktuellen Zustand.

### MailHog Service

MailHog muss aktiv und läuft sein.

```bash (uid:1)
systemctl is-active mailhog 2>/dev/null && echo "OK - MailHog läuft" || echo "FEHLER - MailHog läuft nicht"
```

### MailHog Version

```bash (uid:1)
/opt/mailhog/MailHog --version 2>&1 | head -1 && echo "OK" || echo "FEHLER - kein Binary"
```

### Apache läuft?

```bash (uid:1)
systemctl is-active apache2 2>/dev/null && echo "OK - Apache läuft" || echo "FEHLER - Apache läuft nicht"
```

### Port 8025 (MailHog WebUI)

```bash (uid:1)
ss -tlnp | grep -q ":8025" && echo "OK - Port 8025 belegt" || echo "FEHLER - nichts auf Port 8025"
```

### Port 1025 (MailHog SMTP)

```bash (uid:1)
ss -tlnp | grep -q ":1025" && echo "OK - Port 1025 belegt" || echo "FEHLER - nichts auf Port 1025"
```

### Apache-Module für den Reverse Proxy

Folgende Module werden benötigt: `proxy`, `proxy_http`, `proxy_wstunnel`, `substitute`.

```bash (uid:1)
for mod in proxy proxy_http proxy_wstunnel substitute; do
  apache2ctl -M 2>&1 | grep -q "${mod}_module\|${mod} " && echo "OK - $mod" || echo "FEHLER - $mod fehlt"
done
```

Zeile für Zeile prüfen. Wenn alle vier Module mit "OK" quittieren, kannst du zu **Schritt 4** springen.  
Fehlt ein Modul, geht es in **Schritt 3** weiter.

---

## 3. Apache-Module aktivieren

Fehlende Module werden jetzt aktiviert.

```bash (uid:1)
sudo a2enmod proxy proxy_http proxy_wstunnel substitute
```

**Prüfung:** Alle vier Module müssen jetzt geladen sein.

```bash (uid:1)
COUNT=$(apache2ctl -M 2>&1 | grep -cE "proxy_module|proxy_http_module|proxy_wstunnel_module|substitute_module")
[ "$COUNT" -eq 4 ] && echo "OK - alle Module aktiv" || echo "FEHLER - nur $COUNT/4 Modulen aktiv"
```

---

## 4. Reverse-Proxy-Konfiguration anlegen

Wir erstellen eine Apache-Konfigurationsdatei in `conf-available/`.  
Diese leitet Aufrufe von `/mailhog/` an die lokal laufende MailHog-Instanz (Port 8025) weiter und reicht auch WebSocket-Verbindungen durch.

```bash (uid:1)
sudo tee /etc/apache2/conf-available/mailhog.conf <<'EOF'
Redirect 301 /mailhog /mailhog/

ProxyPass /mailhog/ws ws://127.0.0.1:8025/ws
ProxyPassReverse /mailhog/ws ws://127.0.0.1:8025/ws

ProxyPass /mailhog/ http://127.0.0.1:8025/
ProxyPassReverse /mailhog/ http://127.0.0.1:8025/
EOF
```

**Prüfung:** Datei existiert und hat Inhalt.

```bash (uid:1)
test -s /etc/apache2/conf-available/mailhog.conf && echo "OK - Konfiguration angelegt" || echo "FEHLER - Datei nicht vorhanden oder leer"
```

**Optional:** Konfiguration anzeigen.

```bash (uid:1)
cat /etc/apache2/conf-available/mailhog.conf
```

**Nachbearbeitung:** Config in vim öffnen und ggf. anpassen.

```bash (uid:1)
sudo vim /etc/apache2/conf-available/mailhog.conf
```

---

## 5. Konfiguration aktivieren & testen

### Config aktivieren

```bash (uid:1)
sudo a2enconf mailhog
```

### Syntax-Prüfung

Apache testet selbst, ob die Konfiguration syntaktisch korrekt ist.

```bash (uid:1)
sudo apache2ctl configtest && echo "OK - Syntax korrekt" || echo "FEHLER - Syntax-Fehler in der Konfiguration"
```

Sollte hier ein Fehler erscheinen, lies die Fehlermeldung genau und korrigiere die Datei aus **Schritt 4**.

### Apache neuladen

```bash (uid:1)
sudo systemctl reload apache2 && echo "OK - Apache neugeladen" || echo "FEHLER - Neuladen fehlgeschlagen"
```

**Prüfung:** Apache läuft weiterhin sauber.

```bash (uid:1)
systemctl is-active apache2 2>/dev/null && echo "OK - Apache läuft" || echo "FEHLER - Apache abgestürzt"
```

---

## 6. Verifikation

Jetzt testen wir, ob der Reverse Proxy funktioniert.

### WebUI-Hauptseite

```bash (uid:1)
curl -s -o /dev/null -w "%{http_code}" http://localhost/mailhog/ | grep -q 200 && echo "OK - HTTP 200" || echo "FEHLER"
```

**Erwartet:** `OK - HTTP 200`

### CSS-Asset laden

```bash (uid:1)
curl -s -o /dev/null -w "%{http_code}" http://localhost/mailhog/css/style.css | grep -q 200 && echo "OK - CSS ladbar" || echo "FEHLER"
```

### JavaScript-Asset laden

```bash (uid:1)
curl -s -o /dev/null -w "%{http_code}" http://localhost/mailhog/js/controllers.js | grep -q 200 && echo "OK - JS ladbar" || echo "FEHLER"
```

### Bild-Asset laden

```bash (uid:1)
curl -s -o /dev/null -w "%{http_code}" http://localhost/mailhog/images/hog.png | grep -q 200 && echo "OK - Bilder ladbar" || echo "FEHLER"
```

### API testen

```bash (uid:1)
curl -s -o /dev/null -w "%{http_code}" http://localhost/mailhog/api/v2/messages | grep -q 200 && echo "OK - API erreichbar" || echo "FEHLER"
```

### Konnten bereits E-Mails empfangen werden?

```bash (uid:1)
curl -s http://localhost/mailhog/api/v2/messages | head -c 200
```

Zeigt die ersten 200 Zeichen der API-Antwort. Ist `"total":0` enthalten, wurden noch keine E-Mails empfangen.

### Alle Tests in einem Rutsch

```bash (uid:1)
echo "=== MailHog Proxy-Test ==="
for url in \
  "http://localhost/mailhog/" \
  "http://localhost/mailhog/css/style.css" \
  "http://localhost/mailhog/js/controllers.js" \
  "http://localhost/mailhog/images/hog.png" \
  "http://localhost/mailhog/api/v2/messages"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$url")
  status="OK"
  [ "$code" != "200" ] && status="FEHLER"
  printf "  %-55s %s (%s)\n" "$url" "$status" "$code"
done
```

### WebSocket testen (optional)

Benötigt `wscat` (Netzwerk-Tool). Installiere es bei Bedarf.

```bash (uid:1)
which wscat 2>/dev/null 1>&2 && echo "OK - wscat installiert" || echo "HINWEIS - wscat fehlt, Schritt überspringbar"
```

```bash (uid:1)
which wscat 2>/dev/null 1>&2 && echo '{"type":"ping"}' | timeout 3 wscat -c ws://localhost/mailhog/ws 2>&1 | head -3 || echo "übersprungen (wscat nicht installiert)"
```

---

## 7. (Optional) Port-Bindung sichern

Aktuell bindet MailHog auf `0.0.0.0:8025` und `0.0.0.0:1025` – also auf allen Netzwerk-Interfaces.  
Sollen die Dienste **nur lokal** erreichbar sein (empfohlen für Produktion), muss die `.env` angepasst werden.

### Aktuelle Bindung prüfen

```bash (uid:1)
ss -tlnp | grep -E "8025|1025"
```

Siehst du `*:8025` oder `0.0.0.0:8025`, ist der Dienst auf allen Interfaces offen.

### .env-Datei anpassen

```bash (uid:1)
sudo tee /opt/mailhog/.env <<'EOF'
MH_UI_BIND_ADDR=127.0.0.1:8025
MH_SMTP_BIND_ADDR=127.0.0.1:1025
EOF
```

**Prüfung:**

```bash (uid:1)
cat /opt/mailhog/.env
```

Darstellung sollte `127.0.0.1` für beide Adressen zeigen.

**Nachbearbeitung:** Config in vim öffnen und ggf. anpassen.

```bash (uid:1)
sudo vim /opt/mailhog/.env
```

### MailHog neustarten

```bash (uid:1)
sudo systemctl restart mailhog && echo "OK - MailHog neugestartet" || echo "FEHLER"
```

### Erneute Prüfung

```bash (uid:1)
ss -tlnp | grep -E "8025|1025"
```

Jetzt sollten `127.0.0.1:8025` und `127.0.0.1:1025` angezeigt werden.

### Proxy erneut testen

```bash (uid:1)
curl -s -o /dev/null -w "%{http_code}" http://localhost/mailhog/ | grep -q 200 && echo "OK - Proxy funktioniert weiterhin" || echo "FEHLER"
```

---

## 8. Service-Management (Referenz)

### MailHog

```bash (uid:1)
# Status
systemctl status mailhog

# Logs verfolgen
journalctl -u mailhog -f

# Letzte 50 Logzeilen
journalctl -u mailhog -n 50 --no-pager

# Neustarten
sudo systemctl restart mailhog

# Stoppen / Starten
sudo systemctl stop mailhog
sudo systemctl start mailhog

# Autostart konfigurieren
sudo systemctl enable mailhog
sudo systemctl disable mailhog
```

### Apache Proxy

```bash (uid:1)
# Proxy-Konfiguration aktivieren/deaktivieren
sudo a2enconf mailhog
sudo a2disconf mailhog

# Apache neu laden (nach Config-Änderungen)
sudo systemctl reload apache2

# Config-Syntax prüfen
sudo apache2ctl configtest
```

---

## 9. Dateien & Pfade

| Datei / Verzeichnis                          | Zweck                           |
|-----------------------------------------------|---------------------------------|
| `/opt/mailhog/MailHog`                       | MailHog-Binary (v1.0.0)         |
| `/opt/mailhog/.env`                          | Umgebungsvariablen               |
| `/etc/systemd/system/mailhog.service`        | Systemd-Service-Definition       |
| `/etc/apache2/conf-available/mailhog.conf`   | Apache-Proxy-Konfiguration       |
| `/etc/apache2/conf-enabled/mailhog.conf`     | Aktivierter Symlink              |

---

## 10. Troubleshooting

### "502 Proxy Error" beim Aufruf von `/mailhog/`

Mögliche Ursachen:

1. MailHog läuft nicht
   ```bash (uid:1)
   sudo systemctl restart mailhog
   ```

2. Apache-Module fehlen
   ```bash (uid:1)
   sudo a2enmod proxy proxy_http proxy_wstunnel
   sudo systemctl reload apache2
   ```

3. Port-Konflikt – Prüfen ob Port 8025 belegt ist
   ```bash (uid:1)
   ss -tlnp | grep 8025
   ```

### Assets (CSS/JS) laden nicht

MailHog verwendet relative Pfade. Solange die Seite unter `/mailhog/` aufgerufen wird, sollten alle Assets korrekt laden.  
Tritt der Fehler nach einer Änderung auf, Apache neuladen:

```bash (uid:1)
sudo systemctl reload apache2
```

### WebSocket-Updates live funktionieren nicht

WebSocket wird über `/mailhog/ws` weitergeleitet. Prüfung:

```bash (uid:1)
apache2ctl -M 2>&1 | grep proxy_wstunnel && echo "OK - Modul da" || echo "FEHLER - proxy_wstunnel fehlt"
```

### Configtest schlägt fehl

Bei Syntax-Fehlern die genaue Zeile aus der Fehlermeldung notieren und die Config-Datei korrigieren:

```bash (uid:1)
sudo apache2ctl configtest 2>&1
```

---

## 11. Security Review

Sicherheitsanalyse des aktuellen Setups mit abgestuften Maßnahmen.

### 11.1 Aktuelle Risikobewertung

#### 🔴 Kritisch

| Risiko | Detail | Gegenmaßnahme |
|--------|--------|---------------|
| **Port 8025 offen auf `0.0.0.0`** | MailHog-WebUI (inkl. API) ist von außen erreichbar – ohne Authentifizierung | Bindung auf `127.0.0.1` in `.env` setzen (siehe Stufe 1) |
| **Port 1025 offen auf `0.0.0.0`** | SMTP-Server ist von außen erreichbar – kann für Spam-Relaying missbraucht werden | Bindung auf `127.0.0.1` in `.env` setzen (siehe Stufe 1) |
| **Keine Authentifizierung** | MailHog hat kein Login – jeder mit Zugriff auf die WebUI sieht alle E-Mails | IP-Beschränkung oder Basic-Auth via Apache (siehe Stufe 2/3) |

#### 🟡 Mittel

| Risiko | Detail | Gegenmaßnahme |
|--------|--------|---------------|
| **.env-Datei** liegt unverschlüsselt auf Disk | Keine Secrets aktuell, aber potenzieller Angriffspunkt | Berechtigungen auf `600` setzen (siehe Stufe 1) |
| **Apache-Proxy ohne Zugriffsschutz** | Jeder mit der URL kann auf MailHog zugreifen | IP-Block oder Basic-Auth (siehe Stufe 2/3) |
| **Kein HTTPS für `/mailhog/`** | Nur HTTP – Traffic in Klartext | Proxy-Konfiguration in SSL-VHost einbinden |
| **MailHog als `www-data`** | Läuft unter gleichem User wie Apache | Standard, aber dedizierter Service-User wäre strikter |

#### 🟢 Grün (bereits gut)

| Aspekt | Bewertung |
|--------|-----------|
| `Restart=always` im Service | MailHog startet bei Absturz neu |
| Memory-Storage | Standard: keine Persistenz sensibler Mails |
| Eigener Systemd-Service | Saubere Trennung, keine Abhängigkeit zu Apache |

---

### 11.2 Stufe 1 – Port-Bindung & Berechtigungen (Sofortmaßnahme)

MailHog bindet standardmäßig auf `0.0.0.0`. Das schränken wir auf localhost ein.

```bash (uid:1)
echo -e "MH_UI_BIND_ADDR=127.0.0.1:8025\nMH_SMTP_BIND_ADDR=127.0.0.1:1025" | sudo tee /opt/mailhog/.env
```

**Nachbearbeitung:** Prüfen und ggf. anpassen.

```bash (uid:1)
sudo vim /opt/mailhog/.env
```

**Berechtigungen der `.env`-Datei verschärfen:**

```bash (uid:1)
sudo chown www-data:www-data /opt/mailhog/.env && sudo chmod 600 /opt/mailhog/.env && echo "OK - Berechtigungen gesetzt" || echo "FEHLER"
```

**Prüfung:**

```bash (uid:1)
ls -la /opt/mailhog/.env
```

Sollte `-rw------- 1 www-data www-data` anzeigen.

**MailHog neustarten, damit die neuen Bindings greifen:**

```bash (uid:1)
sudo systemctl restart mailhog && echo "OK" || echo "FEHLER"
```

**Erneute Port-Prüfung – jetzt müssen `127.0.0.1:8025` und `127.0.0.1:1025` stehen:**

```bash (uid:1)
ss -tlnp | grep -E "8025|1025"
```

**Proxy nochmals testen (lokal funktioniert der Reverse Proxy weiterhin):**

```bash (uid:1)
curl -s -o /dev/null -w "%{http_code}" http://localhost/mailhog/ | grep -q 200 && echo "OK - Proxy funktioniert" || echo "FEHLER"
```

---

### 11.3 Stufe 2 – IP-basierte Zugriffsbeschränkung (Empfohlen)

Die MailHog-WebUI wird nur noch aus bestimmten Netzwerken erreichbar gemacht.

**Config um IP-Beschränkung erweitern:**

```bash (uid:1)
sudo tee -a /etc/apache2/conf-available/mailhog.conf <<'EOF'

<Location /mailhog/>
    Require ip 10.0.0.0/8 141.0.0.0/8
</Location>
EOF
```

**Nachbearbeitung:** Config öffnen und IP-Bereiche ggf. anpassen.

```bash (uid:1)
sudo vim /etc/apache2/conf-available/mailhog.conf
```

**Syntax-Prüfung:**

```bash (uid:1)
sudo apache2ctl configtest && echo "OK - Syntax korrekt" || echo "FEHLER"
```

**Apache neuladen:**

```bash (uid:1)
sudo systemctl reload apache2 && echo "OK" || echo "FEHLER"
```

**Test von localhost (sollte funktionieren):**

```bash (uid:1)
curl -s -o /dev/null -w "%{http_code}" http://localhost/mailhog/ | grep -q 200 && echo "OK - Lokaler Zugriff erlaubt" || echo "FEHLER"
```

---

### 11.4 Stufe 3 – Basic-Auth mit htpasswd (Optional, aber empfohlen)

Wenn dynamische IPs im Spiel sind, ist Basic-Auth die robustere Lösung.

**htpasswd-Datei anlegen (Benutzer `admin`):**

```bash (uid:1)
sudo htpasswd -c /opt/mailhog/htpasswd admin
```

**Hinweis:** Das Passwort wird interaktiv abgefragt. Für weitere Nutzer den `-c`-Parameter weglassen:

```bash (uid:1)
sudo htpasswd /opt/mailhog/htpasswd weitere-username
```

**Config um Basic-Auth erweitern (ersetzt die IP-Beschränkung aus Stufe 2):**

```bash (uid:1)
sudo tee /etc/apache2/conf-available/mailhog.conf <<'EOF'
Redirect 301 /mailhog /mailhog/

ProxyPass /mailhog/ws ws://127.0.0.1:8025/ws
ProxyPassReverse /mailhog/ws ws://127.0.0.1:8025/ws

ProxyPass /mailhog/ http://127.0.0.1:8025/
ProxyPassReverse /mailhog/ http://127.0.0.1:8025/

<Location /mailhog/>
    AuthType Basic
    AuthName "MailHog - authentifizierter Zugriff"
    AuthUserFile /opt/mailhog/htpasswd
    Require valid-user
</Location>
EOF
```

**Nachbearbeitung:**

```bash (uid:1)
sudo vim /etc/apache2/conf-available/mailhog.conf
```

**Syntax-Prüfung:**

```bash (uid:1)
sudo apache2ctl configtest && echo "OK - Syntax korrekt" || echo "FEHLER"
```

**Apache neuladen:**

```bash (uid:1)
sudo systemctl reload apache2 && echo "OK" || echo "FEHLER"
```

**Test mit Authentifizierung:**

```bash (uid:1)
curl -s -o /dev/null -w "%{http_code}" http://admin:DEIN_PASSWORT@localhost/mailhog/ | grep -q 200 && echo "OK - Auth funktioniert" || echo "FEHLER"
```

**Test ohne Authentifizierung (sollte 401 liefern):**

```bash (uid:1)
curl -s -o /dev/null -w "%{http_code}" http://localhost/mailhog/ | grep -q 401 && echo "OK - 401 ohne Auth" || echo "HINWEIS - kein 401 erhalten"
```

---

### 11.5 Stufe 4 – Zusätzliche Härtung

```bash (uid:1)
# Berechtigungen der htpasswd-Datei setzen
sudo chown www-data:www-data /opt/mailhog/htpasswd && sudo chmod 600 /opt/mailhog/htpasswd

# MailHog-Binary nur für root:www-data ausführbar
sudo chown root:www-data /opt/mailhog/MailHog && sudo chmod 750 /opt/mailhog/MailHog

# .env-Berechtigungen prüfen (falls noch nicht geschehen)
sudo chown www-data:www-data /opt/mailhog/.env && sudo chmod 600 /opt/mailhog/.env
```

---

*Ende des Tutorials. Stand: 26.06.2026. Bei Fragen an hio-admins@ruhr-uni-bochum.de wenden.*
