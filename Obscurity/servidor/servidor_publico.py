#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OBSCURITY - servidor público independente (não precisa de pygame).
Sobe 3 servidores (portas 5555, 5556, 5557), 6 vagas cada.

    python3 servidor_publico.py

Libere as portas 5555-5557 (TCP) no firewall / roteador / painel do provedor.
No jogo, ajuste PUBLIC_HOST (rpg.py) ou "public_host" (obscurity_config.json) para o IP/domínio desta máquina.
"""
import json
import math
import queue
import socket
import sys
import threading
import time

# ===================================================================== REDE (multiplayer)
PROTO = 1
DEFAULT_PORT = 5555
MAX_PLAYERS = 12
# --- servidores PÚBLICOS (3 salas fixas, 6 vagas cada, entrada instantânea) ---
PUBLIC_MAX = 6                                   # vagas de cada servidor público
PUBLIC_HOST = "127.0.0.1"                        # <<< TROQUE pelo IP/domínio da máquina que roda:  python rpg.py --public
PUBLIC_SERVERS = (("Público 1", 5555), ("Público 2", 5556), ("Público 3", 5557))   # (nome, porta TCP)
SNAP_DT = 0.05
HEROES_OK = ("knight", "ranger", "mage", "guardian", "rogue")
RACES_OK = ("human", "elf", "dwarf", "orc", "halfling", "tiefling")
ROOMS = ("lobby", "arena", "none")
MAX_LINE = 16384
MAX_PER_IP = 12                                  # conexões simultâneas por IP (protege o servidor público)
MAX_CONNS = 200                                  # conexões totais por servidor


def encode(obj):
    return (json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def parse_addr(text, default_port=DEFAULT_PORT):
    """'ip', 'ip:porta' ou 'nome.dominio:porta' -> (host, porta). Levanta ValueError se inválido."""
    t = (text or "").strip() or "127.0.0.1"
    host, port = t, default_port
    if t.count(":") == 1:
        h, p = t.split(":")
        host = h or "127.0.0.1"
        port = int(p)
    if not host or not (0 < port < 65536):
        raise ValueError("endereço inválido")
    return host, port


def _num(v, lo, hi, default=0.0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f in (math.inf, -math.inf):
        return default
    return max(lo, min(hi, f))


def _clean_text(s, n):
    s = "".join(ch for ch in str(s) if ch.isprintable())
    return s.strip()[:n]


def query_server(host, port, timeout=1.5):
    """Pergunta a um servidor quantos jogadores ele tem. Retorna {'n','p','max'} ou None se estiver offline."""
    try:
        sk = socket.create_connection((host, port), timeout=timeout)
    except Exception:
        return None
    res = None
    try:
        sk.settimeout(timeout)
        sk.sendall(encode({"t": "info", "v": PROTO}))
        buf = b""
        while b"\n" not in buf and len(buf) < MAX_LINE:
            d = sk.recv(1024)
            if not d:
                break
            buf += d
        m = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
        if isinstance(m, dict) and m.get("t") == "info":
            res = {"n": _clean_text(m.get("n"), 16), "p": int(_num(m.get("p"), 0, 999)),
                   "max": int(_num(m.get("max"), 1, 999, PUBLIC_MAX))}
    except Exception:
        res = None
    try:
        sk.close()
    except OSError:
        pass
    return res


# =================================================================== SERVIDOR
class _Conn:
    def __init__(self, sock, addr):
        self.sock, self.addr = sock, addr
        self.out = queue.Queue(maxsize=400)
        self.id = None
        self.name, self.hero, self.race = "", "knight", "human"
        self.st = {"room": "none", "x": 4.5, "y": 4.5, "hd": 0.0, "mv": 0, "lg": 0.0, "rl": -1.0,
                   "dead": 0, "hp": 1, "pm": 1}
        self.k = self.d = 0
        self.alive = True
        self.t_atk = 0.0
        self.t_died = 0.0

    def send(self, obj, droppable=False):
        if not self.alive:
            return
        try:
            self.out.put_nowait(encode(obj))
        except queue.Full:
            if not droppable:
                self.close()

    def close(self):
        if not self.alive:
            return
        self.alive = False
        try:
            self.out.put_nowait(None)
        except queue.Full:
            pass
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class Server:
    def __init__(self, port=DEFAULT_PORT, host="0.0.0.0", log=print, max_players=MAX_PLAYERS, name=""):
        self.port, self.host, self.log = port, host, log
        self.max_players, self.name = max_players, name
        self.lock = threading.RLock()
        self.conns = []
        self.next_id = 1
        self.running = False
        self.lsock = None

    # ---- ciclo de vida
    def start(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.port))          # OSError se a porta estiver ocupada
        s.listen(16)
        self.lsock, self.running = s, True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        threading.Thread(target=self._snap_loop, daemon=True).start()
        self.log(f"[obscurity] servidor ouvindo em {self.host}:{self.port}")
        return self

    def stop(self):
        self.running = False
        try:
            self.lsock.close()
        except Exception:
            pass
        with self.lock:
            for c in list(self.conns):
                c.close()
            self.conns.clear()

    # ---- helpers
    def count(self):
        with self.lock:
            return sum(1 for c in self.conns if c.id is not None)

    def players(self):
        with self.lock:
            return [dict(id=c.id, n=c.name, h=c.hero, r=c.race, k=c.k, d=c.d, **c.st)
                    for c in self.conns if c.id is not None]

    def broadcast(self, obj, room=None, skip=None, droppable=False):
        with self.lock:
            targets = [c for c in self.conns if c.id is not None and c is not skip
                       and (room is None or c.st["room"] == room)]
        for c in targets:
            c.send(obj, droppable)

    def _drop(self, c):
        with self.lock:
            was = c in self.conns
            if was:
                self.conns.remove(c)
        c.close()
        if was and c.id is not None:
            self.log(f"[obscurity] {c.name} (#{c.id}) saiu")
            self.broadcast({"t": "leave", "id": c.id, "n": c.name})

    # ---- threads
    def _accept_loop(self):
        while self.running:
            try:
                sock, addr = self.lsock.accept()
            except OSError:
                break
            sock.settimeout(30)
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            c = _Conn(sock, addr)
            with self.lock:
                if len(self.conns) >= MAX_CONNS or sum(1 for o in self.conns if o.addr[0] == addr[0]) >= MAX_PER_IP:
                    sock.close()                  # excesso de conexões (abuso/flood)
                    continue
                self.conns.append(c)
            threading.Thread(target=self._writer, args=(c,), daemon=True).start()
            threading.Thread(target=self._reader, args=(c,), daemon=True).start()

    def _writer(self, c):
        try:
            while True:
                data = c.out.get()
                if data is None:
                    break
                c.sock.sendall(data)
        except OSError:
            pass
        self._drop(c)

    def _reader(self, c):
        buf = b""
        try:
            while c.alive:
                chunk = c.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > MAX_LINE and b"\n" not in buf:
                    break
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        m = json.loads(line.decode("utf-8"))
                    except ValueError:
                        continue
                    if isinstance(m, dict):
                        self._handle(c, m)
                        if not c.alive:
                            break
        except OSError:
            pass
        self._drop(c)

    def _snap_loop(self):
        while self.running:
            time.sleep(SNAP_DT)
            ps = self.players()
            if ps:
                self.broadcast({"t": "snap", "p": ps}, droppable=True)

    # ---- mensagens
    def _handle(self, c, m):
        t = m.get("t")
        if c.id is None and t == "info":              # consulta da lista de servidores (não ocupa vaga)
            c.send({"t": "info", "n": self.name or f"Servidor {self.port}", "p": self.count(), "max": self.max_players})
            return
        if c.id is None:
            if t != "hello":
                c.send({"t": "err", "msg": "esperava hello"})
                c.close()
                return
            if m.get("v") != PROTO:
                c.send({"t": "err", "msg": f"versão do protocolo incompatível (servidor {PROTO})"})
                c.close()
                return
            with self.lock:
                if sum(1 for o in self.conns if o.id is not None) >= self.max_players:
                    c.send({"t": "err", "msg": "servidor cheio"})
                    c.close()
                    return
                c.id = self.next_id
                self.next_id += 1
            c.name = _clean_text(m.get("name"), 12) or f"Jogador{c.id}"
            c.hero = m.get("hero") if m.get("hero") in HEROES_OK else "knight"
            c.race = m.get("race") if m.get("race") in RACES_OK else "human"
            c.send({"t": "welcome", "id": c.id, "proto": PROTO, "players": self.players()})
            self.broadcast({"t": "join", "id": c.id, "n": c.name}, skip=c)
            self.log(f"[obscurity] {c.name} (#{c.id}) entrou de {c.addr[0]}")
            return

        if t == "state":
            st = c.st
            room = m.get("room")
            st["room"] = room if room in ROOMS else "none"
            st["x"], st["y"] = _num(m.get("x"), -3, 25, 4.5), _num(m.get("y"), -3, 25, 4.5)
            st["hd"] = _num(m.get("hd"), -7, 7)
            st["mv"] = 1 if m.get("mv") else 0
            st["lg"] = _num(m.get("lg"), 0, 2)
            st["rl"] = _num(m.get("rl"), -1, 1.5, -1.0)
            st["dead"] = 1 if m.get("dead") else 0
            st["hp"] = int(_num(m.get("hp"), 0, 9999, 1))
            st["pm"] = int(_num(m.get("pm"), 1, 9999, 1))
        elif t in ("atk", "shot"):
            if c.st["room"] != "arena" or c.st["dead"]:
                return
            now = time.time()
            if now - c.t_atk < 0.10:                  # limite de cadência
                return
            c.t_atk = now
            out = {"t": t, "id": c.id,
                   "x": _num(m.get("x"), -3, 25), "y": _num(m.get("y"), -3, 25), "ang": _num(m.get("ang"), -7, 7),
                   "dmg": int(_num(m.get("dmg"), 0, 150)), "crit": 1 if m.get("crit") else 0}
            if t == "atk":
                out["reach"] = _num(m.get("reach"), 0, 4, 1.9)
                out["arc"] = _num(m.get("arc"), 0, 2, 1.15)
            else:
                out["kind"] = m.get("kind") if m.get("kind") in ("arrow", "bolt", "snipe", "fireball") else "arrow"
                out["spd"] = _num(m.get("spd"), 1, 30, 12)
                out["rng"] = _num(m.get("rng"), 1, 20, 10)
                out["pierce"] = 1 if m.get("pierce") else 0
            self.broadcast(out, room="arena", skip=c)
        elif t == "hurt":                              # a vítima avisa que tomou dano (feedback para todos)
            if c.st["room"] != "arena":
                return
            self.broadcast({"t": "hurt", "id": c.id, "by": int(_num(m.get("by"), 0, 10 ** 9)),
                            "dmg": int(_num(m.get("dmg"), 0, 150)), "crit": 1 if m.get("crit") else 0,
                            "x": _num(m.get("x"), -3, 25), "y": _num(m.get("y"), -3, 25)}, room="arena", skip=c)
        elif t == "died":
            if c.st["room"] != "arena":
                return
            if time.time() - c.t_died < 1.0:              # evita contar a mesma morte duas vezes
                return
            c.t_died = time.time()
            by = int(_num(m.get("by"), 0, 10 ** 9))
            c.d += 1
            killer = None
            with self.lock:
                for o in self.conns:
                    if o.id == by and o is not c:
                        o.k += 1
                        killer = o
            self.broadcast({"t": "kill", "by": by, "bn": killer.name if killer else "", "victim": c.id, "vn": c.name})
        elif t == "chat":
            txt = _clean_text(m.get("text"), 100)
            if txt:
                self.broadcast({"t": "chat", "id": c.id, "n": c.name, "text": txt})


# =================================================================== CLIENTE
class NetClient:
    """Conexão em thread. O jogo chama poll() a cada frame e send() quando quiser."""

    def __init__(self):
        self.sock = None
        self.inbox = queue.Queue()
        self.status = "idle"          # idle | connecting | connected | error | closed
        self.err = ""
        self.id = None
        self._gen = 0
        self._slock = threading.Lock()

    def connect(self, host, port, hello):
        self.close()
        self._gen += 1
        self.status, self.err, self.id = "connecting", "", None
        threading.Thread(target=self._run, args=(host, port, hello, self._gen), daemon=True).start()

    def _run(self, host, port, hello, gen):
        try:
            s = socket.create_connection((host, port), timeout=6)
        except Exception as e:
            if gen == self._gen:
                self.status, self.err = "error", f"Não foi possível conectar em {host}:{port} ({getattr(e, 'strerror', None) or e})"
            return
        s.settimeout(30)
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        if gen != self._gen:
            s.close()
            return
        self.sock = s
        try:
            s.sendall(encode(hello))
            buf = b""
            while gen == self._gen:
                data = s.recv(8192)
                if not data:
                    raise ConnectionError("o servidor fechou a conexão")
                buf += data
                if len(buf) > 4 * MAX_LINE * 8:
                    raise ConnectionError("mensagem grande demais")
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        m = json.loads(line.decode("utf-8"))
                    except ValueError:
                        continue
                    if not isinstance(m, dict):
                        continue
                    if m.get("t") == "welcome":
                        self.id, self.status = m.get("id"), "connected"
                    elif m.get("t") == "err":
                        self.err = str(m.get("msg", "erro do servidor"))
                    self.inbox.put(m)
        except socket.timeout:
            if gen == self._gen:
                self.err = self.err or "tempo esgotado (sem resposta do servidor)"
        except Exception as e:
            if gen == self._gen:
                self.err = self.err or str(e) or "conexão perdida"
        finally:
            if gen == self._gen:
                self.status = "closed" if self.status == "connected" else "error"
                self.err = self.err or "conexão encerrada"
            try:
                s.close()
            except OSError:
                pass

    def send(self, obj):
        s = self.sock
        if s is None or self.status not in ("connecting", "connected"):
            return False
        try:
            with self._slock:
                s.sendall(encode(obj))
            return True
        except OSError:
            self.status, self.err = "closed", self.err or "conexão perdida"
            return False

    def poll(self):
        out = []
        try:
            while True:
                out.append(self.inbox.get_nowait())
        except queue.Empty:
            return out

    def close(self):
        self._gen += 1
        s, self.sock = self.sock, None
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass
        self.status = "idle"
        try:
            while True:
                self.inbox.get_nowait()
        except queue.Empty:
            pass




def run_dedicated_server(argv):
    """python rpg.py --server [porta]  ->  servidor dedicado (sem abrir o jogo)."""
    if "--public" in argv:                        # os 3 servidores públicos de uma vez (6 vagas cada)
        srvs = []
        for nm, pt in PUBLIC_SERVERS:
            try:
                srvs.append(Server(pt, max_players=PUBLIC_MAX, name=nm).start())
            except OSError as e:
                print(f"Não foi possível abrir {nm} na porta {pt}: {e}")
        if not srvs:
            sys.exit(1)
        print(f"{len(srvs)} servidores públicos no ar ({PUBLIC_MAX} vagas cada). Libere as portas "
              + ", ".join(str(sv.port) for sv in srvs) + " TCP no firewall/roteador.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            for sv in srvs:
                sv.stop()
        return
    port = DEFAULT_PORT
    args = [x for x in argv[1:] if x.lstrip("-").isdigit()]
    if args:
        port = int(args[0])
    try:
        srv = Server(port).start()
    except OSError as e:
        print(f"Não foi possível abrir a porta {port}: {e}")
        sys.exit(1)
    print(f"Passe aos amigos:  {lan_ip()}:{port}   (na internet: libere/redirecione a porta {port} TCP no roteador)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()




if __name__ == "__main__":
    run_dedicated_server(["servidor_publico.py", "--public"])
