"""
Converte a imagem enviada pelo aluno em um PDF.

Usa img2pdf para a conversão da imagem em si, porque ele não recomprime
a imagem (ao contrário do Pillow), preservando a qualidade da foto do
documento -- importante pra manter o texto legível.
"""

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


def documentos_para_pdf_unico(imagens: list[bytes]) -> bytes:
    """
    Recebe os bytes de várias imagens (uma por documento, na ordem em que
    devem aparecer) e devolve os bytes de um único PDF com uma página por
    imagem, na mesma ordem.
    """
    imagens_normalizadas = [_normalizar_imagem(img) for img in imagens]
    return img2pdf.convert(imagens_normalizadas)


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
