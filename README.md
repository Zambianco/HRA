# RH Local - Django + SQLite

Sistema de RH para uso local, com interface web e banco SQLite.

## Escopo atual

- Cadastro de empregados com:
  - `matricula`
  - `nome_completo`
  - `setor` (setores ativos)
  - `created_at`
- Tabela de setores da empresa com:
  - `nome`
  - `created_at`
  - `deactivated_at` (desativado quando preenchido)
- Listagem dos empregados cadastrados
- Validacao de campos obrigatorios
- Validacao de matricula unica

## Stack

- Django
- SQLite
- PyWebView (modo desktop)

## Como executar (local)

1. Criar e ativar ambiente virtual:

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
```

2. Instalar dependencias:

```powershell
pip install -r requirements.txt
```

3. Aplicar migracoes:

```powershell
python manage.py migrate
```

4. Rodar servidor local:

```powershell
python manage.py runserver 127.0.0.1:8000
```

5. Abrir no navegador:

`http://127.0.0.1:8000/empregados/`

## Executar como aplicativo desktop (PyWebView)

Com o ambiente virtual ativo e dependencias instaladas:

```powershell
python run_desktop.py
```

Esse comando sobe o Django localmente e abre a interface em uma janela nativa.
Ao iniciar, o app consulta automaticamente o `latest release` no GitHub e avisa quando existir uma versao mais nova.
Por padrao, o repositorio consultado e `Zambianco/HRA` (pode ser alterado com `HRA_GITHUB_REPO=owner/repo`).
Para alterar o banco, use o menu `Config. Banco` dentro do sistema:
- `online`: usa variaveis `DB_*` do ambiente (ex.: deploy com `.env`).
- `arquivo`: usa o caminho de um arquivo `.db` informado na tela.
Depois de salvar, reinicie o aplicativo para aplicar.

## Releases no GitHub

- Workflow: `.github/workflows/release.yml`
- Gatilho: push de tag no formato `vMAJOR.MINOR.PATCH` (ex.: `v1.0.0`)
- Pipeline: instala dependencias, roda `manage.py check`, roda `manage.py test` e cria a release automaticamente

### Publicar a primeira release (`v1.0.0`)

```powershell
git add .
git commit -m "chore: preparar release v1.0.0"
git push origin main
git tag v1.0.0
git push origin v1.0.0
```

## Banco de dados

- Modo padrao: SQLite em `data/rh.db`
- Variaveis suportadas:
  - `DATABASE_MODE=online|arquivo`
  - `DB_FILE_PATH=<caminho do .db>` (usado no modo `arquivo`)
  - `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` (usadas no modo `online`)
- Configuracao persistida localmente em `data/db_config.json`.
- Se existir a tabela legada `empregados` (versao Flask), os dados sao importados automaticamente para o modelo Django na migracao `0002`.

## Verificacao de codificacao de texto

Para validar rapidamente se os arquivos de texto estao em UTF-8 e sem mojibake:

```powershell
python tools/check_text_integrity.py
```

## Proximos passos sugeridos

1. Adicionar `horas_semanais_previstas` no cadastro de empregado.
2. Criar lancamento semanal de horas trabalhadas.
3. Gerar relatorio de horas previstas x horas trabalhadas por periodo.
