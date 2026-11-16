"""Configurações centrais do Quarto Pilar."""
from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DADOS = RAIZ / "dados"
BRUTOS = DADOS / "brutos"          # cache local (não vai para o git)
SITE = RAIZ / "docs"               # GitHub Pages publica esta pasta
SITE_DADOS = SITE / "data"
CONFIG = RAIZ / "config"

# --- IF.Data (Olinda / BCB) -------------------------------------------------
OLINDA = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata"
OLINDA_VALORES = OLINDA + "/IfDataValores(AnoMes=@AnoMes,TipoInstituicao=@TipoInstituicao,Relatorio=@Relatorio)"
OLINDA_CADASTRO = OLINDA + "/IfDataCadastro(AnoMes=@AnoMes)"
IFDATA_REST = "https://www3.bcb.gov.br/ifdata/rest/arquivos"

TIPO_PRUDENCIAL = 1          # conglomerados prudenciais (recorte do Basileia)
RELATORIOS = {
    "1": "Resumo",
    "2": "Ativo",
    "3": "Passivo",
    "4": "Demonstração de Resultado",
    "5": "Informações de Capital",
}
ANO_INICIAL = 2014

# Universo monitorado: conglomerados com ativo total acima deste valor (R$)
ATIVO_MINIMO = 1_000_000_000

# Tipos de instituição monitorados (código Tcb do cadastro): bancos comerciais/múltiplos (B1),
# de investimento (B2), cooperativas singulares (B3S), de desenvolvimento (B4) e financeiras (N1).
# Ficam de fora corretoras (N2), instituições de pagamento (N4) e centrais de cooperativas (B3C).
UNIVERSO_TCB = {"B1", "B2", "B3S", "B4", "N1"}

# Requerimento mínimo de Basileia no Brasil (8% + 2,5% de conservação)
BASILEIA_MINIMO = 0.105

# --- IA ----------------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_MODELOS = [m for m in os.getenv(
    "GROQ_MODELOS", "openai/gpt-oss-120b,llama-3.3-70b-versatile,llama-3.1-8b-instant"
).split(",") if m]
GEMINI_MODELOS = [m for m in os.getenv(
    "GEMINI_MODELOS", "gemini-2.5-flash,gemini-2.5-flash-lite"
).split(",") if m]

# Limites de uso por execução diária (para ficar dentro da cota grátis)
MAX_CHAMADAS_EXTRACAO = int(os.getenv("MAX_CHAMADAS_EXTRACAO", "60"))
MAX_DOSSIES = int(os.getenv("MAX_DOSSIES", "15"))
MANCHETES_POR_CHAMADA = 15

# --- Notícias ------------------------------------------------------------------
BANCOS_NOTICIAS = int(os.getenv("BANCOS_NOTICIAS", "60"))   # quantos bancos buscar por dia
JANELA_NOTICIAS_DIAS = 45                                  # quanto tempo os eventos pesam no score
