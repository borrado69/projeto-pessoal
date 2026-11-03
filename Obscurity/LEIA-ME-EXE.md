# Obscurity: criar o .exe (Windows)

## Jeito mais fácil: duplo clique
1. Coloque `rpg.py` e `CRIAR_EXE.bat` na mesma pasta.
2. Dê dois cliques em **CRIAR_EXE.bat**. Ele instala o que falta (pygame e PyInstaller) e gera o jogo.
3. Pronto: aparece **Obscurity.exe** na mesma pasta. Pode copiar só ele para qualquer PC com Windows,
   sem precisar de Python.

Precisa só do **Python 3.12** instalado, com "Add python.exe to PATH" marcado:
https://www.python.org/downloads/

## Sem criar exe: JOGAR.bat
Dê dois cliques em **JOGAR.bat**. Ele instala o pygame na primeira vez e abre o jogo.

## Sem Python no PC: build na nuvem (GitHub)
1. Suba `rpg.py` e a pasta `.github` para um repositório no GitHub.
2. Aba **Actions > Criar Obscurity.exe > Run workflow**.
3. Quando terminar, baixe o **Obscurity-windows** em "Artifacts". Dentro está o Obscurity.exe.

## Saves e configurações
Ficam na mesma pasta do `.exe` (`obscurity_saves.json`, `obscurity_config.json`).
Se o jogo fechar com erro, o motivo fica em `obscurity_log.txt`, ao lado do exe.
Não mova só o exe para outra pasta se quiser manter os saves: leve os `.json` junto.

## Avisos
- O Windows (SmartScreen) e alguns antivírus podem avisar sobre "app desconhecido", porque o exe
  não é assinado digitalmente. Isso é comum em jogos feitos com PyInstaller.
  Clique em "Mais informações > Executar assim mesmo".
- A primeira abertura do exe é um pouco mais lenta (ele se descompacta sozinho).
- Para o multiplayer público, lembre de ajustar `PUBLIC_HOST` no `rpg.py` ANTES de gerar o exe.
