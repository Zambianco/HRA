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

## Banco de dados

- Arquivo SQLite em `data/rh.db`
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
