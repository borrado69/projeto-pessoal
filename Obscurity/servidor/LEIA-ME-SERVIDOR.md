# Obscurity: colocar os 3 servidores públicos online

Os servidores são o arquivo `servidor_publico.py` (só Python 3, sem pygame).
Ele abre 3 salas: **Público 1, 2 e 3**, portas **5555, 5556 e 5557** (TCP), **6 vagas** cada.

Para ficarem online, esse arquivo precisa rodar numa máquina ligada 24h com IP acessível
pela internet (um VPS, por exemplo). Depois você aponta o jogo para o IP/domínio dela.

## Opção A: VPS Linux (recomendado)

1. Copie os arquivos para o servidor:
   ```
   sudo mkdir -p /opt/obscurity && sudo useradd -r -s /usr/sbin/nologin obscurity
   sudo cp servidor_publico.py /opt/obscurity/
   sudo cp obscurity-servidor.service /etc/systemd/system/
   ```
2. Libere as portas **TCP 5555-5557**:
   - no firewall do servidor: `sudo ufw allow 5555:5557/tcp`
   - e no painel do provedor (Security List / Security Group / Firewall de rede).
     Em alguns provedores (ex.: Oracle Cloud) também é preciso liberar no iptables da máquina.
3. Ligue e deixe iniciar com o servidor:
   ```
   sudo systemctl daemon-reload
   sudo systemctl enable --now obscurity-servidor
   sudo systemctl status obscurity-servidor
   ```
   Se ele reiniciar ou travar, o systemd sobe de novo sozinho.

## Opção B: Docker

```
docker build -t obscurity-servidor .
docker run -d --restart always --name obscurity -p 5555-5557:5555-5557 obscurity-servidor
```

## Opção C: no seu próprio PC (teste / amigos)

```
python3 servidor_publico.py
```
Redirecione as portas 5555-5557 TCP no roteador para o seu PC e use seu IP público.
O PC precisa ficar ligado e o IP pode mudar.

## Ligar o jogo ao servidor

No `rpg.py`, troque a linha:
```
PUBLIC_HOST = "127.0.0.1"
```
pelo IP ou domínio do servidor (ex.: `PUBLIC_HOST = "203.0.113.10"`).
Ou, sem editar o código, coloque no `obscurity_config.json`:
```
"public_host": "203.0.113.10"
```
Todos os jogadores precisam do `rpg.py` com esse host (ou da config).

## Conferir se está no ar

Abra o jogo > MULTIPLAYER: os 3 cartões devem mostrar `0/6` e "6 vaga(s) livre(s)".
`OFFLINE` significa que a porta não está acessível: revise firewall/roteador e o IP.

## Proteções embutidas

- 6 vagas por servidor público; o 7º jogador recebe "servidor cheio".
- Máx. 12 conexões simultâneas por IP e 200 por servidor (contra flood).
- O protocolo é o mesmo do jogo (versão 1). Se mudar o protocolo no `rpg.py`,
  regenere o `servidor_publico.py` para manterem a mesma versão.
