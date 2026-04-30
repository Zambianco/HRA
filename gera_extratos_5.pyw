import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib.utils import simpleSplit
import tkinter as tk
from tkinter import filedialog
import os
import sys
import tkinter.messagebox as msgbox
import time

def timedelta_para_decimal(td):
    return td.total_seconds() / 3600

def formatar_horas_livres(total_horas):
    """
    Formata horas totais no formato HH:MM sem converter em dias
    Aceita tanto timedelta quanto strings no formato 'X days HH:MM:SS' ou HH:MM:SS
    """
    if pd.isna(total_horas):
        return "00:00"
    
    # Se for um timedelta ou string com dias
    if 'days' in str(total_horas) or (isinstance(total_horas, str) and ' ' in total_horas):
        parts = str(total_horas).split()
        if len(parts) > 1:  # Tem dias
            days = int(parts[0])
            hhmmss = parts[2]
        else:  # Só tem HH:MM:SS
            hhmmss = parts[0]
        
        hours, minutes, _ = map(int, hhmmss.split(':'))
        total_hours = days * 24 + hours
        return f"{total_hours:02d}:{minutes:02d}"
    
    # Se já estiver no formato HH:MM:SS sem dias
    if isinstance(total_horas, str) and ':' in total_horas:
        parts = total_horas.split(':')
        if len(parts) == 3:  # HH:MM:SS
            hours, minutes, _ = map(int, parts)
            return f"{hours:02d}:{minutes:02d}"
        elif len(parts) == 2:  # HH:MM
            return total_horas
    
    # Se for decimal (horas)
    if isinstance(total_horas, (float, int)):
        return decimal_para_hhmm(total_horas)
    
    return "00:00"


def hhmm_para_decimal(hora_str):
    """
    Converte horas no formato HH:MM para decimal (float)
    Exemplo: "10:30" → 10.5
    """
    if pd.isna(hora_str) or hora_str in ("", "0:00", "00:00"):
        return 0.0
    
    if pd.isnull(hora_str) or hora_str in ['', '00:00']:
        return 0.0
    
    try:
        horas, minutos = map(float, str(hora_str).split(':'))
        return horas + minutos/60
    except:
        return 0.0
    

def calcular_horas_decimais(hora_str):
    """
    Converte horas no formato HH:MM para decimal para cálculos.
    Exemplo: "32:30" → 32.5
    """
    if pd.isna(hora_str) or hora_str == "":
        return 0.0
    
    if isinstance(hora_str, (float, int)):
        return float(hora_str)  # Mantém compatibilidade
    
    try:
        horas, minutos = map(float, str(hora_str).split(':'))
        return horas + minutos/60
    except:
        return 0.0


def formatar_horas(hora_str):
    """
    Formata horas no formato HH:MM para exibição consistente.
    Também pode converter de decimal para HH:MM se necessário (para compatibilidade).
    """
    if isinstance(hora_str, str) and ':' in hora_str:
        # Já está no formato HH:MM
        horas, minutos = map(int, hora_str.split(':'))
        return f"{horas:02d}:{minutos:02d}"
    elif isinstance(hora_str, (float, int)):
        # Mantém compatibilidade com decimais (se necessário)
        return decimal_para_hhmm(hora_str)
    return "00:00"  # Default para valores inválidos



# --- Constantes ---
MESES_ORDEM = [
    'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
    'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'
]
PERIODO_RELATORIO = "JULHO a DEZEMBRO de 2025"
MARGEM = 2 * cm
LINHA_ALTURA = 0.7 * cm

# --- Funções de Utilidade ---
def salvar_pdf_seguro(c, arquivo_pdf):
    """Tenta salvar o PDF, pedindo para fechar se estiver em uso."""
    while True:
        try:
            c.save()
            break
        except PermissionError:
            resposta = msgbox.askretrycancel(
                "Arquivo em uso",
                "O arquivo relatorio.pdf está aberto e não pode ser sobrescrito.\n\n"
                "Por favor, feche o PDF e pressione 'Tentar novamente' para continuar."
            )
            if not resposta:
                msgbox.showinfo("Cancelado", "A exportação foi cancelada pelo usuário.")
                exit()
            time.sleep(1)

def checar_duplicidade_mes(historico):
    """Verifica se há meses duplicados para a mesma matrícula."""
    duplicados = historico.groupby(['matricula', 'mes']).size().reset_index(name='count')
    duplicados = duplicados[duplicados['count'] > 1]

    if not duplicados.empty:
        erro_txt = "Há meses repetidos para o(s) funcionário(s) abaixo:\n\n"
        erro_txt += "\n".join(
            f"Matrícula {row['matricula']} - mês: {row['mes'].capitalize()}" 
            for _, row in duplicados.iterrows()
        )
        erro_txt += "\n\nA geração do relatório foi ABORTADA.\n\nCorrija a planilha antes de prosseguir."
        msgbox.showerror("Erro de Duplicidade de Mês", erro_txt)
        exit()


def decimal_para_hhmm(decimal_horas):
    """
    Converte horas decimais para formato HH:MM alinhado pelo ':'
    Exemplo:
        -45.5 → "-45:30"
         6.2 → " 06:12"
    """
    if pd.isna(decimal_horas) or decimal_horas == 0:
        return " 00:00"   # Um espaço à esquerda, para alinhar lado a lado com negativos

    negativo = decimal_horas < 0
    decimal_horas = abs(decimal_horas)
    horas = int(decimal_horas)
    minutos = int(round((decimal_horas - horas) * 60))

    if minutos == 60:
        horas += 1
        minutos = 0

    resultado = f"{horas:02d}:{minutos:02d}"

    # Se for negativo, coloca sinal antes; se for positivo, espaço. Assim todos têm 6 caracteres.
    return f"-{resultado}" if negativo else f" {resultado}"


def calcular_saldo_acumulado(dados_func):
    saldo_acumulado = []
    saldo_anterior = 0.0
    for idx, row in dados_func.iterrows():
        banco = timedelta_para_decimal(row['hora_banco'])
        acrescimo = timedelta_para_decimal(row['banco_acrescimo'])
        desconto = timedelta_para_decimal(row['horas_descontadas'])
        
        saldo_atual = saldo_anterior + banco + acrescimo - desconto
        saldo_acumulado.append(saldo_atual)
        saldo_anterior = saldo_atual
    return saldo_acumulado



def preparar_dados_funcionario(historico, matricula):
    dados_func = historico[historico['matricula'] == matricula].copy()

    MESES_ORDEM = [
        'janeiro','fevereiro','março','abril','maio','junho',
        'julho','agosto','setembro','outubro','novembro','dezembro'
    ]
    dados_func['mes'] = pd.Categorical(dados_func['mes'], categories=MESES_ORDEM, ordered=True)
    dados_func = dados_func.sort_values('mes')

    def td2h(v):
        if pd.isna(v): return 0.0
        if hasattr(v, 'total_seconds'): return v.total_seconds()/3600.0
        s = str(v)
        if 'days' in s or 'day' in s:
            parts = s.split()
            days = int(parts)
            hh, mm, ss = map(int, parts.split(':'))
            return days*24 + hh + mm/60 + ss/3600
        if ':' in s:
            hh, mm, *rest = s.split(':')
            ss = float(rest) if rest else 0
            return float(hh) + float(mm)/60 + float(ss)/3600
        try: return float(s)
        except: return 0.0

    # saldo por linha: SOMENTE banco - descontos
    dados_func['saldo_linha'] = (
        dados_func['hora_banco'].apply(td2h) * 1.6
        - dados_func['horas_descontadas'].apply(td2h)
    )
    return dados_func




# --- Funções de Geração de PDF ---
def criar_cabecalho(c, matricula, nome, y_pos):
    """Cria o cabeçalho do relatório."""
    largura_pagina = A4[0]
    
    c.setFont("Courier-Bold", 14)
    c.drawCentredString(largura_pagina / 2, y_pos, "BANCO DE HORAS")
    y_pos -= 1.0 * cm
    
    c.setFont("Courier", 12)
    c.drawCentredString(largura_pagina / 2, y_pos, PERIODO_RELATORIO)
    y_pos -= 1.2 * cm
    
    c.setFont("Courier-Bold", 12)
    c.drawString(MARGEM, y_pos, f"{matricula} - {nome}")
    y_pos -= 1.0 * cm
    
    c.drawString(MARGEM, y_pos, "Saldo de horas mês a mês")
    return y_pos - 1.0 * cm

def criar_cabecalho_tabela(c, y_pos):
    """Cria o cabeçalho da tabela de dados."""
    col_larguras = [3.2*cm, 3.2*cm, 4.5*cm, 3.5*cm, 3.0*cm]
    headers = ["Mês", "horas\nbanco", "horas\ncom acréscimo", "descontos", "saldo"]
    
    c.setFont("Courier-Bold", 11)
    x = MARGEM
    
    for i, header in enumerate(headers):
        partes = header.split('\n')
        for parte_idx, parte in enumerate(partes):
            c.drawString(x + 0.3 * cm, y_pos - (parte_idx * 10), parte)
        x += col_larguras[i]
    
    max_linhas_header = max(header.count('\n') + 1 for header in headers)
    y_pos -= (max_linhas_header * 10)
    
    c.setLineWidth(1)
    c.line(MARGEM, y_pos - 5, MARGEM + sum(col_larguras) - 20, y_pos - 5)
    return y_pos - LINHA_ALTURA, col_larguras


def criar_linhas_tabela(c, dados_func, y_pos, col_larguras):
    print(dados_func[['mes', 'hora_banco', 'banco_acrescimo', 'horas_descontadas']])
    """Cria as linhas da tabela com o novo cálculo de saldo"""
    c.setFont("Courier", 10)
    for _, row in dados_func.iterrows():
        x = MARGEM
        dados_linha = [
            row['mes'].capitalize(),
            formatar_horas_livres(row['hora_banco']),
            formatar_horas_livres(row['banco_acrescimo']),
            formatar_horas_livres(row['horas_descontadas']),
            decimal_para_hhmm(row['saldo_linha'])  # Já calculado com a nova regra
        ]
        
        for i, dado in enumerate(dados_linha):
            c.drawString(x + 0.3 * cm, y_pos, str(dado))
            x += col_larguras[i]
        
        y_pos -= LINHA_ALTURA
        
        if y_pos < 5 * cm:
            c.showPage()
            y_pos = A4[1] - 2 * cm
    
    return y_pos


def criar_rodape(c, y_pos):
    """Cria o rodapé com observações."""
    largura_pagina = A4[0]
    x_final = largura_pagina - MARGEM
    y_rodape = 1.5 * cm

    c.setLineWidth(0.6)
    c.line(MARGEM, y_rodape + 40, x_final, y_rodape + 40)

    c.setFont("Helvetica-Bold", 9)
    c.drawString(MARGEM, y_rodape + 26, "OBSERVAÇÕES")

    explicacoes = [
        ("hora banco", "metade do total de horas extras trabalhadas no mês"),
        ("horas com acréscimo", "metade do valor das horas trabalhadas no mês com acréscimo de 60%, o que vai ser pago como hora extra do respectivo mês"),
        ("descontos", "total de faltas no mês"),
        ("saldo", "saldo acumulado do mês, considerando horas banco menos descontos, acumulado mês a mês"),
    ]

    y_texto = y_rodape + 12
    max_largura = largura_pagina - MARGEM*2 - 10
    
    for nome, explicacao in explicacoes:
        c.setFont("Helvetica-Bold", 8)
        c.drawString(MARGEM, y_texto, f"{nome}: ")
        largura_nome = c.stringWidth(f"{nome}: ", "Helvetica-Bold", 8)
        
        c.setFont("Helvetica", 8)
        linhas = simpleSplit(explicacao, "Helvetica", 8, max_largura - largura_nome)
        for linha in linhas:
            c.drawString(MARGEM + largura_nome, y_texto, linha)
            y_texto -= 9
            largura_nome = 0
        y_texto -= 3


def criar_totais(c, dados_func, y_pos, col_larguras):
    """Exibe o total (soma dos saldos por linha)"""
    if not dados_func.empty:
        total = dados_func['saldo_linha'].sum()
        c.setLineWidth(0.5)
        c.line(MARGEM, y_pos + 10, MARGEM + sum(col_larguras) - 20, y_pos + 10)

        # rótulo TOTAL na primeira coluna
        c.setFont("Courier-Bold", 10)
        c.drawString(MARGEM + 0.3*cm, y_pos, "TOTAL")
        
        c.setFont("Courier-Bold", 10)
        c.drawString(MARGEM + sum(col_larguras[:4]) + 0.3*cm, y_pos, decimal_para_hhmm(total))
    return y_pos - LINHA_ALTURA - 0.5 * cm


def gerar_pdf_funcionario(c, matricula, nome, relatorio_mes):
    """Gera o PDF para um único funcionário."""
    y_pos = A4[1] - 2 * cm
    
    # Cabeçalho
    y_pos = criar_cabecalho(c, matricula, nome, y_pos)
    
    # Preparar dados
    dados_func = preparar_dados_funcionario(relatorio_mes, matricula)
    
    # Tabela
    y_pos, col_larguras = criar_cabecalho_tabela(c, y_pos)
    y_pos = criar_linhas_tabela(c, dados_func, y_pos, col_larguras)
    y_pos = criar_totais(c, dados_func, y_pos, col_larguras)
    
    # Rodapé
    criar_rodape(c, y_pos)
    c.showPage()


# --- Fluxo Principal ---
def main():
    # Seleção do arquivo
    root = tk.Tk()
    root.withdraw()
    arquivo = filedialog.askopenfilename(
        title="Selecione o arquivo Excel",
        filetypes=(("Arquivos Excel", "*.xlsx;*.xls"), ("Todos os arquivos", "*.*"))
    )
    if not arquivo:
        print("Nenhum arquivo selecionado. Encerrando o programa.")
        exit()

    # Carregar dados
    empregados = pd.read_excel(arquivo, sheet_name='empregados')
    historico = pd.read_excel(arquivo, sheet_name='historico')
    historico['mes'] = historico['mes'].str.lower().str.strip()  # Normaliza os nomes dos meses
    
    # Verifica se todos os meses estão na lista MESES_ORDEM
    meses_invalidos = set(historico['mes']) - set(MESES_ORDEM)
    if meses_invalidos:
        msgbox.showerror("Erro", f"Meses inválidos encontrados: {', '.join(meses_invalidos)}")
        exit()

    checar_duplicidade_mes(historico)

    # Processar dados
    relatorio_mes = (
        historico.groupby(['matricula', 'nome', 'mes'], as_index=False)
        [['hora_banco', 'banco_acrescimo', 'horas_descontadas']].sum()
    ).sort_values(['matricula', 'mes'])

    # Gerar PDF
    arquivo_pdf = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'relatorio.pdf')
    c = canvas.Canvas(arquivo_pdf, pagesize=A4)
    
    for _, row in empregados.iterrows():
        gerar_pdf_funcionario(c, row['matricula'], row['nome'], relatorio_mes)
    
    salvar_pdf_seguro(c, arquivo_pdf)
    
    # Abrir o PDF
    if sys.platform.startswith('darwin'):
        os.system(f'open "{arquivo_pdf}"')
    elif os.name == 'nt':
        os.startfile(arquivo_pdf)
    elif os.name == 'posix':
        os.system(f'xdg-open "{arquivo_pdf}"')

if __name__ == "__main__":
    main()
