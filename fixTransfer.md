# Shell Notebook Export - 2026-06-18 14:50:19

# Anpassen des Git Säulentrasnfer

Die einzelnen Säulen von HisInOne wuren in Gruppn unterteilt, welche wiederum jede ihrem eigenen Datenbankcluster zugeordnet werden. Zuvor war das nicht so, da haben sich alle Säulen den selben Datenbankcluser geteilt. Daher müssen alle Konfigurationen, welche nicht Spezialmodule fähig sind aber den Hostname der einzelnen Datenbakcluster und -knoten benötigen über einen Git-Filter auf jeder Säule individuell angepasst werden.

Zunächst müssen wir ein Connectionstring anlegen:

```bash (uid:1)
DB_CLUSTER_CONF_STRING='
# DB-Cluster Configuration String for Confpackages
DB_CLUSTER_CONFIGURATION="pg-cluster9-node1.it-services.ruhr-uni-bochum.de,pg-cluster9-node2.it-services.ruhr-uni-bochum.de"
'
```

Nun fügen wir die Zeile zur secret.env hinzu (wenn nicht vorhanden):

```bash (uid:1)
cd /var/lib/tomcat10
```

```bash (uid:1)
sudo grep -q "#  DB-Cluster Configuration" secrets.env || printf "\n%s\n" "$DB_CLUSTER_CONF_STRING" | sudo tee -a secrets.env
```

```text



# DB-Cluster Configuration String for Confpackages
DB_CLUSTER_CONFIGURATION="pg-cluster9-node1.it-services.ruhr-uni-bochum.de,pg-cluster9-node2.it-services.ruhr-uni-bochum.de"
```

```bash (uid:1)
sudo cat secrets.env
```

```text

HIO_CUST_DB_PASSWORD=kdL7mnOZaCsXb0Jp4sTxgxkBYwVcMwle07JuIJTB5vCfHXr5NXgMP1NeuEExkxlH
SOSPOS_DB_PASSWORD=idefix
SHARED_SECRET=wmmrrJE3tPG9is1YjpPSBiCK7uEgsh


# DB-Cluster Configuration String for Confpackages
DB_CLUSTER_CONFIGURATION="pg-cluster9-node1.it-services.ruhr-uni-bochum.de,pg-cluster9-node2.it-services.ruhr-uni-bochum.de"



# DB-Cluster Configuration String for Confpackages
DB_CLUSTER_CONFIGURATION="pg-cluster9-node1.it-services.ruhr-uni-bochum.de,pg-cluster9-node2.it-services.ruhr-uni-bochum.de"



# DB-Cluster Configuration String for Confpackages
DB_CLUSTER_CONFIGURATION="pg-cluster9-node1.it-services.ruhr-uni-bochum.de,pg-cluster9-node2.it-services.ruhr-uni-bochum.de"
```

Als nächstes brauchen wir ein Script was den Platzhalter in den Konfigurationsdateien (vornehmlich die Configuration Packages von HiO) austauscht durch diesen Connection String.

```
#!/bin/bash

source secret.env

find /var/lib/tomcat10/webapps/qisserver/WEB-INF/conf/hisinone/confPackages -type f -name ".xml" -exec sed -i
-e "s/db_cluster_configuration/$DB_CLUSTER_CONFIGURATION/g"
{} +
```

```bash (uid:1)
vim updateConfPackageDBCluster.sh
```

```text
#!/bin/bash

source secret.env

find /var/lib/tomcat10/webapps/qisserver/WEB-INF/conf/hisinone/confPackages -type f -name ".xml" -exec sed -i
-e "s/db_cluster_configuration/$DB_CLUSTER_CONFIGURATION/g"
{} +
~                                                                                                                                                                                                                                             ~                                                                                                                                                                                                                                             ~                                                                                                                                                                                                                                             ~                                                                                                                                                                                                                                             ~                                                                                                                                                                                                                                             ~                                                                                                                                                                                                                                             ~                                                                                                                                                                                                                                             ~                                                                                                                                                                                                                                             ~                                                                                                                                                                                                                                             ~                                                                                                                                                                                                                                             ~                                                                                                                                                                                                                                             ~                                                                                                                                                                                                                                             ~                                                                                                                                                                                                                                             ~                                                                                                                                                                                                                                             ~                                                                                                                                                                                                                                             ~                                                                                                                                                                                                                                             7,4All#!/bin/bash

source secret.env

find /var/lib/tomcat10/webapps/qisserver/WEB-INF/conf/hisinone/confPackages -type f -name ".xml" -exec sed -i
-e "s/db_cluster_configuration/$DB_CLUSTER_CONFIGURATION/g"
{} +
~                                                                                                                                                                                                                                                       ~                                                                                                                                                                                                                                                       ~                                                                                                                                                                                                                                                       ~                                                                                                                                                                                                                                                       ~                                                                                                                                                                                                                                                       ~                                                                                                                                                                                                                                                       ~                                                                                                                                                                                                                                                       ~                                                                                                                                                                                                                                                       ~                                                                                                                                                                                                                                                       ~                                                                                                                                                                                                                                                       ~                                                                                                                                                                                                                                                       ~                                                                                                                                                                                                                                                       ~                                                                                                                                                                                                                                                       ~                                                                                                                                                                                                                                                       ~                                                                                                                                                                                                                                                       ~                                                                                                                                                                                                                                                       7,4All::q>
```

```bash (uid:1)
sudo chmod +x updateConfPackageDBCluster.sh
```
