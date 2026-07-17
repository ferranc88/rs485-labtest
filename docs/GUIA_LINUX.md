# Guia ràpida — instal·lar, actualitzar i executar (Linux)

Passos de bash per posar en marxa `rs485-labtest` al PC Linux del laboratori.

---

## 1. Primera instal·lació (només un cop)

```bash
# Python (si 'python3 --version' falla). Ajusta a la teva distro:
sudo apt update && sudo apt install -y python3 python3-venv python3-pip   # Debian/Ubuntu
# sudo dnf install -y python3 python3-pip                                 # Fedora/RHEL
# sudo pacman -S python                                                   # Arch

# Autenticació a GitHub (repo privat). Cal scope 'repo'.
gh auth login
gh auth status                         # ha de llistar l'scope 'repo'
gh auth setup-git                      # perquè 'git pull' no demani contrasenya

# Clonar el repo
gh repo clone ferranc88/rs485-labtest
cd rs485-labtest

# Entorn virtual + instal·lació editable
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Comprovar
rs485-labtest --version                # ha de dir 0.3.0
```

> Si `python3 -m venv` es queixa d'`ensurepip`: `sudo apt install python3-venv` i torna-hi.

---

## 2. Actualitzar a l'última versió (cada cop que hi hagi canvis)

```bash
cd ~/rs485-labtest
git pull
```

No cal reinstal·lar res: com que està instal·lat amb `pip install -e .`
(editable), els canvis del `git pull` queden actius a l'instant.

---

## 3. Executar

```bash
cd ~/rs485-labtest
source .venv/bin/activate              # activa el venv (cada sessió nova)

# Assistent interactiu (recomanat): pregunta i llança
rs485-labtest wizard

# O directament, tot des d'aquest PC (els 2 adaptadors aquí):
rs485-labtest duo \
    --port /dev/serial/by-id/<ADAPTADOR_A> \
    --slave-port /dev/serial/by-id/<ADAPTADOR_B> \
    --profile smoke --label "NDR6_Vcm+0V" --live rich
```

Un cop desada una config al wizard, el proper `rs485-labtest wizard` te
l'oferirà d'entrada per llançar-la directament.

---

## 4. Comprovacions útils

```bash
# Quins adaptadors sèrie hi ha connectats (noms estables):
ls -l /dev/serial/by-id/

# Baixar el latency_timer a 1 ms (FTDI) abans de mesurar latències:
echo 1 | sudo tee /sys/bus/usb-serial/devices/ttyUSB0/latency_timer
echo 1 | sudo tee /sys/bus/usb-serial/devices/ttyUSB1/latency_timer

# Notificacions al mòbil (Telegram) per a soak sense vigilància:
export RS485_TELEGRAM_TOKEN="123456:ABC-..."   # de @BotFather
rs485-labtest notify-test                       # et diu el chat_id
export RS485_TELEGRAM_CHAT_ID="987654321"
rs485-labtest notify-test                       # missatge de prova
# (posa els dos export al ~/.bashrc perquè persisteixin)

# Permís d'accés als ports (un cop; després tanca i obre sessió):
sudo usermod -aG dialout $USER

# Passar la bateria de tests (sense hardware, sobre ptys):
pytest -q
```

---

## Problemes freqüents

| Símptoma | Solució |
|---|---|
| `python3: command not found` | instal·la Python (pas 1) |
| `ensurepip is not available` | `sudo apt install python3-venv` |
| `git pull` demana usuari/contrasenya | `gh auth setup-git` |
| clone: `Could not resolve to a Repository` | el token no té scope `repo`: `gh auth refresh -h github.com -s repo` |
| `rs485-labtest: command not found` | activa el venv: `source .venv/bin/activate` |
| Permission denied al `/dev/ttyUSB*` | `sudo usermod -aG dialout $USER` i reinicia sessió |
