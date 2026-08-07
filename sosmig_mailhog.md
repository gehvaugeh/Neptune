# Shell Notebook Export - 2026-05-29 13:54:29

Zuächst testen wir mit Telnet ob eine Verbindung auf den Port von MailHog auf vom Appserver zum Webserver möglich ist.

```bash
telnet sosmig-web.hio.rub.de 1025
```

```text
Trying 2a05:3e00:1:1025:10:200:61:198...
Connection failed: Connection refused
Trying 10.200.61.198...
Connected to sosmig-web.hio.rub.de.
Escape character is '^]'.
hallo^M;^[iC^Mquit^M^M^M^M^M^[
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

```text
NS_e7059e20_0_/home/vangegcz
```

Connection Refused aber kein Timeout, d.h. es scheint eine Verbindung mölich zu sein es lauscht nur keiner am anderen Ende. Wir nehmen nun NC um das zu ändern und final die Verbindung zu testen:

```bash
sudo apt install netcat-openbsd -y && nc -l -p 1025
```

```text
Reading package lists... 0%Reading package lists... 100%Reading package lists... Done
Building dependency tree... 0%Building dependency tree... 0%Building dependency tree... 50%Building dependency tree... 50%Building dependency tree... Done
Reading state information... 0% Reading state information... 0%Reading state information... Done
netcat-openbsd is already the newest version (1.226-1ubuntu2).
0 upgraded, 0 newly installed, 0 to remove and 5 not upgraded.
```

Jetzt wo netcat lauscht können wir die telnet Verbindung aus dem Comandblock weiter oben erneut aufbauen.

Der Verbindunsaufbau hat nun geklappt. Jetzt kann der Mailhogals Service auf dem Webserver eingerichtet werden.
