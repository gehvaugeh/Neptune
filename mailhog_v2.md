# Shell Notebook Export - 2026-06-02 09:51:56

Zuächst testen wir mit Telnet ob eine Verbindung auf den Port von MailHog auf vom Appserver zum Webserver möglich ist.

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

```text
IPV4 Outbound (filtered for sosmig-web):

ACCEPT     tcp  --  anywhere             sosmig-web.hio.ruhr-uni-bochum.de  tcp dpt:1025
ACCEPT     tcp  --  anywhere             sosmig-web.hio.ruhr-uni-bochum.de  tcp dpt:1025
ACCEPT     tcp  --  anywhere             sosmig-web.hio.ruhr-uni-bochum.de  tcp dpt:1025
ACCEPT     tcp  --  anywhere             sosmig-web.hio.ruhr-uni-bochum.de  tcp dpt:1025

IPV6 Outbound (filtered for sosmig-web):

ACCEPT     tcp  --  anywhere             sosmig-web.hio.ruhr-uni-bochum.de  tcp dpt:1025
ACCEPT     tcp  --  anywhere             sosmig-web.hio.ruhr-uni-bochum.de  tcp dpt:1025
```

Gegebenenfalls müssen wir die Regeln hinzufügen, diese müssen *Outbound* und auf *Port 1025* gehen:

```bash (uid:1)
sudo iptables -A OUTPUT -p tcp -d sosmig-web.hio.rub.de --dport 1025 -j ACCEPT
sudo ip6tables -A OUTPUT -p tcp -d sosmig-web.hio.rub.de --dport 1025 -j ACCEPT
```

```text

```

---

Jetzt können wir den Verbindungsaufbau via Telnet (siehe Oben) erneut ausführen um zu sehen ob es funktioniert. Falls nicht fehlt vermutlich noch die Regel auf Seite des _Webservers_. Diese legen wir nun an:

```bash (uid:2)
echo "IPV4 Outbound (filtered for sosmig-app):"
sudo iptables -L OUTPUT | grep sosmig-app 
echo "IPV6 Outbound (filtered for sosmig-app):"
sudo ip6tables -L OUTPUT | grep sosmig-app
```

```text
IPV4 Outbound (filtered for sosmig-app):

ACCEPT     tcp  --  anywhere             sosmig-app.hio.ruhr-uni-bochum.de  state NEW /* sosmig-app.hio.ruhr-uni-bochum.de - AJP */ tcp dpt:8009
ACCEPT     tcp  --  anywhere             sosmig-app.hio.ruhr-uni-bochum.de  tcp dpt:1025

IPV6 Outbound (filtered for sosmig-app):

ACCEPT     tcp  --  anywhere             sosmig-app.hio.ruhr-uni-bochum.de  state NEW /* sosmig-app.hio.ruhr-uni-bochum.de - AJP */ tcp dpt:8009
ACCEPT     tcp  --  anywhere             sosmig-app.hio.ruhr-uni-bochum.de  tcp dpt:1025
```

```bash (uid:2)
sudo iptables -A INPUT -p tcp -s sosmig-app.hio.rub.de --dport 1025 -j ACCEPT
sudo ip6tables -A INPUT -p tcp -s sosmig-app.hio.rub.de --dport 1025 -j ACCEPT
```

```text

```

---

Ein erneuter Test kann nun erfolgen (wieder via telnet). Wenn wir ein Connection Refused aber kein Timeout erhalten , scheint eine Verbindung mölich zu sein es lauscht nur keiner am anderen Ende. Wir nehmen nun netcat um das zu ändern und final die Verbindung zu verifizieren:

```bash (uid:2)
sudo apt install netcat-openbsd -y
```

```text
Reading package lists... 0%Reading package lists... 100%Reading package lists... Done
Building dependency tree... 0%Building dependency tree... 0%Building dependency tree... 50%Building dependency tree... 50%Building dependency tree... Done
Reading state information... 0% Reading state information... 0%Reading state information... Done
netcat-openbsd is already the newest version (1.226-1ubuntu2).
0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.
```

Wir starten Netcat auf Port 1025, damit am anderen Ende jemand *abnimmt* um die Verbindung zu testen:

```bash (uid:2)
nc -l -p 1025
```

```text
����
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

```text
="/etc/systemd/system/mailhog.service" 16L, 294B▽  zz           10;?11;?  1 [Unit]
  2 Description=Mailtrap via MailHog for HiO  3 After=network.target  4 
  5 [Service]
  6 Type=simple
  7 User=www-data
  8 ExecStart=/opt/mailhog/MailHog
  9 EnvironmentFile=/opt/mailhog/.env
 10 StandardOutput=journal
 11 StandardError=journal
 12 SyslogIdentifier=mailhog
 13 Restart=always
 14 
 15 [Install]
 16 WantedBy=multi-user.target
~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~@k   [Unit]~@k   ~@k   ~@k   []~@k   []~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   []~@k   []~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ::q>
```

Mailhog verwendet eine .env Datei für die Konfiguration, hier schalten wir die Authentifizierung ein. Diese Konfigurationsdatei wird in der Servicedatei oben angegeben unter *EnviromentFile*. Zunächst muss das Arbeitsverzeichnis für die Mailhog Binary und die Konfiguration angelegt werden. Danach können wir die Konfiguration anlegen:

```bash (uid:2)
sudo mkdir -p /opt/mailhog
```

```text

```

```bash (uid:2)
sudo vim /opt/mailhog/.env
```

```text
="/opt/mailhog/.env" 1L, 1B▽  zz           10;?11;?  1 
~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       ~                                                                                                                                                                                                       L ^?  ^?  ::w"/opt/mailhog/.env" 1L, 1B written::w"/opt/mailhog/.env" 1L, 1B written::q>
```

Wenn wir alle Dateien angelegt haben, können wir den Service aktivieren und den Servicedaemon reloaden damit der neue Service verfügbar ist:

```bash (uid:2)
sudo systemctl enable mailhog
```

```text

```

```bash (uid:2)
sudo systemctl daemon-reload
```

```text

```

---

Abschliessend müssen wir noch den Mailhog bereitstellen. Dafür müssen wir den lokalen Umweg wählen, da der Webserver keinen Zugriff auf die entsprechenden Ressourcen im Internet hat. Also laden wir zunächst auf unser lokales System die Binary runter und kopieren sie dann via scp auf den Webserver:

```bash (uid:0)
curl -LO https://github.com/mailhog/MailHog/releases/download/v1.0.0/MailHog_linux_amd64
```

```text
% Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                 Dload  Upload   Total   Spent    Left  Speed
  0     0    0     0    0     0      0      0 --:--:-- --:--:-- --:--:--     0  0     0    0     0    0     0      0      0 --:--:-- --:--:-- --:--:--     0
  1 10.7M    1  159k    0     0   208k      0  0:00:52 --:--:--  0:00:52  208k100 10.7M  100 10.7M    0     0  6929k      0  0:00:01  0:00:01 --:--:-- 12.8M
```

```bash (uid:0)
scp MailHog_linux_amd64 vangegcz@sosmig-web.hio.rub.de:/tmp/MailHog
```

```text
MailHog_linux_amd64                                                                                                                                                     0%    0     0.0KB/s   --:-- ETAMailHog_linux_amd64                                                                                                                                                     2%  255KB 254.9KB/s   00:42 ETAMailHog_linux_amd64                                                                                                                                                     2%  255KB 229.4KB/s   00:46 ETAMailHog_linux_amd64                                                                                                                                                     2%  255KB 206.5KB/s   00:51 ETAMailHog_linux_amd64                                                                                                                                                    95%   10MB   1.2MB/s   00:00 ETAMailHog_linux_amd64                                                                                                                                                   100%   11MB   2.6MB/s   00:04
```

```bash (uid:2)
sudo mv /tmp/MailHog /opt/mailhog/MailHog
```

```text

```

> Hinweis: Wir haben keine Berechtigung auf Opt zu schreiben also müssen wir die Datei in tmp zwischenspeichern und dann verschieben via sudo. Bitte auf die Gross- / Kleinschreibung der Binary achten, diese muss mit der in der Servicedatei übereinstimmen!

Jetzt können wir den Mailhog final starten:

```bash (uid:2)
sudo systemctl start mailhog && sudo systemctl status mailhog
```

```text
=● mailhog.service - Mailtrap via MailHog for HiO
     Loaded: loaded (8;;file://sosmig-web/etc/systemd/system/mailhog.service/etc/systemd/system/mailhog.service8;;; enabled; preset: enabled)
     Active: active (running) since Tue 2026-06-02 09:45:24 CEST; 14ms ago
   Main PID: 4120609 (MailHog)
      Tasks: 6 (limit: 19037)
     Memory: 1.8M (peak: 2.2M)
        CPU: 5ms
     CGroup: /system.slice/mailhog.service
             └─4120609 /opt/mailhog/MailHog

Jun 02 09:45:24 sosmig-web systemd[1]: Started mailhog.service - Mailtrap via MailHog for HiO.
Jun 02 09:45:24 sosmig-web mailhog[4120609]: 2026/06/02 09:45:24 Using in-memory storage
Jun 02 09:45:24 sosmig-web mailhog[4120609]: 2026/06/02 09:45:24 [SMTP] Binding to address: 0.0.0.0:1025
Jun 02 09:45:24 sosmig-web mailhog[4120609]: [HTTP] Binding to address: 0.0.0.0:8025
Jun 02 09:45:24 sosmig-web mailhog[4120609]: 2026/06/02 09:45:24 Serving under http://0.0.0.0:8025/
Jun 02 09:45:24 sosmig-web mailhog[4120609]: Creating API v1 with WebPath:
Jun 02 09:45:24 sosmig-web mailhog[4120609]: Creating API v2 with WebPath:
>
```

---

Sollten beim Starten Fehlerauftreten, schauen wir in das Journal des Mailhog Service mit folgendem Befehl (ich empfehle diesen in einer weiter remote pty zu starten, dann kann diese in Echtzeit beim Start eingesehen werden):

```bash (uid:3)
sudo journalctl -u mailhog
```

```text
=May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed to load environment files: No such file or directory
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed to spawn 'start' task: No such file or directory
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed with result 'resources'.
May 29 15:56:04 sosmig-web systemd[1]: Failed to start mailhog.service - Mailtrap via MailHog for HiO.
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Scheduled restart job, restart counter is at 1.
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed to load environment files: No such file or directory
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed to spawn 'start' task: No such file or directory
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed with result 'resources'.
May 29 15:56:04 sosmig-web systemd[1]: Failed to start mailhog.service - Mailtrap via MailHog for HiO.
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Scheduled restart job, restart counter is at 2.
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed to load environment files: No such file or directory
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed to spawn 'start' task: No such file or directory
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed with result 'resources'.
May 29 15:56:04 sosmig-web systemd[1]: Failed to start mailhog.service - Mailtrap via MailHog for HiO.
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Scheduled restart job, restart counter is at 3.
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Failed to load environment files: No such file or directory
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Failed to spawn 'start' task: No such file or directory
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Failed with result 'resources'.
May 29 15:56:05 sosmig-web systemd[1]: Failed to start mailhog.service - Mailtrap via MailHog for HiO.
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Scheduled restart job, restart counter is at 4.
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Failed to load environment files: No such file or directory
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Failed to spawn 'start' task: No such file or directory
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Failed with result 'resources'.
lines 1-23...skipping...
Jun 02 09:37:03 sosmig-web systemd[1]: mailhog.service: Scheduled restart job, restart counter is at 2.
Jun 02 09:37:03 sosmig-web systemd[1]: Started mailhog.service - Mailtrap via MailHog for HiO.
Jun 02 09:37:03 sosmig-web systemd[1]: mailhog.service: Main process exited, code=exited, status=203/EXEC
Jun 02 09:37:03 sosmig-web systemd[1]: mailhog.service: Failed with result 'exit-code'.
Jun 02 09:37:03 sosmig-web systemd[1]: mailhog.service: Scheduled restart job, restart counter is at 3.
Jun 02 09:37:03 sosmig-web systemd[1]: Started mailhog.service - Mailtrap via MailHog for HiO.
Jun 02 09:37:03 sosmig-web systemd[1]: mailhog.service: Main process exited, code=exited, status=203/EXEC
Jun 02 09:37:03 sosmig-web systemd[1]: mailhog.service: Failed with result 'exit-code'.
Jun 02 09:37:04 sosmig-web systemd[1]: mailhog.service: Scheduled restart job, restart counter is at 4.
Jun 02 09:37:04 sosmig-web systemd[1]: Started mailhog.service - Mailtrap via MailHog for HiO.
Jun 02 09:37:04 sosmig-web systemd[1]: mailhog.service: Main process exited, code=exited, status=203/EXEC
Jun 02 09:37:04 sosmig-web systemd[1]: mailhog.service: Failed with result 'exit-code'.
Jun 02 09:37:04 sosmig-web systemd[1]: mailhog.service: Scheduled restart job, restart counter is at 5.
Jun 02 09:37:04 sosmig-web systemd[1]: mailhog.service: Start request repeated too quickly.
Jun 02 09:37:04 sosmig-web systemd[1]: mailhog.service: Failed with result 'exit-code'.
Jun 02 09:37:04 sosmig-web systemd[1]: Failed to start mailhog.service - Mailtrap via MailHog for HiO.
Jun 02 09:45:24 sosmig-web systemd[1]: Started mailhog.service - Mailtrap via MailHog for HiO.
Jun 02 09:45:24 sosmig-web mailhog[4120609]: 2026/06/02 09:45:24 Using in-memory storage
Jun 02 09:45:24 sosmig-web mailhog[4120609]: 2026/06/02 09:45:24 [SMTP] Binding to address: 0.0.0.0:1025
Jun 02 09:45:24 sosmig-web mailhog[4120609]: [HTTP] Binding to address: 0.0.0.0:8025
Jun 02 09:45:24 sosmig-web mailhog[4120609]: 2026/06/02 09:45:24 Serving under http://0.0.0.0:8025/
Jun 02 09:45:24 sosmig-web mailhog[4120609]: Creating API v1 with WebPath:
Jun 02 09:45:24 sosmig-web mailhog[4120609]: Creating API v2 with WebPath:
lines 205-227/227 (END)
```

Es scheint so als gäbe es ein Problem bei der Ausführung. Dies könnte ein Berechtigungsproblem sein, also sehen wir uns diese an:

```bash (uid:2)
ls -la /opt/mailhog
```

```text
total 10988
drwxr-xr-x 2 root root     4096 Jun  2 09:16 .
drwxr-xr-x 3 root root     4096 May 29 16:10 ..
-rw-r--r-- 1 root root        1 Jun  2 09:16 .env
-rwxr-xr-x 1 root root 11235353 Jun  2 09:11 MailHog
```

Der Benutzer ist noch der von meinem lokalen System und obendrein fehlen die Ausführbrechtigungen, das fixen wir schnell dann starten wir den Service neu:

```bash (uid:2)
sudo chown root:root /opt/mailhog/MailHog
```

```text

```

```bash (uid:2)
sudo chmod 755 /opt/mailhog/MailHog
```

```text

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
