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

## Banco de dados

- Arquivo SQLite em `data/rh.db`
- Se existir a tabela legada `empregados` (versao Flask), os dados sao importados automaticamente para o modelo Django na migracao `0002`.

## Proximos passos sugeridos

1. Adicionar `horas_semanais_previstas` no cadastro de empregado.
2. Criar lancamento semanal de horas trabalhadas.
3. Gerar relatorio de horas previstas x horas trabalhadas por periodo.
