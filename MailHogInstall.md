# Shell Notebook Export - 2026-05-29 16:16:38

Zuächst testen wir mit Telnet ob eine Verbindung auf den Port von MailHog auf vom Appserver zum Webserver möglich ist.

```bash
telnet sosmig-web.hio.rub.de 1025
```

Es scheint als sei die Firewall noch nicht richtig konfiguriert, wir legen also erstmal eine neue Regel an, für IpV4:

```bash
sudo iptables -A OUTPUT -p tcp -d sosmig-web.hio.rub.de --dport 1025 -j ACCEPT
```

Jetzt können wir den Command oben erneut ausführen um zu sehen ob es funktioniert. Falls nicht fehlen vermutlich noch die Regel auf der Seite des Webservers. Dazu legen wir diese nun an:

Nun das gleiche nochmal für IPv6, nur um sicher zu gehen:

```bash
sudo ip6tables -A OUTPUT -p tcp -d sosmig-web.hio.rub.de --dport 1025 -j ACCEPT
```

```bash
sudo iptables -A INPUT -p tcp -s sosmig-app.hio.rub.de --dport 1025 -j ACCEPT && sudo ip6tables -A INPUT -p tcp -s sosmig-app.hio.rub.de --dport 1025 -j ACCEPT
```

Connection Refused aber kein Timeout, d.h. es scheint eine Verbindung mölich zu sein es lauscht nur keiner am anderen Ende. Wir nehmen nun NC um das zu ändern und final die Verbindung zu testen:

```bash
sudo apt install netcat-openbsd -y && nc -l -p 1025
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

```bash
sudo vim /etc/systemd/system/mailhog.service
```

```text
="/etc/systemd/system/mailhog.service" [New]▽  zz           10;?11;?  1 
~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 Type  :qa  and press <Enter> to exit Vim/Directorysearch hit BOTTOM, continuing at TOPE486: Pattern not found: Directory-- INSERT (paste) --t]
  2 Description=Mailtrap via MailHog for HiO  3 After=network.target  4   5 [Service]  6 Type=simple  7 User=www-data  8 ExecStart=/opt/mailhog/MailHog  9 EnvironmentFile=/opt/mailhog/.env 10 StandardOutput=journal 11 StandardError=journal 12 SyslogIdentifier=mailhog 13 Restart=always 14  15 [Install] 16 WantedBy=multi-user.target[][][][][t][]Ut][Utnt]it]^[  ::wq"/etc/systemd/system/mailhog.service" [New] 16L, 294B written
>NS_8b28b266_0_/home/vangegcz
```

```bash
sudo vim /opt/mailhog/.env
```

```text
="/opt/mailhog/.env" [New]▽  zz           10;?11;?  1 
~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ~                                                                                                                                                                                 ^?  ^[  ^[  ^[  ^[  ma  s cl  -- INSERT (paste) --kd^?^?^?^?^?^?^?^[  ^?  ^?  ^?  ^?  ^?  ^?  ^?  ^?  ^?  ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   ~@k   99x   99dl    ::wq"/opt/mailhog/.env" [New] 1L, 1B written
>NS_4acda1a3_0_/home/vangegcz
```

After creating the unit file, we need to enable it and then reload the systemd daemon:

```bash
sudo systemctl enable mailhog
```

```text
Created symlink /etc/systemd/system/multi-user.target.wants/mailhog.service → /etc/systemd/system/mailhog.service.
```

```bash
sudo systemctl daemon-reload
```

```text

```

Nun müssen wir noch die Mailhog bereitstellen, dazu laden wir diese local runter und kopieren sie via scp auf den Webserver.

```bash
curl -LO https://github.com/mailhog/MailHog/releases/download/v1.0.0/MailHog_linux_amd64
```

```text
% Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                 Dload  Upload   Total   Spent    Left  Speed
  0     0    0     0    0     0      0      0 --:--:-- --:--:-- --:--:--     0  0     0    0     0    0     0      0      0 --:--:-- --:--:-- --:--:--     0
  5 10.7M    5  559k    0     0   583k      0  0:00:18 --:--:--  0:00:18  583k 46 10.7M   46 5055k    0     0  2576k      0  0:00:04  0:00:01  0:00:03 4478k 86 10.7M   86 9471k    0     0  3202k      0  0:00:03  0:00:02  0:00:01 4456k100 10.7M  100 10.7M    0     0  3372k      0  0:00:03  0:00:03 --:--:-- 4535k
```

Wir legen noch ein Verzeichnis auf dem Zielsystem an wo wir später die Konfiguration und die Binary ablegen können.

```bash
sudo mkdir -p /opt/mailhog
```

```text
NS_274526ab_0_/home/vangegcz
```

```bash
scp MailHog_linux_amd64 vangegcz@sosmig-web.hio.rub.de:/tmp/MailHog
```

```text
MailHog_linux_amd64                                                                                                                               0%    0     0.0KB/s   --:-- ETAMailHog_linux_amd64                                                                                                                               2%  255KB 254.9KB/s   00:42 ETAMailHog_linux_amd64                                                                                                                               2%  255KB 229.4KB/s   00:46 ETAMailHog_linux_amd64                                                                                                                               2%  255KB 206.5KB/s   00:51 ETAMailHog_linux_amd64                                                                                                                              97%   10MB   1.2MB/s   00:00 ETAMailHog_linux_amd64                                                                                                                             100%   11MB   2.7MB/s   00:04
```

```bash
sudo mv /tmp/MailHog /opt/mailhog/MailHog
```

```text
NS_ad421069_0_/home/vangegcz
```

> Hinweis: Wir haben keine Berechtigung auf Opt zu schreiben also müssen wir die Datei in tmp zwischenspeichern und dann verschieben via sudo

Jetzt können wir den Mailhog starten:


```bash
sudo systemctl start mailhog && sudo systemctl status mailhog
```

```text
=● mailhog.service - Mailtrap via MailHog for HiO
     Loaded: loaded (8;;file://sosmig-web/etc/systemd/system/mailhog.service/etc/systemd/system/mailhog.service8;;; enabled; preset: enabled)
     Active: activating (auto-restart) (Result: exit-code) since Fri 2026-05-29 16:16:15 CEST; 14ms ago
    Process: 3539974 ExecStart=/opt/mailhog/MailHog (code=exited, status=203/EXEC)
   Main PID: 3539974 (code=exited, status=203/EXEC)
        CPU: 1ms

May 29 16:16:15 sosmig-web systemd[1]: mailhog.service: Failed with result 'exit-code'.
>NS_33acb90c_3_/home/vangegcz
```
