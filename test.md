# Shell Notebook Export - 2026-05-15 11:57:41

```bash
ls
```

```text
dataimport  hio_autoreboot  MailHog_linux_amd64
```

*Das* ist der Status

```bash
sudo systemctl status
```

```text
=● qs-app
    State: running
    Units: 465 loaded (incl. loaded aliases)
     Jobs: 0 queued
   Failed: 0 units
    Since: Mon 2026-04-20 11:27:49 CEST; 3 weeks 4 days ago
  systemd: 255.4-1ubuntu8.15
   CGroup: /
           ├─init.scope
           │ └─1 /usr/lib/systemd/systemd --system --deserialize=72
           ├─system.slice
           │ ├─ModemManager.service
           │ │ └─310444 /usr/sbin/ModemManager
           │ ├─NetworkManager.service
           │ │ └─1069 /usr/sbin/NetworkManager --no-daemon
           │ ├─avahi-daemon.service
           │ │ ├─3777871 "avahi-daemon: running [qs-app.local]"
           │ │ └─3777873 "avahi-daemon: chroot helper"
           │ ├─check-mk-agent-async.service
           │ │ ├─   1192 /bin/bash /usr/bin/check_mk_agent
           │ │ └─4158412 sleep 60
           │ ├─chrony.service
           │ │ ├─310397 /usr/sbin/chronyd -F 1
lines 1-23 ESCESCOOBB           │ │ └─310398 /usr/sbin/chronyd -F 1
lines 2-24 ESCESCOOBB           │ ├─clamav-freshclam.service
lines 3-25 ESCESCOOBB           │ │ └─3099494 /usr/bin/freshclam -d --foreground=true
lines 4-26 ESCESCOOBB           │ ├─cmk-agent-ctl-daemon.service
lines 5-27 ESCESCOOBB           │ │ └─1198 /usr/bin/cmk-agent-ctl daemon
lines 6-28 ESCESCOOBB           │ ├─cron.service
lines 7-29 ESCESCqqlines 7-29 ESCESCOOBB           │ │ └─1293 /usr/sbin/cron -f -P
lines 8-30 ESCESCOOBB           │ ├─dbus.service
lines 9-31 ESCESCOOBB           │ │ └─1006 @dbus-daemon --system --address=systemd: --nofo>
lines 10-32>
```
