"""Bateria completa (perfil smoke, mode duo) sobre un link virtual amb ptys.

Nomes POSIX: dos parells de ptys units per bombes de bytes fan de "cable".
Es el test de paritat amb l'script v2.0: exit 0, cap FAIL i els tres
informes generats.
"""

import glob
import json
import os
import subprocess
import sys
import threading

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform == "win32", reason="pty nomes existeix a POSIX"),
]


class PtyLink:
    """Dos ptys units en creu: el que entra per A surt per B i viceversa."""

    def __init__(self):
        import pty
        import tty
        self.master_a, self.slave_a = pty.openpty()
        self.master_b, self.slave_b = pty.openpty()
        for fd in (self.slave_a, self.slave_b):
            tty.setraw(fd)
        self.port_a = os.ttyname(self.slave_a)
        self.port_b = os.ttyname(self.slave_b)
        self._stop = threading.Event()
        self._threads = [
            threading.Thread(target=self._pump, args=(self.master_a, self.master_b),
                             daemon=True),
            threading.Thread(target=self._pump, args=(self.master_b, self.master_a),
                             daemon=True),
        ]
        for t in self._threads:
            t.start()

    def _pump(self, src, dst):
        import select
        while not self._stop.is_set():
            r, _, _ = select.select([src], [], [], 0.05)
            if r:
                try:
                    data = os.read(src, 4096)
                except OSError:
                    break
                if data:
                    os.write(dst, data)

    def close(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=1)
        for fd in (self.master_a, self.master_b, self.slave_a, self.slave_b):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.parametrize("interface", ["rs485-full", "rs422", "rs232"])
def test_duo_smoke_fullduplex_interfaces_pass_on_virtual_link(tmp_path, interface):
    # Els ptys son full-duplex per naturalesa: banc ideal per a aquestes
    # interficies. Valida que la carrega simultania (finestra de trames en vol)
    # funciona end-to-end contra el slave real, sense colisions ni perdues.
    label = f"ci_{interface.replace('-', '_')}"
    link = PtyLink()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "rs485_labtest", "duo",
             "--port", link.port_a, "--slave-port", link.port_b,
             "--interface", interface, "--profile", "smoke", "--label", label,
             "--seed", "7", "--outdir", str(tmp_path)],
            capture_output=True, text=True, timeout=300)
    finally:
        link.close()

    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"

    with open(glob.glob(str(tmp_path / f"rs485_{label}_*.json"))[0],
              encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["meta"]["interface"] == interface
    assert doc["meta"]["duplex"] == "full"
    names = [r["name"] for r in doc["results"]]
    # full-duplex: sense tests de colisio, amb els de carrega simultania
    assert not any(n.startswith("collision_blind") for n in names)
    assert not any(n.startswith("post_collision") for n in names)
    fd = [r for r in doc["results"] if r["name"].startswith("fullduplex")]
    assert len(fd) == 2
    for r in fd:
        assert r["verdict"] == "PASS", r
        assert r["ok"] > 0 and r["junk_bytes"] == 0

    # la guia de l'informe ha de parlar d'aquesta interficie, no d'una altra
    md = open(glob.glob(str(tmp_path / f"rs485_{label}_*.md"))[0],
              encoding="utf-8").read()
    if interface == "rs232":
        assert "single-ended" in md
        assert "bias de failsafe insuficient" not in md
    else:
        assert "RS-485" in md or "RS-422" in md


def test_duo_smoke_battery_passes_on_virtual_link(tmp_path):
    link = PtyLink()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "rs485_labtest", "duo",
             "--port", link.port_a, "--slave-port", link.port_b,
             "--profile", "smoke", "--label", "ci_pty", "--seed", "42",
             "--outdir", str(tmp_path)],
            capture_output=True, text=True, timeout=300)
    finally:
        link.close()

    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"

    json_files = glob.glob(str(tmp_path / "rs485_ci_pty_*.json"))
    md_files = glob.glob(str(tmp_path / "rs485_ci_pty_*.md"))
    csv_files = glob.glob(str(tmp_path / "rs485_ci_pty_*_latencies.csv"))
    assert len(json_files) == 1 and len(md_files) == 1 and len(csv_files) == 1

    with open(json_files[0]) as f:
        doc = json.load(f)
    assert doc["meta"]["aborted"] is False
    assert doc["meta"]["seed"] == 42
    assert len(doc["results"]) == 18          # 12 del nucli + 6 desajustos de baud
    verdicts = {r["name"]: r["verdict"] for r in doc["results"]}
    assert all(v in ("PASS", "INFO") for v in verdicts.values()), verdicts
    assert "RESULTAT GLOBAL: PASS" in proc.stdout
