# Notes de suport remot

Bloc de comandes útils que anem acumulant per resoldre coses a la màquina del
laboratori. Cada secció és un problema concret amb les comandes per
diagnosticar-lo. **Per actualitzar-lo a la màquina del lab: `git pull`.**

> Les comandes que fan servir `$RS485_TELEGRAM_TOKEN` no mostren mai el token:
> el llegeixen de la variable d'entorn. No enganxis el token en clar enlloc.

---

## 1. Notificacions de Telegram no arriben

Diagnòstic de dalt a baix. Atura't al primer que falli.

**a) Les variables hi són i estan netes** (sense cometes ni espais dins):
```bash
echo "[$RS485_TELEGRAM_TOKEN]"      # [123456789:AAH...]  ~46 caràcters, amb ':'
echo "[$RS485_TELEGRAM_CHAT_ID]"    # [987654321]  un número
```

**b) El token és vàlid** (aïlla el token de tota la resta):
```bash
curl -s "https://api.telegram.org/bot$RS485_TELEGRAM_TOKEN/getMe"
```
- `{"ok":true,...}` → token bo, continua.
- `{"ok":false,"error_code":401}` → token dolent/revocat: torna a @BotFather
  (`/mybots` → bot → API Token) i refés l'`export` al `~/.zshrc`.

**c) L'error REAL de l'enviament** (reprodueix el que fa l'eina i l'imprimeix;
el codi normal l'amaga):
```bash
python3 -c "
import urllib.request, urllib.parse, os
t=os.environ['RS485_TELEGRAM_TOKEN']; c=os.environ['RS485_TELEGRAM_CHAT_ID']
d=urllib.parse.urlencode({'chat_id':c,'text':'prova py'}).encode()
try:
    r=urllib.request.urlopen(urllib.request.Request(f'https://api.telegram.org/bot{t}/sendMessage',data=d),timeout=10)
    print(r.read().decode())
except Exception as e:
    print('ERROR:', repr(e))
"
```
Segons el que surti:
- `CERTIFICATE_VERIFY_FAILED` / `SSLCertVerificationError` → falten CA o hi ha
  proxy: `sudo apt install ca-certificates && sudo update-ca-certificates`.
- `...timed out` → `api.telegram.org` filtrat en aquesta xarxa (prova amb dades
  del mòbil).
- `{"ok":false,"description":"chat not found"}` → chat_id erroni o no has premut
  **Start** al bot des del teu Telegram.
- `{"ok":true,...}` → Python SÍ que envia; el problema és la config de l'eina.

**d) Enviament directe amb curl** (contrast; dona l'error exacte de Telegram):
```bash
curl -s "https://api.telegram.org/bot$RS485_TELEGRAM_TOKEN/sendMessage?chat_id=$RS485_TELEGRAM_CHAT_ID&text=prova_curl"
```

**e) Descobrir el chat_id** (has d'haver escrit tu al bot abans):
```bash
curl -s "https://api.telegram.org/bot$RS485_TELEGRAM_TOKEN/getUpdates"
# busca  "chat":{"id":NNNNN}  -> aquell número és el teu chat_id
```

**f) Prova integrada de l'eina** (un cop a/b/c estan bé):
```bash
rs485-labtest notify-test
```
