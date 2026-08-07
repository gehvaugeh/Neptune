# Shell Notebook Export - 2026-06-02 12:01:01

Zuächst testen wir mit Telnet ob eine Verbindung auf den Port von MailHog vom Appserver zum Webserver möglich ist.

```bash (uid:1)
telnet sosmig-web.hio.rub.de 1025
```

---

Wenn die Verbindung fehlschlägt prüfen wir zunächst ob eine *Outbound* Regel in der Firewall geschaltet ist.

```bash (uid:1)
echo "IPV4 Outbound (filtered for sosmig-web):"
sudo iptables -L OUTPUT | grep sosmig-web 
echo "IPV6 Outbound (filtered for sosmig-web):"
sudo ip6tables -L OUTPUT | grep sosmig-web
```

Gegebenenfalls müssen wir die Regeln hinzufügen, diese müssen *Outbound* und auf *Port 1025* gehen:

```bash (uid:1)
sudo iptables -A OUTPUT -p tcp -d sosmig-web.hio.rub.de --dport 1025 -j ACCEPT
sudo ip6tables -A OUTPUT -p tcp -d sosmig-web.hio.rub.de --dport 1025 -j ACCEPT
```

---

Jetzt können wir den Verbindungsaufbau via Telnet (siehe Oben) erneut ausführen um zu sehen ob es funktioniert. Falls nicht fehlt vermutlich noch die Regel auf Seite des _Webservers_. Diese legen wir nun an:

```bash (uid:2)
echo "IPV4 Outbound (filtered for sosmig-app):"
sudo iptables -L INPUT | grep sosmig-app 
echo "IPV6 Outbound (filtered for sosmig-app):"
sudo ip6tables -L INPUT | grep sosmig-app
```

```bash (uid:2)
sudo iptables -A INPUT -p tcp -s sosmig-app.hio.rub.de --dport 1025 -j ACCEPT
sudo ip6tables -A INPUT -p tcp -s sosmig-app.hio.rub.de --dport 1025 -j ACCEPT
```

---

Ein erneuter Test kann nun erfolgen (wieder via telnet). Wenn wir ein Connection Refused aber kein Timeout erhalten , scheint eine Verbindung mölich zu sein es lauscht nur keiner am anderen Ende. Wir nehmen nun netcat um das zu ändern und final die Verbindung zu verifizieren:

```bash (uid:2)
sudo apt install netcat-openbsd -y
```

Wir starten Netcat auf Port 1025, damit am anderen Ende jemand *abnimmt* um die Verbindung zu testen:

```bash (uid:2)
nc -l -p 1025
```

---

Jetzt wo netcat lauscht können wir die telnet Verbindung aus dem Commandblock weiter oben erneut aufbauen.
> Hinweis: Sollte nun keine Verbindung hergestellt werden können muss ISSI die ACLs anpassen.

Als nächstes kann der Mailhog als Service auf dem Webserver eingerichtet werden. Dazu legen wir eine neue Serviceunit an. Hier der Inhalt der Servicedatei:

```System Unit MailHog
[Unit]
Description=Mailtrap via MailHog for HiO
After=network.target

[Service]
Type=simple
User=www-data
ExecStart=/opt/mailhog/MailHog
EnvironmentFile=/opt/mailhog/.env
StandardOutput=journal
StandardError=journal
SyslogIdentifier=mailhog
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash (uid:2)
sudo vim /etc/systemd/system/mailhog.service
```

Mailhog verwendet eine .env Datei für die Konfiguration, hier schalten wir die Authentifizierung ein. Diese Konfigurationsdatei wird in der Servicedatei oben angegeben unter *EnviromentFile*. Zunächst muss das Arbeitsverzeichnis für die Mailhog Binary und die Konfiguration angelegt werden. Danach können wir die Konfiguration anlegen:

```bash (uid:2)
sudo mkdir -p /opt/mailhog
```

```bash (uid:2)
sudo vim /opt/mailhog/.env
```

Wenn wir alle Dateien angelegt haben, können wir den Service aktivieren und den Servicedaemon reloaden damit der neue Service verfügbar ist:

```bash (uid:2)
sudo systemctl enable mailhog
```

```bash (uid:2)
sudo systemctl daemon-reload
```

---

Abschliessend müssen wir noch den Mailhog bereitstellen. Dafür müssen wir den lokalen Umweg wählen, da der Webserver keinen Zugriff auf die entsprechenden Ressourcen im Internet hat. Also laden wir zunächst auf unser lokales System die Binary runter und kopieren sie dann via scp auf den Webserver:

```bash (uid:0)
curl -LO https://github.com/mailhog/MailHog/releases/download/v1.0.0/MailHog_linux_amd64
```

```bash (uid:0)
scp MailHog_linux_amd64 vangegcz@sosmig-web.hio.rub.de:/tmp/MailHog
```

```bash (uid:2)
sudo mv /tmp/MailHog /opt/mailhog/MailHog
```

> Hinweis: Wir haben keine Berechtigung auf Opt zu schreiben also müssen wir die Datei in tmp zwischenspeichern und dann verschieben via sudo. Bitte auf die Gross- / Kleinschreibung der Binary achten, diese muss mit der in der Servicedatei übereinstimmen!

Jetzt können wir den Mailhog final starten:

```bash (uid:2)
sudo systemctl start mailhog && sudo systemctl status mailhog
```

---

Sollten beim Starten Fehlerauftreten, schauen wir in das Journal des Mailhog Service mit folgendem Befehl (ich empfehle diesen in einer weiter remote pty zu starten, dann kann diese in Echtzeit beim Start eingesehen werden):

```bash (uid:2)
sudo journalctl -u mailhog
```

Es scheint so als gäbe es ein Problem bei der Ausführung. Dies könnte ein Berechtigungsproblem sein, also sehen wir uns diese an:

```bash (uid:2)
ls -la /opt/mailhog
```

Der Benutzer ist noch der von meinem lokalen System und obendrein fehlen die Ausführbrechtigungen, das fixen wir schnell dann starten wir den Service neu:

```bash (uid:2)
sudo chown root:root /opt/mailhog/MailHog
```

```bash (uid:2)
sudo chmod 755 /opt/mailhog/MailHog
```

---

Jetzt ist er Service gestartet. Wir können nun nochmal über den Telnet Befehl ganz am Anfang dieses Notebooks mit dem MailHog verbinden und via SMTP Protokoll eine Mail manuell schicken. Dazu kann der folgende Codeschnipsl verwndet werden (einfach über den Interaktiven Modus im Telnet Commandblock einfügen):

```SMTP
EHLO test.de
MAIL FROM:<bob@test.de>
RCPT TO:<alice@test.de>
DATA
Subject: Test Mail via Telet
From: bob@test.de
To: alice@test.de

Hallo Alice,
hier ist ein kurzer Inhalt von Bob.
.
QUIT
```

---

Wie wir oben gesehen haben schreibt MailHog aktuell nur in das Systemjournal. Für Diagnosezwecke und für eine bessere Übersicht kann es aber ratsam sein, ein eigenes Log für den MailHog einzurichten. Dazu legen wir zunächst ein entsprechendes Verzeichnis an:

```bash (uid:2)
sudo mkdir -p /var/log/mailhog
```

Nun können wir Teile des Systemlogs, welche dem MailHog zugeordnet sind extrahieren und in eine eigene Logdatei schreiben. Der zugehörige Service der das macht heisst rsyslog. Dieser verteilt anhand von Filterregeln Logeinträge an verschiedene Quellen, unter anderem Dateien. Wir erzeugen nun eine neue Konfigurationsdatei mit folgendem Inhalt:

```rsyslog filter
if $programname == 'mailhog' then {
  action(type="omfile" file="/var/log/mailhog/logfile.log")
  stop
}
```

> Hinweis: Der Programmname ist der *SyslogIdentifier* den wir oben in der Servicedatein zugewiesen haben

```bash (uid:2)
sudo vim /etc/rsyslog.d/mailhog.conf
```

Nun müssen wir noch die Berechtigungen anpassen und den Dienst rsyslog neustarten:

```bash (uid:2)
sudo chown -R syslog:adm /var/log/mailhog
```

```bash (uid:2)
ls -la /var/log/mailhog
```

```bash (uid:2)
sudo systemctl enable rsyslog.service
```

Wenn rsyslog nicht installiert ist (das kann auf neueren Ubuntu Versionen der Fall sein), installieren wir es einfach nach:

```bash (uid:2)
sudo apt install rsyslog -y
```

```bash (uid:2)
sudo tail -F /var/log/mailhog/logfile.log
```

---
Der MailHog Service und die Logdatei stehen nun. Ein letzter Schritt au dem Websever wäre noch das logrotate für letztere einzurichten. Das geht über den Dienst logrotate. Dazu legen wir wieder eine eigene Konfiguration an mit dem folgnden Inhalt:

```logrotate Konfiguration
/var/log/blubbi.log {
    daily
    rotate 7
    missingok
    notifempty
    compress
    delaycompress
    sharedscripts
    postrotate
        /usr/lib/rsyslog/rsyslog-rotate
    endscript
}
```

```bash (uid:2)
sudo vim /etc/logrotate.d/mailhog
```

```bash (uid:2)
sudo ls /etc/logrotate.d/
```

Ein kurzer Testaufruf des logrotate zeigt ob die Konfiguration so passt (ist eine Trockenübung und führt keine persistenten Änderungen auf dem Dateisystem durch):

```bash (uid:2)
sudo logrotate -d /etc/logrotate.d/mailhog
```

---

Nun können wir testweise die WebUI vom MailHog aufrufen, dazu müssen wir via ssh den remote Port auf einen lokalen tunneln:
> Hinweis: Das machen wir am besten in einer neuen lokalen ptty damit wir unsere default pty nicht blockieren -> !!local<return>:

```bash (uid:0)
ssh -N -L 8080:127.0.0.1:8025 vangegcz@sosmig-web.hio.rub.de
```

Wenn wir nun die lokale Seite [http://127.0.0.1:8080] aufrufen sollten wir die WebUI sehen.

---

Abschliessend müssen wir noch die Konfiguration im HiO prüfen und dann sind wir abgesehen von der Authentifizierung fertig. Dazu sehen wir uns die Dispatcherproperties auf dem Applikationsserver an. Folgendes muss dort konfiguriert sein:

```Dispatcherproperties
# Mailserver auf Mailhog verweisen (Überschreiben rub variante)                          
MAIL_SERVER=sosmig-web.hio.ruhr-uni-bochum.de                                            
                                                                                          
# Mail-Port MailHog                                                                      
MAIL_SERVER_PORT=1025
```

```bash (uid:1)
sudo vim /var/lib/tomcat10/webapps/qisserver/WEB-INF/conf/DispatcherProperties_rub-sosmig.txt
```

Sollten wir die Dispatcherproperties angepasst haben ist noch ein neustart des Tomcat notwendig. Ansonsten ist nun alles konfiguriert und kann getestet werden.
