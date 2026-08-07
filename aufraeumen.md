# Shell Notebook Export - 2026-06-05 15:47:49

# Aufräumarbeiten *netappnfs*

## Dumps

Bestandsaufnahme des IST-Zustands nach den Aufräumarbeiten der  Dumps, also Auflistung aller Dumps auf netappnfs sowie gesamt Speicherbedarf dieser:

```bash (uid:1)
sudo ls -lahR /opt/netappnfs/**/*.[dump,bak] | awk '{print $6 " " $7 " " $5 " " $9'}
```

```text

ls: cannot access '/opt/netappnfs/**/*.[dump,bak]': No such file or directory
```

```bash (uid:1)
ls -lR /opt/netappnfs/**/*.dump /opt/netappnfs/**/*.bak | grep -v '^d' | awk '{total += $5} END {print total / 1024 / 1024 / 1024 " GB"}'
```

```text

ls: cannot access '/opt/netappnfs/**/*.bak': No such file or directory
9.26724 GB
```

---

## Webapp Sicherungskopien

Im Zuge des Releasewechsel wurden diverse Sicherungskopien der alten webapps Verzeichnisse von HiO angelegt. Diese verbrauchen relativ viel Speicher auf dem netappnfs und können nun gelöscht werden.

```bash (uid:1)
sudo find /opt/netappnfs/ -type d -name "*webapps*"
```

```bash (uid:1)
sudo rm -rf /opt/netappnfs/cust/backup/webapps
```

```bash (uid:1)
sudo rm -rf /opt/netappnfs/test/20260324_backup/webapps
```

```bash (uid:1)
sudo rm -rf /opt/netappnfs/sosmig/20260320_backup_webapps
```

```bash (uid:1)
sudo rm -rf /opt/netappnfs/sosmig/20260320_tomcat9/webapps
```

```bash (uid:1)
sudo rm -rf /opt/netappnfs/qs/20260420_webapps
```

```bash (uid:1)
sudo rm -rf /opt/netappnfs/cust-2024-12/backup/webapps
```

```bash (uid:1)
sudo rm -rf /opt/netappnfs/prod/20260422_webapps
```

```bash (uid:1)
df -h /opt/netappnfs
```

```text

Filesystem                                             Size  Used Avail Use% Mounted on
netapp-nfs.rz.ruhr-uni-bochum.de:/netapp_nfs_hisinone  351G  219G  133G  63% /opt/netappnfs
```

---

Als nächstes suchen wir noch nach alten tomcat9 Verzeichnissen. Dies können wir mit folgendem Befehl von lokal aus tun um dann gezielt zu löschen, dazu legen wir zunächst eine Liste mit allen app Server connection strings für ssh an:

```bash (uid:0)
vim hio_app_hosts.txt
```

```text
="hio_app_hosts.txt" 11L, 305B▽  zz           10;?11;?vangegcz@cust-app.hio.rub.de
vangegcz@t1-app-01.hio.rub.devangegcz@t1-app-02.hio.rub.devangegcz@cust-app.hio.rub.de
vangegcz@prod-app-01.hio.rub.de
vangegcz@prod-app-02.hio.rub.de
vangegcz@prod-app-03.hio.rub.de
vangegcz@prod-app-04.hio.rub.de
vangegcz@sosmig-app.hio.rub.de
vangegcz@qs-app.hio.rub.de

~                                                                                                                                                         ~                                                                                                                                                         ~                                                                                                                                                         ~                                                                                                                                                         ~                                                                                                                                                         ~                                                                                                                                                         ~                                                                                                                                                         ~                                                                                                                                                         ~                                                                                                                                                         ~                                                                                                                                                         ~                                                                                                                                                         ~                                                                                                                                                         6,10All~@k   7~@k   8~@k   7~@k   6~@k   5~@k   4~@k   3~@k   2~@k   1~@k   ~@k   ~@k   ~@k   9 ~@k   8~@k   7^[  ^[  dd  
~                                                                                                                                                         1,1All^[  ^[  ::w"hio_app_hosts.txt" 10L, 276B written1,1All1,1All::qwE492: Not an editor command: qw1,1All::q>
```

```bash (uid:0)
while read -r host; do
    # Mit < /dev/null verhindern wir, dass ssh den Input-Stream der Schleife kapert
    ssh -n -q -o ConnectTimeout=5 "$host" "[ -d /var/lib/tomcat9 ] && echo '$host: vorhanden' || echo '$host: nicht vorhanden'" < /dev/null
done < hio_app_hosts.txt
```

```text
vangegcz@t1-app-01.hio.rub.de: nicht vorhanden
vangegcz@t1-app-02.hio.rub.de: nicht vorhanden
vangegcz@cust-app.hio.rub.de: nicht vorhanden
vangegcz@prod-app-01.hio.rub.de: nicht vorhanden
vangegcz@prod-app-02.hio.rub.de: nicht vorhanden
vangegcz@prod-app-03.hio.rub.de: nicht vorhanden
vangegcz@prod-app-04.hio.rub.de: nicht vorhanden
vangegcz@sosmig-app.hio.rub.de: nicht vorhanden
vangegcz@qs-app.hio.rub.de: nicht vorhanden
```

```bash (uid:0)
rm -rf hio_app_hosts.txt
```
