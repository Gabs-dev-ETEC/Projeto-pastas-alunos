

import io
import re
import unicodedata

import img2pdf
from PIL import Image
from pypdf import PdfWriter


def sanitizar_nome(texto: str) -> str:
    """
    Remove acentos, espaços e caracteres especiais para gerar nomes de
    arquivo seguros. Ex: "João Silva" -> "joao-silva"
    """
    texto_sem_acento = (
        unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    )
    texto_limpo = re.sub(r"[^a-zA-Z0-9]+", "-", texto_sem_acento).strip("-").lower()
    return texto_limpo


def _normalizar_imagem(imagem_bytes: bytes) -> bytes:
    """
    Recebe os bytes de uma imagem (jpg/png/etc, incluindo fotos tiradas
    direto da câmera do celular) e devolve os bytes de uma imagem JPEG
    normalizada (orientação EXIF corrigida, modo RGB), pronta pro img2pdf,
    que é estrito quanto ao formato de entrada.
    """
    imagem = Image.open(io.BytesIO(imagem_bytes))

    try:
        from PIL import ImageOps

        imagem = ImageOps.exif_transpose(imagem)
    except Exception:
        pass

    if imagem.mode != "RGB":
        imagem = imagem.convert("RGB")

    buffer_imagem = io.BytesIO()
    imagem.save(buffer_imagem, format="JPEG", quality=90)
    buffer_imagem.seek(0)
    return buffer_imagem.read()


def imagem_para_pdf(imagem_bytes: bytes) -> bytes:
    """
    Recebe os bytes de uma imagem e devolve os bytes de um PDF de 1 página.
    """
    return img2pdf.convert(_normalizar_imagem(imagem_bytes))


def eh_pdf(conteudo: bytes) -> bool:
    """Verifica pela assinatura do arquivo (%PDF-) se o conteúdo já é um PDF."""
    return bool(conteudo) and conteudo[:5] == b"%PDF-"


def documento_para_pdf(conteudo: bytes) -> bytes:
    """
    Recebe os bytes de um documento enviado pelo aluno -- que agora pode
    ser uma foto (câmera) ou um arquivo já em PDF (opção "Anexar arquivo"
    ou o envio de "PDF único com tudo") -- e devolve os bytes de um PDF.
    Se já for PDF, devolve como está; se for imagem, converte.
    """
    if eh_pdf(conteudo):
        return conteudo
    return imagem_para_pdf(conteudo)


def documentos_para_pdf_unico(conteudos: list[bytes]) -> bytes:
    """
    Recebe os bytes de vários documentos (foto ou PDF, um por documento,
    na ordem em que devem aparecer) e devolve os bytes de um único PDF
    com todas as páginas, na mesma ordem.
    """
    return juntar_pdfs([documento_para_pdf(c) for c in conteudos])


def juntar_pdfs(pdfs_em_bytes: list[bytes]) -> bytes:
    """
    Recebe uma lista de PDFs (em bytes) e devolve um único PDF com todas
    as páginas, na ordem em que os PDFs foram passados.
    """
    writer = PdfWriter()
    for pdf_bytes in pdfs_em_bytes:
        writer.append(io.BytesIO(pdf_bytes))

    buffer_saida = io.BytesIO()
    writer.write(buffer_saida)
    buffer_saida.seek(0)
    return buffer_saida.read()