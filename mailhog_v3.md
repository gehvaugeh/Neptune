# Shell Notebook Export - 2026-06-02 10:32:27

Zuächst testen wir mit Telnet ob eine Verbindung auf den Port von MailHog auf vom Appserver zum Webserver möglich ist.

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

```bash (uid:0)
sudo journalctl -f -u mailhog
```

```text


Jun 02 10:19:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:20:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:21:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:22:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:23:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:24:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:25:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:26:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:27:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:28:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
Jun 02 10:29:24 sosmig-web mailhog[4120609]: [APIv1] KEEPALIVE /api/v1/events
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

```bash (uid:0)
sudo vim /etc/rsyslog.d/mailhog.conf
```

```text


="/etc/rsyslog.d/mailhog.conf" 4L, 105B▽  zz           10;?11;?  1 if $programname == 'mailhog' then {
  2   action(type="omfile" file="/var/log/mailhog/logfile.log")  3   stop  4 }
~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ~                                                                                            ::q
>
```

Nun müssen wir den Dienst rsyslog neustarten:

```bash (uid:1)
sudo systemctl enable rsyslog.service
```

```text

Failed to enable unit: Unit file rsyslog.service does not exist.
```

Es scheint als sei rsyslog nicht installiert (das kann auf neueren Ubuntu Versionen der Fall sein, also installieren wir es einfach nach):

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

```bash (uid:1)
tail -F /var/log/mailhog/logfile.log
```

```text

tail: cannot open '/var/log/mailhog/logfile.log' for reading: No such file or directory
```
