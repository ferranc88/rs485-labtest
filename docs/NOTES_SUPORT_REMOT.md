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

---

## 2. Telegram dona `HTTP 401 Unauthorized`

401 vol dir **exactament una cosa**: el token carregat a la variable d'entorn
**no és vàlid** (mal copiat, tallat, amb un espai, o revocat). No és xarxa ni
chat_id. Sovint passa perquè s'ha arreglat el `~/.zshrc` però el terminal
obert encara té el valor vell, o al `~/.zshrc` hi ha una errada.

Fer-ho tot **al mateix terminal**:

**1) Agafa el token bo** de @BotFather (`/mybots` → bot → API Token) i posa'l a
la sessió, i valida'l a l'acte:
```bash
export RS485_TELEGRAM_TOKEN='ENGANXA_EL_TOKEN_AQUI'
curl -s "https://api.telegram.org/bot$RS485_TELEGRAM_TOKEN/getMe"
```
Ha de sortir `{"ok":true,...}`. Si encara és 401 → el token està mal copiat o
el bot no existeix.

**2) Quan `getMe` doni `ok:true`**, prova la notificació immediatament:
```bash
rs485-labtest notify-test
```

**3) Fes-ho permanent** (corregeix el token dolent del `~/.zshrc`):
```bash
nano ~/.zshrc          # edita la línia export RS485_TELEGRAM_TOKEN='...'
source ~/.zshrc
curl -s "https://api.telegram.org/bot$RS485_TELEGRAM_TOKEN/getMe"   # ok:true
```

> Regla: fins que `getMe` no digui `ok:true` **en aquesta sessió**, res
> funcionarà — el 401 és Telegram dient "aquest token no el reconec".
