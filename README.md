# Ferramenta de Metadados — Fotos & Vídeos

Remoção e substituição de metadados de fotos e vídeos, sem perda de qualidade.

## O que faz

- Remove ou substitui metadados de fotos e vídeos (câmera, data, GPS, software)
- Suporta JPG, PNG, HEIC, MP4, MOV, AVI, MKV
- Processamento em massa
- Sem perda de qualidade (codec copy para vídeos, qualidade máxima para fotos)
- 3 modos: remover tudo, substituir por dados aleatórios, ou personalizar

## Como usar

```bash
# 1. Clone o repositório
git clone https://github.com/lpgaspar25/metadata-remover.git
cd metadata-remover

# 2. Instale as dependências
pip3 install flask Pillow piexif mutagen

# 3. Instale o ffmpeg (necessário para vídeos)
# macOS:
brew install ffmpeg
# Ubuntu/Debian:
sudo apt install ffmpeg
# Windows:
winget install ffmpeg

# 4. Inicie a ferramenta
python3 app.py

# 5. Abra no navegador
# http://localhost:5555
```

## Modos

| Modo | Descrição |
|------|-----------|
| Remover Tudo | Remove todos os metadados. Arquivo fica completamente limpo. |
| Substituir Aleatório | Substitui por metadados novos e aleatórios (câmera, data, GPS, software). |
| Personalizado | Você escolhe a câmera, data, GPS e software que serão inseridos. |
