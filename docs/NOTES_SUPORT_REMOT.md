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

---

## 3. Les variables s'obliden en tancar el terminal

`export` escrit al terminal dura **només aquella sessió**. Perquè persisteixin
han d'estar al fitxer d'arrencada del shell — i cal posar-les al del shell que
fas servir de veritat. **Comprova primer quin shell obre el terminal:**
```bash
echo "$0"        # -bash o /bin/bash -> BASH ;  -zsh o /bin/zsh -> ZSH
```

- **BASH** (el cas del PC del lab, usuari `root`) → `~/.bashrc`:
  ```bash
  echo 'export RS485_TELEGRAM_TOKEN="EL-TOKEN-BO"'  >> ~/.bashrc
  echo 'export RS485_TELEGRAM_CHAT_ID="EL-CHAT-ID"' >> ~/.bashrc
  source ~/.bashrc
  ```
- **ZSH** → el mateix però a `~/.zshrc`.

> ⚠️ Bash **no** llegeix mai els fitxers de zsh (`.zshrc`, `.zshenv`) ni al
> revés. Posar-ho al fitxer del shell que no toca és la causa #1 de "no
> persisteix".

Prova de veritat: **tanca i obre un terminal nou** i comprova que hi són:
```bash
echo "[$RS485_TELEGRAM_TOKEN]"    # ha de sortir ple
```

> `~` es fa amb `AltGr+4` i espai; o escriu `$HOME/.bashrc` en lloc de `~/.bashrc`.

---

## 4. Hi són al fitxer però no es carreguen

Diagnòstic d'una sola línia al terminal nou:
```bash
whoami; echo "$0 $SHELL"; echo "[$RS485_TELEGRAM_TOKEN]"; grep -l RS485 ~/.bashrc ~/.zshrc ~/.zshenv ~/.profile 2>/dev/null
```

- **shell = bash però les línies són a `.zshrc`/`.zshenv`** → fitxer equivocat:
  passa-les a `~/.bashrc` (secció 3).
- **`whoami` no és l'usuari amb qui corres els tests** → cada usuari té els seus
  fitxers; posa-les per a l'usuari bo i llança sempre amb aquell.
- **shell login que no llegeix `~/.bashrc`** → afegeix-ho també a `~/.profile`:
  ```bash
  grep RS485 ~/.bashrc >> ~/.profile
  ```

---

## 5. Moltes línies duplicades al `~/.zshrc`

Passa si s'ha repetit l'`echo … >> ~/.zshrc` diverses vegades. Mana **l'última**
del fitxer, així que si la darrera és dolenta, trenca la resta. Deixa'n només
una de bona:

```bash
cp ~/.zshrc ~/.zshrc.bak            # còpia de seguretat
sed -i '/RS485_TELEGRAM/d' ~/.zshrc # esborra TOTES les línies RS485
grep RS485 ~/.zshrc                 # no ha de tornar res

# torna a afegir-ne UNA de sola (el token que dona getMe ok:true):
echo 'export RS485_TELEGRAM_TOKEN="EL-TOKEN-BO"'  >> ~/.zshrc
echo 'export RS485_TELEGRAM_CHAT_ID="EL-CHAT-ID"' >> ~/.zshrc
source ~/.zshrc

grep RS485 ~/.zshrc                 # ara han de sortir NOMÉS 2 línies
curl -s "https://api.telegram.org/bot$RS485_TELEGRAM_TOKEN/getMe"   # ok:true
```

---

## 6. Notificar diverses persones

Dues maneres (cap requereix tocar codi):

**a) chat_id per coma** (per a 1-2 persones fixes). Cadascú ha d'obrir el bot i
prémer **Start** abans:
```bash
export RS485_TELEGRAM_CHAT_ID="el-teu-id,l-id-de-l-altra"
rs485-labtest notify-test          # prova cada destinatari i diu quin falla
```

**b) un grup** (recomanat per a equip; afegeixes gent al grup i prou):
1. Crea un grup a Telegram i afegeix-hi el bot.
2. Escriu al grup `/start@elteubot` perquè el bot el "vegi".
3. Agafa l'id del grup (és **negatiu**):
   ```bash
   curl -s "https://api.telegram.org/bot$RS485_TELEGRAM_TOKEN/getUpdates"
   # busca  "chat":{"id":-1001234567890,...}
   ```
4. Posa'l com a destinatari:
   ```bash
   export RS485_TELEGRAM_CHAT_ID="-1001234567890"
   rs485-labtest notify-test
   ```
