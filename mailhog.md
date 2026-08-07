# Shell Notebook Export - 2026-06-01 13:27:03

Zuächst testen wir mit Telnet ob eine Verbindung auf den Port von MailHog auf vom Appserver zum Webserver möglich ist.

```bash (uid:1)
telnet sosmig-web.hio.rub.de 1025
```

Es scheint als sei die Firewall noch nicht richtig konfiguriert, wir legen also erstmal eine neue Regel an, für IpV4:

```bash (uid:1)
sudo iptables -A OUTPUT -p tcp -d sosmig-web.hio.rub.de --dport 1025 -j ACCEPT
```

Jetzt können wir den Command oben erneut ausführen um zu sehen ob es funktioniert. Falls nicht fehlen vermutlich noch die Regel auf der Seite des Webservers. Dazu legen wir diese nun an:

Nun das gleiche nochmal für IPv6, nur um sicher zu gehen:

```bash (uid:1)
sudo ip6tables -A OUTPUT -p tcp -d sosmig-web.hio.rub.de --dport 1025 -j ACCEPT
```

```bash (uid:2)
sudo iptables -A INPUT -p tcp -s sosmig-app.hio.rub.de --dport 1025 -j ACCEPT && sudo ip6tables -A INPUT -p tcp -s sosmig-app.hio.rub.de --dport 1025 -j ACCEPT
```

Connection Refused aber kein Timeout, d.h. es scheint eine Verbindung mölich zu sein es lauscht nur keiner am anderen Ende. Wir nehmen nun NC um das zu ändern und final die Verbindung zu testen:

```bash (uid:2)
sudo apt install netcat-openbsd -y
```

Wir starten Netcat auf Port 1025, damit am anderen Ende jemand *abnimmt* um die Verbindung zu testen

```bash (uid:2)
nc -l -p 1025
```

Jetzt wo netcat lauscht können wir die telnet Verbindung aus dem Comandblock weiter oben erneut aufbauen.

Der Verbindunsaufbau hat nun geklappt. Jetzt kann der Mailhog als Service auf dem Webserver eingerichtet werden.

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

```bash (uid:None)
sudo vim /etc/systemd/system/mailhog.service
```

```bash (uid:None)
sudo vim /opt/mailhog/.env
```

After creating the unit file, we need to enable it and then reload the systemd daemon:

```bash (uid:None)
sudo systemctl enable mailhog
```

```bash (uid:None)
sudo systemctl daemon-reload
```

Nun müssen wir noch die Mailhog bereitstellen, dazu laden wir diese local runter und kopieren sie via scp auf den Webserver.

```bash (uid:0)
curl -LO https://github.com/mailhog/MailHog/releases/download/v1.0.0/MailHog_linux_amd64
```

Wir legen noch ein Verzeichnis auf dem Zielsystem an wo wir später die Konfiguration und die Binary ablegen können.

```bash (uid:None)
sudo mkdir -p /opt/mailhog
```

```bash (uid:0)
scp MailHog_linux_amd64 vangegcz@sosmig-web.hio.rub.de:/tmp/MailHog
```

```bash (uid:None)
sudo mv /tmp/MailHog /opt/mailhog/MailHog
```

> Hinweis: Wir haben keine Berechtigung auf Opt zu schreiben also müssen wir die Datei in tmp zwischenspeichern und dann verschieben via sudo

Jetzt können wir den Mailhog starten:

```bash (uid:None)
sudo systemctl start mailhog && sudo systemctl status mailhog
```
