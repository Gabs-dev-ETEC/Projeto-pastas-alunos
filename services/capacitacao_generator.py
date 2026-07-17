
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent.parent / "templates_capacitacao"


class ModeloNaoEncontrado(Exception):
    pass


def _slugs_disponiveis() -> list[str]:
    prefixo = "modelo_capacitacao_"
    return [
        arquivo.stem[len(prefixo):]
        for arquivo in TEMPLATES_DIR.glob(f"{prefixo}*.docx")
    ]


def _caminho_modelo(curso_sanitizado: str) -> Path:
    caminho_exato = TEMPLATES_DIR / f"modelo_capacitacao_{curso_sanitizado}.docx"
    if caminho_exato.exists():
        return caminho_exato

    # O nome do curso que vem do SIGA raramente bate 100% com o slug do
    # arquivo (ex: SIGA manda "tecnico-em-eletrotecnica", o arquivo se
    # chama so "eletrotecnica"). Em vez de depender de nome identico,
    # tenta achar um slug cadastrado cujas palavras estejam todas contidas
    # no nome do curso (em qualquer ordem) -- e fica com o mais especifico
    # (mais palavras) em caso de mais de um bater.
    tokens_curso = set(curso_sanitizado.split("-"))
    candidatos = []
    for slug in _slugs_disponiveis():
        tokens_slug = set(slug.split("-"))
        if tokens_slug and tokens_slug.issubset(tokens_curso):
            candidatos.append(slug)

    if candidatos:
        melhor_slug = max(candidatos, key=lambda s: len(s.split("-")))
        return TEMPLATES_DIR / f"modelo_capacitacao_{melhor_slug}.docx"

    raise ModeloNaoEncontrado(
        f"Nao existe modelo de capacitacao para o curso '{curso_sanitizado}' "
        f"(nem por nome exato, nem por aproximacao) em {TEMPLATES_DIR}. "
        f"Modelos cadastrados hoje: {', '.join(_slugs_disponiveis()) or '(nenhum)'}. "
        f"Cadastre o arquivo .docx com os marcadores {{{{NOME}}}} e {{{{CPF}}}} "
        f"nesse caminho, ou ajuste o nome do arquivo pra bater com o curso."
    )


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