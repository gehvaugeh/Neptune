# Shell Notebook Export - 2026-06-02 11:19:28

Zuächst testen wir mit Telnet ob eine Verbindung auf den Port von MailHog vom Appserver zum Webserver möglich ist.

```bash (uid:0)
telnet sosmig-web.hio.rub.de 1025
```

---

Wenn die Verbindung fehlschlägt prüfen wir zunächst ob eine *Outbound* Regel in der Firewall geschaltet ist.

```bash (uid:0)
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

```bash (uid:0)
sudo iptables -A OUTPUT -p tcp -d sosmig-web.hio.rub.de --dport 1025 -j ACCEPT
sudo ip6tables -A OUTPUT -p tcp -d sosmig-web.hio.rub.de --dport 1025 -j ACCEPT
```

---

Jetzt können wir den Verbindungsaufbau via Telnet (siehe Oben) erneut ausführen um zu sehen ob es funktioniert. Falls nicht fehlt vermutlich noch die Regel auf Seite des _Webservers_. Diese legen wir nun an:

```bash (uid:0)
echo "IPV4 Outbound (filtered for sosmig-app):"
sudo iptables -L INPUT | grep sosmig-app 
echo "IPV6 Outbound (filtered for sosmig-app):"
sudo ip6tables -L INPUT | grep sosmig-app
```

```text


IPV4 Outbound (filtered for sosmig-app):


ACCEPT     tcp  --  sosmig-app.hio.ruhr-uni-bochum.de  anywhere             tcp dpt:1025
ACCEPT     tcp  --  sosmig-app.hio.ruhr-uni-bochum.de  anywhere             tcp dpt:1025


IPV6 Outbound (filtered for sosmig-app):


ACCEPT     tcp  --  sosmig-app.hio.ruhr-uni-bochum.de  anywhere             tcp dpt:1025
```

```bash (uid:0)
sudo iptables -A INPUT -p tcp -s sosmig-app.hio.rub.de --dport 1025 -j ACCEPT
sudo ip6tables -A INPUT -p tcp -s sosmig-app.hio.rub.de --dport 1025 -j ACCEPT
```

---

Ein erneuter Test kann nun erfolgen (wieder via telnet). Wenn wir ein Connection Refused aber kein Timeout erhalten , scheint eine Verbindung mölich zu sein es lauscht nur keiner am anderen Ende. Wir nehmen nun netcat um das zu ändern und final die Verbindung zu verifizieren:

```bash (uid:0)
sudo apt install netcat-openbsd -y
```

Wir starten Netcat auf Port 1025, damit am anderen Ende jemand *abnimmt* um die Verbindung zu testen:

```bash (uid:0)
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

```bash (uid:0)
sudo vim /etc/systemd/system/mailhog.service
```

Mailhog verwendet eine .env Datei für die Konfiguration, hier schalten wir die Authentifizierung ein. Diese Konfigurationsdatei wird in der Servicedatei oben angegeben unter *EnviromentFile*. Zunächst muss das Arbeitsverzeichnis für die Mailhog Binary und die Konfiguration angelegt werden. Danach können wir die Konfiguration anlegen:

```bash (uid:0)
sudo mkdir -p /opt/mailhog
```

```bash (uid:0)
sudo vim /opt/mailhog/.env
```

Wenn wir alle Dateien angelegt haben, können wir den Service aktivieren und den Servicedaemon reloaden damit der neue Service verfügbar ist:

```bash (uid:0)
sudo systemctl enable mailhog
```

```bash (uid:0)
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

```bash (uid:0)
sudo mv /tmp/MailHog /opt/mailhog/MailHog
```

> Hinweis: Wir haben keine Berechtigung auf Opt zu schreiben also müssen wir die Datei in tmp zwischenspeichern und dann verschieben via sudo. Bitte auf die Gross- / Kleinschreibung der Binary achten, diese muss mit der in der Servicedatei übereinstimmen!

Jetzt können wir den Mailhog final starten:

```bash (uid:0)
sudo systemctl start mailhog && sudo systemctl status mailhog
```

---

Sollten beim Starten Fehlerauftreten, schauen wir in das Journal des Mailhog Service mit folgendem Befehl (ich empfehle diesen in einer weiter remote pty zu starten, dann kann diese in Echtzeit beim Start eingesehen werden):

```bash (uid:2)
sudo journalctl -u mailhog
```

```text

=May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed to load environment files: No>
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed to spawn 'start' task: No suc>
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed with result 'resources'.
May 29 15:56:04 sosmig-web systemd[1]: Failed to start mailhog.service - Mailtrap via MailHo>
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Scheduled restart job, restart count>
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed to load environment files: No>
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed to spawn 'start' task: No suc>
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed with result 'resources'.
May 29 15:56:04 sosmig-web systemd[1]: Failed to start mailhog.service - Mailtrap via MailHo>
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Scheduled restart job, restart count>
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed to load environment files: No>
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed to spawn 'start' task: No suc>
May 29 15:56:04 sosmig-web systemd[1]: mailhog.service: Failed with result 'resources'.
May 29 15:56:04 sosmig-web systemd[1]: Failed to start mailhog.service - Mailtrap via MailHo>
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Scheduled restart job, restart count>
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Failed to load environment files: No>
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Failed to spawn 'start' task: No suc>
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Failed with result 'resources'.
May 29 15:56:05 sosmig-web systemd[1]: Failed to start mailhog.service - Mailtrap via MailHo>
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Scheduled restart job, restart count>
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Failed to load environment files: No>
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Failed to spawn 'start' task: No suc>
May 29 15:56:05 sosmig-web systemd[1]: mailhog.service: Failed with result 'resources'.
lines 1-23...skipping...
Jun 02 10:31:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:32:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:33:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:34:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:35:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:36:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:37:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:38:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:39:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:40:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:41:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:42:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:43:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:44:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:45:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:46:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:47:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:48:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:49:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:50:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:51:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:52:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:53:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 283-305/305 (END) ESCESCOOAAJun 02 10:30:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 282-304/305 100% ESCESCOOAAJun 02 10:29:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 281-303/305 100% ESCESCOOAAJun 02 10:28:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 280-302/305 99% ESCESCOOAAJun 02 10:27:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 279-301/305 99% ESCESCOOAAJun 02 10:26:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 278-300/305 99% ESCESCOOAAJun 02 10:25:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 277-299/305 99% ESCESCOOAAJun 02 10:24:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 276-298/305 98% ESCESCOOAAJun 02 10:23:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 275-297/305 98% ESCESCOOAAJun 02 10:22:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 274-296/305 98% ESCESCOOAAJun 02 10:21:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 273-295/305 98% ESCESCOOAAJun 02 10:20:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 272-294/305 98% ESCESCOOAAJun 02 10:19:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 271-293/305 97% ESCESCOOAAJun 02 10:18:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 270-292/305 97% ESCESCOOAAJun 02 10:17:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 269-291/305 97% ESCESCOOAAJun 02 10:16:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 268-290/305 97% ESCESCOOAAJun 02 10:15:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 267-289/305 96% ESCESCOOAAJun 02 10:14:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 266-288/305 96% ESCESCOOAAJun 02 10:13:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 265-287/305 96% ESCESCOOAAJun 02 10:12:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 264-286/305 96% ESCESCOOAAJun 02 10:11:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 263-285/305 95% ESCESCOOAAJun 02 10:10:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 262-284/305 95% ESCESCOOAAJun 02 10:09:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 261-283/305 95% ESCESCOOAAJun 02 10:08:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 260-282/305 95% ESCESCOOAAJun 02 10:07:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 259-281/305 95% ESCESCOOAAJun 02 10:06:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 258-280/305 94% ESCESCOOAAJun 02 10:05:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 257-279/305 94% ESCESCOOAAJun 02 10:04:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 256-278/305 94% ESCESCOOAAJun 02 10:03:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 255-277/305 94% ESCESCOOAAJun 02 10:02:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 254-276/305 93% ESCESCOOAAJun 02 10:01:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 253-275/305 93% ESCESCOOAAJun 02 10:00:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 252-274/305 93% ESCESCOOAAJun 02 09:59:53 sosmig-web mailhog[4120609]: 2026/06/02 09:59:53 [SMTP [2a05:3e00:1:1025:10:>
lines 251-273/305 93% ESCESCOOAAJun 02 09:59:53 sosmig-web mailhog[4120609]: 2026/06/02 09:59:53 [SMTP [2a05:3e00:1:1025:10:>
lines 250-272/305 93% ESCESCOOAAJun 02 09:59:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 249-271/305 92% ESCESCOOAAJun 02 09:58:36 sosmig-web mailhog[4120609]: 2026/06/02 09:58:36 [SMTP [2a05:3e00:1:1025:10:>
lines 248-270/305 92% ESCESCOOAAJun 02 09:58:36 sosmig-web mailhog[4120609]: 2026/06/02 09:58:36 [SMTP [2a05:3e00:1:1025:10:>
lines 247-269/305 92% ESCESCOOAAJun 02 09:58:36 sosmig-web mailhog[4120609]: 2026/06/02 09:58:36 [SMTP [2a05:3e00:1:1025:10:>
lines 246-268/305 92% ESCESCOOAAJun 02 09:58:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 245-267/305 91% ESCESCOOAAJun 02 09:58:12 sosmig-web mailhog[4120609]: 2026/06/02 09:58:12 [SMTP [2a05:3e00:1:1025:10:>
lines 244-266/305 91% ESCESCOOAAJun 02 09:58:12 sosmig-web mailhog[4120609]: 2026/06/02 09:58:12 [SMTP [2a05:3e00:1:1025:10:>
lines 243-265/305 91% ESCESCOOAAJun 02 09:57:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 242-264/305 91% ESCESCOOAAJun 02 09:56:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 241-263/305 90% ESCESCOOAAJun 02 09:55:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 240-262/305 90% ESCESCOOAAJun 02 09:54:40 sosmig-web mailhog[4120609]: 2026/06/02 09:54:40 [SMTP [2a05:3e00:1:1025:10:>
lines 239-261/305 90% ESCESCOOAAJun 02 09:54:40 sosmig-web mailhog[4120609]: 2026/06/02 09:54:40 [SMTP [2a05:3e00:1:1025:10:>
lines 238-260/305 90% ESCESCOOAAJun 02 09:54:40 sosmig-web mailhog[4120609]: 2026/06/02 09:54:40 [SMTP [2a05:3e00:1:1025:10:>
lines 237-259/305 90% ESCESCOOAAJun 02 09:54:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 236-258/305 89% ESCESCOOAAJun 02 09:53:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 235-257/305 89% ESCESCOOAAJun 02 09:52:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 234-256/305 89% ESCESCOOAAJun 02 09:51:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 233-255/305 89% ESCESCOOAAJun 02 09:50:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 232-254/305 88% ESCESCOOAAJun 02 09:49:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 231-253/305 88% ESCESCOOAAJun 02 09:48:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 230-252/305 88% ESCESCOOAAJun 02 09:47:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 229-251/305 88% ESCESCOOAAJun 02 09:46:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 228-250/305 87% ESCESCOOAAJun 02 09:45:24 sosmig-web mailhog[4120609]: Creating API v2 with WebPath:
lines 227-249/305 87% ESCESCOOAAJun 02 09:45:24 sosmig-web mailhog[4120609]: Creating API v1 with WebPath:
lines 226-248/305 87% ESCESCOOAAJun 02 09:45:24 sosmig-web mailhog[4120609]: 2026/06/02 09:45:24 Serving under http://0.0.0.>
lines 225-247/305 86% ESCESCOOAAJun 02 09:45:24 sosmig-web mailhog[4120609]: [HTTP] Binding to address: 0.0.0.0:8025
lines 224-246/305 86% ESCESCOOAAJun 02 09:45:24 sosmig-web mailhog[4120609]: 2026/06/02 09:45:24 [SMTP] Binding to address: >
lines 223-245/305 85% ESCESCOOAAJun 02 09:45:24 sosmig-web mailhog[4120609]: 2026/06/02 09:45:24 Using in-memory storage
lines 222-244/305 85% ESCESCOOAAJun 02 09:45:24 sosmig-web systemd[1]: Started mailhog.service - Mailtrap via MailHog for Hi>
lines 221-243/305 85% ESCESCOOAAJun 02 09:37:04 sosmig-web systemd[1]: Failed to start mailhog.service - Mailtrap via MailHo>
lines 220-242/305 84% ESCESCOOAAJun 02 09:37:04 sosmig-web systemd[1]: mailhog.service: Failed with result 'exit-code'.
lines 219-241/305 84% ESCESCOOAAJun 02 09:37:04 sosmig-web systemd[1]: mailhog.service: Start request repeated too quickly.
lines 218-240/305 84% ESCESCOOAAJun 02 09:37:04 sosmig-web systemd[1]: mailhog.service: Scheduled restart job, restart count>
lines 217-239/305 84% ESCESCOOAAJun 02 09:37:04 sosmig-web systemd[1]: mailhog.service: Failed with result 'exit-code'.
lines 216-238/305 83% ESCESCOOAAJun 02 09:37:04 sosmig-web systemd[1]: mailhog.service: Main process exited, code=exited, st>
lines 215-237/305 83% ESCESCOOAAJun 02 09:37:04 sosmig-web systemd[1]: Started mailhog.service - Mailtrap via MailHog for Hi>
lines 214-236/305 82% ESCESCOOBBJun 02 09:54:40 sosmig-web mailhog[4120609]: 2026/06/02 09:54:40 [SMTP [2a05:3e00:1:1025:10:>
lines 215-237/305 83% ESCESCOOBBJun 02 09:54:40 sosmig-web mailhog[4120609]: 2026/06/02 09:54:40 [SMTP [2a05:3e00:1:1025:10:>
lines 216-238/305 83% ESCESCOOBBJun 02 09:54:40 sosmig-web mailhog[4120609]: 2026/06/02 09:54:40 [SMTP [2a05:3e00:1:1025:10:>
lines 217-239/305 84% ESCESCOOBBJun 02 09:55:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 218-240/305 84% ESCESCOOBBJun 02 09:56:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 219-241/305 84% ESCESCOOBBJun 02 09:57:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 220-242/305 84% ESCESCOOBBJun 02 09:58:12 sosmig-web mailhog[4120609]: 2026/06/02 09:58:12 [SMTP [2a05:3e00:1:1025:10:>
lines 221-243/305 85% ESCESCOOBBJun 02 09:58:12 sosmig-web mailhog[4120609]: 2026/06/02 09:58:12 [SMTP [2a05:3e00:1:1025:10:>
lines 222-244/305 85% ESCESCOOBBJun 02 09:58:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 223-245/305 85%...skipping...
Jun 02 10:31:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:32:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:33:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:34:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:35:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:36:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:37:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:38:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:39:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:40:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:41:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:42:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:43:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:44:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:45:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:46:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:47:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:48:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:49:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:50:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:51:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:52:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:53:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
lines 283-305/305 (END)>
```

Es scheint so als gäbe es ein Problem bei der Ausführung. Dies könnte ein Berechtigungsproblem sein, also sehen wir uns diese an:

```bash (uid:0)
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

```bash (uid:0)
sudo chown root:root /opt/mailhog/MailHog
```

```bash (uid:0)
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

```bash (uid:0)
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

```text

="/etc/rsyslog.d/mailhog.conf" 4L, 105B▽  zz           10;?11;?  1 if $programname == 'mailhog' then {
  2   action(type="omfile" file="/var/log/mailhog/logfile.log")  3   stop  4 }
~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ::q>
```

Nun müssen wir noch die Berechtigungen anpassen und den Dienst rsyslog neustarten:

```bash (uid:2)
sudo chown -R syslog:adm /var/log/mailhog
```

```bash (uid:2)
ls -la /var/log/mailhog
```

```text

total 8
drwxr-xr-x  2 syslog adm    4096 Jun  2 10:08 .
drwxrwxr-x 13 root   syslog 4096 Jun  2 10:24 ..
```

```bash (uid:2)
sudo systemctl enable rsyslog.service
```

Wenn rsyslog nicht installiert ist (das kann auf neueren Ubuntu Versionen der Fall sein), installieren wir es einfach nach:

```bash (uid:0)
sudo apt install rsyslog -y
```

```text



Reading package lists... 0%

Reading package lists... 100%

Reading package lists... Done


Building dependency tree... 0%

Building dependency tree... 0%

Building dependency tree... 50%

Building dependency tree... 50%

Building dependency tree... Done


Reading state information... 0% 

Reading state information... 0%

Reading state information... Done

The following additional packages will be installed:
  libestr0 libfastjson4
Suggested packages:
  rsyslog-mysql | rsyslog-pgsql rsyslog-mongodb rsyslog-doc rsyslog-openssl
  | rsyslog-gnutls rsyslog-gssapi rsyslog-relp
The following NEW packages will be installed:
  libestr0 libfastjson4 rsyslog
0 upgraded, 3 newly installed, 0 to remove and 0 not upgraded.
Need to get 542 kB of archives.
After this operation, 1922 kB of additional disk space will be used.

0% [Working]
            
Get:1 https://linux.ruhr-uni-bochum.de/ubuntu noble/main amd64 libestr0 amd64 0.1.11-1build1 [7802 B]

1% [1 libestr0 7802 B/7802 B 100%]
                                  
8% [Working]
            
Get:2 https://linux.ruhr-uni-bochum.de/ubuntu noble/main amd64 libfastjson4 amd64 1.2304.0-1build1 [23.1 kB]

10% [2 libfastjson4 16.4 kB/23.1 kB 71%]
                                        
18% [Working]
             
Get:3 https://linux.ruhr-uni-bochum.de/ubuntu noble-updates/main amd64 rsyslog amd64 8.2312.0-3ubuntu9.2 [511 kB]

20% [3 rsyslog 16.4 kB/511 kB 3%]
                                 
100% [Working]
              
Fetched 542 kB in 0s (9392 kB/s)

78Selecting previously unselected package libestr0:amd64.
(Reading database ... 
(Reading database ... 5%
(Reading database ... 10%
(Reading database ... 15%
(Reading database ... 20%
(Reading database ... 25%
(Reading database ... 30%
(Reading database ... 35%
(Reading database ... 40%
(Reading database ... 45%
(Reading database ... 50%
(Reading database ... 55%
(Reading database ... 60%
(Reading database ... 65%
(Reading database ... 70%
(Reading database ... 75%
(Reading database ... 80%
(Reading database ... 85%
(Reading database ... 90%
(Reading database ... 95%
(Reading database ... 100%
(Reading database ... 126183 files and directories currently installed.)
Preparing to unpack .../libestr0_0.1.11-1build1_amd64.deb ...
7Progress: [  0%] [.......................................................................] 87Progress: [  8%] [#####..................................................................] 8Unpacking libestr0:amd64 (0.1.11-1build1) ...
7Progress: [ 15%] [##########.............................................................] 8Selecting previously unselected package libfastjson4:amd64.
Preparing to unpack .../libfastjson4_1.2304.0-1build1_amd64.deb ...
7Progress: [ 23%] [################.......................................................] 8Unpacking libfastjson4:amd64 (1.2304.0-1build1) ...
7Progress: [ 31%] [#####################..................................................] 8Selecting previously unselected package rsyslog.
Preparing to unpack .../rsyslog_8.2312.0-3ubuntu9.2_amd64.deb ...
7Progress: [ 38%] [###########################............................................] 8Unpacking rsyslog (8.2312.0-3ubuntu9.2) ...
7Progress: [ 46%] [################################.......................................] 8Setting up libestr0:amd64 (0.1.11-1build1) ...
7Progress: [ 54%] [######################################.................................] 87Progress: [ 62%] [###########################################............................] 8Setting up libfastjson4:amd64 (1.2304.0-1build1) ...
7Progress: [ 69%] [#################################################......................] 87Progress: [ 77%] [######################################################.................] 8Setting up rsyslog (8.2312.0-3ubuntu9.2) ...
7Progress: [ 85%] [############################################################...........] 8info: Adding user `syslog' to group `adm' ...

Creating config file /etc/rsyslog.d/50-default.conf with new version
Created symlink /etc/systemd/system/multi-user.target.wants/dmesg.service → /usr/lib/systemd/system/dmesg.service.

Created symlink /etc/systemd/system/syslog.service → /usr/lib/systemd/system/rsyslog.service.

Created symlink /etc/systemd/system/multi-user.target.wants/rsyslog.service → /usr/lib/systemd/system/rsyslog.service.

7Progress: [ 92%] [#################################################################......] 8Processing triggers for libc-bin (2.39-0ubuntu8.7) ...
Processing triggers for man-db (2.12.0-4build2) ...

78Disabling Ubuntu mode, explicit restart mode configuredScanning processes... [                                                                     ]
Scanning processes... [                                                                     ]
Scanning processes... [                                                                     ]
Scanning processes... [                                                                     ]
Scanning processes... [                                                                     ]
Scanning processes... [=                                                                    ]
Scanning processes... [=                                                                    ]
Scanning processes... [=                                                                    ]
Scanning processes... [=                                                                    ]
Scanning processes... [==                                                                   ]
Scanning processes... [==                                                                   ]
Scanning processes... [==                                                                   ]
Scanning processes... [==                                                                   ]
Scanning processes... [===                                                                  ]
Scanning processes... [===                                                                  ]
Scanning processes... [===                                                                  ]
Scanning processes... [===                                                                  ]
Scanning processes... [====                                                                 ]
Scanning processes... [====                                                                 ]
Scanning processes... [====                                                                 ]
Scanning processes... [====                                                                 ]
Scanning processes... [=====                                                                ]
Scanning processes... [=====                                                                ]
Scanning processes... [=====                                                                ]
Scanning processes... [=====                                                                ]
Scanning processes... [======                                                               ]
Scanning processes... [======                                                               ]
Scanning processes... [======                                                               ]
Scanning processes... [======                                                               ]
Scanning processes... [=======                                                              ]
Scanning processes... [=======                                                              ]
Scanning processes... [=======                                                              ]
Scanning processes... [=======                                                              ]
Scanning processes... [=======                                                              ]
Scanning processes... [========                                                             ]
Scanning processes... [========                                                             ]
Scanning processes... [========                                                             ]
Scanning processes... [========                                                             ]
Scanning processes... [=========                                                            ]
Scanning processes... [=========                                                            ]
Scanning processes... [=========                                                            ]
Scanning processes... [=========                                                            ]
Scanning processes... [==========                                                           ]
Scanning processes... [==========                                                           ]
Scanning processes... [==========                                                           ]
Scanning processes... [==========                                                           ]
Scanning processes... [===========                                                          ]
Scanning processes... [===========                                                          ]
Scanning processes... [===========                                                          ]
Scanning processes... [===========                                                          ]
Scanning processes... [============                                                         ]
Scanning processes... [============                                                         ]
Scanning processes... [============                                                         ]
Scanning processes... [============                                                         ]
Scanning processes... [=============                                                        ]
Scanning processes... [=============                                                        ]
Scanning processes... [=============                                                        ]
Scanning processes... [=============                                                        ]
Scanning processes... [==============                                                       ]
Scanning processes... [==============                                                       ]
Scanning processes... [==============                                                       ]
Scanning processes... [==============                                                       ]
Scanning processes... [===============                                                      ]
Scanning processes... [===============                                                      ]
Scanning processes... [===============                                                      ]
Scanning processes... [===============                                                      ]
Scanning processes... [===============                                                      ]
Scanning processes... [================                                                     ]
Scanning processes... [================                                                     ]
Scanning processes... [================                                                     ]
Scanning processes... [================                                                     ]
Scanning processes... [=================                                                    ]
Scanning processes... [=================                                                    ]
Scanning processes... [=================                                                    ]
Scanning processes... [=================                                                    ]
Scanning processes... [==================                                                   ]
Scanning processes... [==================                                                   ]
Scanning processes... [==================                                                   ]
Scanning processes... [==================                                                   ]
Scanning processes... [===================                                                  ]
Scanning processes... [===================                                                  ]
Scanning processes... [===================                                                  ]
Scanning processes... [===================                                                  ]
Scanning processes... [====================                                                 ]
Scanning processes... [====================                                                 ]
Scanning processes... [====================                                                 ]
Scanning processes... [====================                                                 ]
Scanning processes... [=====================                                                ]
Scanning processes... [=====================                                                ]
Scanning processes... [=====================                                                ]
Scanning processes... [=====================                                                ]
Scanning processes... [======================                                               ]
Scanning processes... [======================                                               ]
Scanning processes... [======================                                               ]
Scanning processes... [======================                                               ]
Scanning processes... [=======================                                              ]
Scanning processes... [=======================                                              ]
Scanning processes... [=======================                                              ]
Scanning processes... [=======================                                              ]
Scanning processes... [=======================                                              ]
Scanning processes... [========================                                             ]
Scanning processes... [========================                                             ]
Scanning processes... [========================                                             ]
Scanning processes... [========================                                             ]
Scanning processes... [=========================                                            ]
Scanning processes... [=========================                                            ]
Scanning processes... [=========================                                            ]
Scanning processes... [=========================                                            ]
Scanning processes... [==========================                                           ]
Scanning processes... [==========================                                           ]
Scanning processes... [==========================                                           ]
Scanning processes... [==========================                                           ]
Scanning processes... [===========================                                          ]
Scanning processes... [===========================                                          ]
Scanning processes... [===========================                                          ]
Scanning processes... [===========================                                          ]
Scanning processes... [============================                                         ]
Scanning processes... [============================                                         ]
Scanning processes... [============================                                         ]
Scanning processes... [============================                                         ]
Scanning processes... [=============================                                        ]
Scanning processes... [=============================                                        ]
Scanning processes... [=============================                                        ]
Scanning processes... [=============================                                        ]
Scanning processes... [==============================                                       ]
Scanning processes... [==============================                                       ]
Scanning processes... [==============================                                       ]
Scanning processes... [==============================                                       ]
Scanning processes... [==============================                                       ]
Scanning processes... [===============================                                      ]
Scanning processes... [===============================                                      ]
Scanning processes... [===============================                                      ]
Scanning processes... [===============================                                      ]
Scanning processes... [================================                                     ]
Scanning processes... [================================                                     ]
Scanning processes... [================================                                     ]
Scanning processes... [================================                                     ]
Scanning processes... [=================================                                    ]
Scanning processes... [=================================                                    ]
Scanning processes... [=================================                                    ]
Scanning processes... [=================================                                    ]
Scanning processes... [==================================                                   ]
Scanning processes... [==================================                                   ]
Scanning processes... [==================================                                   ]
Scanning processes... [==================================                                   ]
Scanning processes... [===================================                                  ]
Scanning processes... [===================================                                  ]
Scanning processes... [===================================                                  ]
Scanning processes... [===================================                                  ]
Scanning processes... [====================================                                 ]
Scanning processes... [====================================                                 ]
Scanning processes... [====================================                                 ]
Scanning processes... [====================================                                 ]
Scanning processes... [=====================================                                ]
Scanning processes... [=====================================                                ]
Scanning processes... [=====================================                                ]
Scanning processes... [=====================================                                ]
Scanning processes... [======================================                               ]
Scanning processes... [======================================                               ]
Scanning processes... [======================================                               ]
Scanning processes... [======================================                               ]
Scanning processes... [======================================                               ]
Scanning processes... [=======================================                              ]
Scanning processes... [=======================================                              ]
Scanning processes... [=======================================                              ]
Scanning processes... [=======================================                              ]
Scanning processes... [========================================                             ]
Scanning processes... [========================================                             ]
Scanning processes... [========================================                             ]
Scanning processes... [========================================                             ]
Scanning processes... [=========================================                            ]
Scanning processes... [=========================================                            ]
Scanning processes... [=========================================                            ]
Scanning processes... [=========================================                            ]
Scanning processes... [==========================================                           ]
Scanning processes... [==========================================                           ]
Scanning processes... [==========================================                           ]
Scanning processes... [==========================================                           ]
Scanning processes... [===========================================                          ]
Scanning processes... [===========================================                          ]
Scanning processes... [===========================================                          ]
Scanning processes... [===========================================                          ]
Scanning processes... [============================================                         ]
Scanning processes... [============================================                         ]
Scanning processes... [============================================                         ]
Scanning processes... [============================================                         ]
Scanning processes... [=============================================                        ]
Scanning processes... [=============================================                        ]
Scanning processes... [=============================================                        ]
Scanning processes... [=============================================                        ]
Scanning processes... [==============================================                       ]
Scanning processes... [==============================================                       ]
Scanning processes... [==============================================                       ]
Scanning processes... [==============================================                       ]
Scanning processes... [==============================================                       ]
Scanning processes... [===============================================                      ]
Scanning processes... [===============================================                      ]
Scanning processes... [===============================================                      ]
Scanning processes... [===============================================                      ]
Scanning processes... [================================================                     ]
Scanning processes... [================================================                     ]
Scanning processes... [================================================                     ]
Scanning processes... [================================================                     ]
Scanning processes... [=================================================                    ]
Scanning processes... [=================================================                    ]
Scanning processes... [=================================================                    ]
Scanning processes... [=================================================                    ]
Scanning processes... [==================================================                   ]
Scanning processes... [==================================================                   ]
Scanning processes... [==================================================                   ]
Scanning processes... [==================================================                   ]
Scanning processes... [===================================================                  ]
Scanning processes... [===================================================                  ]
Scanning processes... [===================================================                  ]
Scanning processes... [===================================================                  ]
Scanning processes... [====================================================                 ]
Scanning processes... [====================================================                 ]
Scanning processes... [====================================================                 ]
Scanning processes... [====================================================                 ]
Scanning processes... [=====================================================                ]
Scanning processes... [=====================================================                ]
Scanning processes... [=====================================================                ]
Scanning processes... [=====================================================                ]
Scanning processes... [=====================================================                ]
Scanning processes... [======================================================               ]
Scanning processes... [======================================================               ]
Scanning processes... [======================================================               ]
Scanning processes... [======================================================               ]
Scanning processes... [=======================================================              ]
Scanning processes... [=======================================================              ]
Scanning processes... [=======================================================              ]
Scanning processes... [=======================================================              ]
Scanning processes... [========================================================             ]
Scanning processes... [========================================================             ]
Scanning processes... [========================================================             ]
Scanning processes... [========================================================             ]
Scanning processes... [=========================================================            ]
Scanning processes... [=========================================================            ]
Scanning processes... [=========================================================            ]
Scanning processes... [=========================================================            ]
Scanning processes... [==========================================================           ]
Scanning processes... [==========================================================           ]
Scanning processes... [==========================================================           ]
Scanning processes... [==========================================================           ]
Scanning processes... [===========================================================          ]
Scanning processes... [===========================================================          ]
Scanning processes... [===========================================================          ]
Scanning processes... [===========================================================          ]
Scanning processes... [============================================================         ]
Scanning processes... [============================================================         ]
Scanning processes... [============================================================         ]
Scanning processes... [============================================================         ]
Scanning processes... [=============================================================        ]
Scanning processes... [=============================================================        ]
Scanning processes... [=============================================================        ]
Scanning processes... [=============================================================        ]
Scanning processes... [=============================================================        ]
Scanning processes... [==============================================================       ]
Scanning processes... [==============================================================       ]
Scanning processes... [==============================================================       ]
Scanning processes... [==============================================================       ]
Scanning processes... [===============================================================      ]
Scanning processes... [===============================================================      ]
Scanning processes... [===============================================================      ]
Scanning processes... [===============================================================      ]
Scanning processes... [================================================================     ]
Scanning processes... [================================================================     ]
Scanning processes... [================================================================     ]
Scanning processes... [================================================================     ]
Scanning processes... [=================================================================    ]
Scanning processes... [=================================================================    ]
Scanning processes... [=================================================================    ]
Scanning processes... [=================================================================    ]
Scanning processes... [==================================================================   ]
Scanning processes... [==================================================================   ]
Scanning processes... [==================================================================   ]
Scanning processes... [==================================================================   ]
Scanning processes... [===================================================================  ]
Scanning processes... [===================================================================  ]
Scanning processes... [===================================================================  ]
Scanning processes... [===================================================================  ]
Scanning processes... [==================================================================== ]
Scanning processes... [==================================================================== ]
Scanning processes... [==================================================================== ]
Scanning processes... [==================================================================== ]
Scanning processes... [=====================================================================]
Scanning processes...                                                                        
Scanning candidates... [                                                                    ]
Scanning candidates... [===========                                                         ]
Scanning candidates... [======================                                              ]
Scanning candidates... [==================================                                  ]
Scanning candidates... [=============================================                       ]
Scanning candidates... [========================================================            ]
Scanning candidates... [====================================================================]
Scanning candidates...                                                                       
Scanning linux images... [                                                                  ]
Scanning linux images... [================                                                  ]
Scanning linux images... [=================================                                 ]
Scanning linux images... [=================================================                 ]
Scanning linux images... [==================================================================]
Scanning linux images...                                                                     

The currently running kernel version is 6.8.0-107-generic which is not the expected kernel
 version 6.8.0-124-generic.

Restarting services...

Service restarts being deferred:
 systemctl restart NetworkManager.service
 /etc/needrestart/restart.d/dbus.service
 systemctl restart networkd-dispatcher.service
 systemctl restart systemd-logind.service
 systemctl restart unattended-upgrades.service
 systemctl restart wpa_supplicant.service

No containers need to be restarted.

No user sessions are running outdated binaries.

No VM guests are running outdated hypervisor (qemu) binaries on this host.
```

```bash (uid:2)
sudo tail -F /var/log/mailhog/logfile.log
```

```text

2026-06-02T10:40:24.426341+02:00 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
2026-06-02T10:41:24.426427+02:00 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
2026-06-02T10:42:24.426380+02:00 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
2026-06-02T10:43:24.426461+02:00 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
2026-06-02T10:44:24.426349+02:00 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
2026-06-02T10:45:24.426420+02:00 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
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

```text

="/etc/logrotate.d/mailhog" 9L, 142B▽  zz           10;?11;?  1 singok
  2     notifempty  3     compress  4     delaycompress
  5     sharedscripts
  6     postrotate
  7 /usr/lib/rsyslog/rsyslog-rotate
  8     endscript
  9 }
~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            g gg  v1-- VISUAL --1G9singok     notifempty     compress     delaycompress     sharedscripts     postrotate         /usr/lib/rsyslog/rsyslog-rotate     endscript ~@k9  }~@k9  x8 fewer lines~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            i -- INSERT (paste) --/var/log/blubbi.log {
  2     daily  3     rotate 7  4     missingok  5     notifempty  6     compress  7     delaycompress  8     sharedscripts  9     postrotate 10         /usr/lib/rsyslog/rsyslog-rotate 11     endscript 12 }{}var/log/mblubbi.log {ablubbi.log {iblubbi.log {lblubbi.log {hblubbi.log {oblubbi.log {gblubbi.log {/blubbi.log {lblubbi.log {oblubbi.log {gblubbi.log {fblubbi.log {iblubbi.log {lblubbi.log {eblubbi.log {.blubbi.log {lblubbi.log {oblubbi.log {gblubbi.log {blubbi.log^? {^? {^? {lubbi.log^?^?^? {ubbi.log^?^?^? {bbi.log^?^?^? {bi.log^?^?^? {i.log^?^?^? {.log^?^?^? {log^?^?^? {og^?^?^? {g^?^?^? {^?^?^? { { { {^[  ::w"/etc/logrotate.d/mailhog" 12L, 203B written::q>
```

```bash (uid:2)
sudo ls /etc/logrotate.d/
```

```text

alternatives  apport  aptitude	btmp	dpkg	  mailhog  rsyslog     unattended-upgrades
apache2       apt     bootlog	chrony	firewall  ppp	   sane-utils  wtmp
```

Ein kurzer Testaufruf des logrotate zeigt ob die Konfiguration so passt (ist eine Trockenübung und führt keine persistenten Änderungen auf dem Dateisystem durch):

```bash (uid:2)
sudo logrotate -d /etc/logrotate.d/mailhog
```

```text

warning: logrotate in debug mode does nothing except printing debug messages!  Consider using verbose mode (-v) instead if this is not what you want.

reading config file /etc/logrotate.d/mailhog
Reading state from file: /var/lib/logrotate/status
Allocating hash table for state file, size 64 entries
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state
Creating new state

Handling 1 logs

rotating pattern: /var/log/mailhog/logfile.log  after 1 days (7 rotations)
empty log files are not rotated, old logs are removed
considering log /var/log/mailhog/logfile.log
Creating new state
  Now: 2026-06-02 10:49
  Last rotated at 2026-06-02 10:00
  log does not need rotating (log has already been rotated)
not running postrotate script, since no logs were rotated
```

---

Nun können wir testweise die WebUI vom MailHog aufrufen, dazu müssen wir via ssh den remote Port auf einen lokalen tunneln:
> Hinweis: Das machen wir am besten in einer neuen lokalen ptty damit wir unsere default pty nicht blockieren -> !!local<return>:

```bash (uid:3)
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

```text

=<ib/tomcat10/webapps/qisserver/WEB-INF/conf/DispatcherProperties_rub-sosmig.txt"<0/webapps/qisserver/WEB-INF/conf/DispatcherProperties_rub-sosmig.txt" 38L, 1601B▽  zz           10;?11;?  1 # ================================================================ #
  2 #                   DispatcherProperties                           #  3 #                                                                  #  4 # Diese Datei wurde initial vom HIS Web-Setup-Assistenten erzeugt. #
  5 # Sie können diese Datei auch weiter für Ihre eigenen Ein-#
  6 # stellungen nutzen. Diese Datei wird nur durch ein erneutes Aus-  #
  7 # führen des Web-Setup-Assistenten überschrieben.#
  8 # Nehmen Sie Änderungen niemals in der ausgelieferten Original-    #
  9 # datei vor. Nutzen Sie immer ein Spezialmodul, bspw. dieses!      #
 10 # ================================================================ #
 11 
 12 
 13 # Produktbereiche: Bitte wählen Sie die Produktbereiche aus, die Sie verwenden möchten. DD    er HISinOne-Kern wird immer installiert. Achten Sie auch hier auf Ihre Lizenzen.
 14 MODULES=core,HISINONE,HISINONEPSV,HISINONEAPP,HISINONESTU,HISINONEEXA,DOSV,EDUSTORE,HISINN    ONEBIA
 15 
 16 # Architektur Säule: Entsprechend Ihrer Einstellungen werden die entsprechenden Spezialmoo    dule in der SPEZIALMODULE.txt aktiviert und die passenden Konfigurationen geladen.
 17 OPERATION_MODE=cust
 18 
 19 CLUSTER_NAME=RUBCUST
 20 ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   
 21 SHOW_DEBUGPANEL=Y~@k   
 22 ~@k   
 23 HISINONESTYLE_NAME=HISinOne_rub.css~@k   
 24 ~@k   
 25 # Request Performance Statistik~@k   
 26 #REQUEST_STATISTICS=Y~@k   
 27 #REQUEST_STATISTICS_TARGET=Logger~@k   
 28 ~@k   
 29 HEALTH_CHECK_URL=Y~@k   
 30 ~@k   
 31 # Upload Dateigröße anpassen gemäßKIDB Anfrage 162872 für HotFixes (gvg)~@k   
 32 MAX_UPLOAD_SIZE=25m~@k    33 
 34 # Mailserver auf Mailhog verweisen (Überschreiben rub variante)~@k   ~@k    35 MAIL_SERVER=sosmig-web.hio.ruhr-uni-bochum.de
 36 ~@k   ~@k   
 37 # Mail-Port MailHog~@k    38 MAIL_SERVER_PORT=1025
~                                                                                            ~@k   ~@k   ~@k   ~@k   ~@k   Tippe:  :qa  und drücke <Enter> um Vim zu beenden^[  ::w<ib/tomcat10/webapps/qisserver/WEB-INF/conf/DispatcherProperties_rub-sosmig.txt"<sserver/WEB-INF/conf/DispatcherProperties_rub-sosmig.txt" 38L, 1601B geschrieben::q>
```

Sollten wir die Dispatcherproperties angepasst haben ist noch ein neustart des Tomcat notwendig. Ansonsten ist nun alles konfiguriert und kann getestet werden.
