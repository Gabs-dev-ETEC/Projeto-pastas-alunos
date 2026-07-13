"""
Gera o PDF de capacitacao de um aluno a partir de um modelo .docx.

Como funciona:
1. Cada curso tem um modelo .docx (ex: modelo_capacitacao_eletrotecnica.docx)
   com os marcadores {{NOME}} e {{CPF}} no lugar do nome/CPF do aluno.
   As datas do modelo NAO mudam -- ficam fixas, como voces ja fazem hoje.
2. Preenchemos uma copia do modelo trocando os marcadores pelos dados
   do aluno (find & replace direto no XML do docx).
3. Convertemos essa copia para PDF usando o LibreOffice em modo headless
   (precisa estar instalado no servidor -- ver Dockerfile).

Para cadastrar um novo curso, monte o .docx do jeito que ja e feito hoje,
troque o nome e o CPF do aluno de exemplo por {{NOME}} e {{CPF}} (usando
Localizar e Substituir no proprio Word mesmo resolve, contanto que o nome
e o cpf estejam escritos de forma identica em todas as ocorrencias), e
salve em TEMPLATES_DIR com o nome sanitizado do curso.
"""

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent.parent / "templates_capacitacao"


class ModeloNaoEncontrado(Exception):
    pass


def _caminho_modelo(curso_sanitizado: str) -> Path:
    caminho = TEMPLATES_DIR / f"modelo_capacitacao_{curso_sanitizado}.docx"
    if not caminho.exists():
        raise ModeloNaoEncontrado(
            f"Nao existe modelo de capacitacao para o curso '{curso_sanitizado}' "
            f"em {caminho}. Cadastre o arquivo .docx com os marcadores "
            f"{{{{NOME}}}} e {{{{CPF}}}} nesse caminho."
        )
    return caminho


def formatar_cpf(cpf: str) -> str:
    """
    Recebe o CPF em qualquer formato (com ou sem pontuacao) e devolve
    formatado como 000.000.000-00.
    """
    digitos = "".join(c for c in cpf if c.isdigit())
    if len(digitos) != 11:
        return cpf  # devolve como veio, nao tenta adivinhar
    return f"{digitos[0:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:11]}"


def _preencher_docx(modelo_path: Path, destino_path: Path, nome: str, cpf: str) -> None:
    """
    Copia o modelo substituindo {{NOME}} e {{CPF}} pelos dados do aluno,
    editando o XML dentro do .docx diretamente (docx e um zip).
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(modelo_path) as z:
            z.extractall(tmp_path)

        doc_xml_path = tmp_path / "word" / "document.xml"
        conteudo = doc_xml_path.read_text(encoding="utf-8")
        conteudo = conteudo.replace("{{NOME}}", nome.upper())
        conteudo = conteudo.replace("{{CPF}}", formatar_cpf(cpf))
        doc_xml_path.write_text(conteudo, encoding="utf-8")

        if destino_path.exists():
            destino_path.unlink()
        with zipfile.ZipFile(destino_path, "w", zipfile.ZIP_DEFLATED) as z:
            for arquivo in tmp_path.rglob("*"):
                if arquivo.is_file():
                    z.write(arquivo, arquivo.relative_to(tmp_path))


def _converter_docx_para_pdf(docx_path: Path, pasta_saida: Path) -> Path:
    resultado = subprocess.run(
        [
            "soffice",
            "--headless",
            "--convert-to", "pdf",
            "--outdir", str(pasta_saida),
            str(docx_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if resultado.returncode != 0:
        raise RuntimeError(
            f"Falha ao converter docx para pdf: {resultado.stderr or resultado.stdout}"
        )
    pdf_path = pasta_saida / (docx_path.stem + ".pdf")
    if not pdf_path.exists():
        raise RuntimeError("LibreOffice nao gerou o PDF esperado.")
    return pdf_path


def gerar_pdf_capacitacao(curso_sanitizado: str, nome: str, cpf: str) -> bytes:
    """
    Gera o PDF de capacitacao preenchido para o aluno e devolve os bytes.
    Lanca ModeloNaoEncontrado se o curso nao tiver modelo cadastrado.
    """
    modelo_path = _caminho_modelo(curso_sanitizado)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        docx_preenchido = tmp_path / "capacitacao_preenchida.docx"
        _preencher_docx(modelo_path, docx_preenchido, nome, cpf)

        pdf_path = _converter_docx_para_pdf(docx_preenchido, tmp_path)
        return pdf_path.read_bytes()
