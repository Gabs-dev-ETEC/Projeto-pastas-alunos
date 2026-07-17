
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class DocumentoRequerido:
    id: str
    label: str
    condicao: Callable[[dict], bool]
    grupo: Optional[str] = None


def _sempre(respostas: dict) -> bool:
    return True


def _somente_homens(respostas: dict) -> bool:
    return respostas.get("sexo") == "masculino"


def _sem_cpf_no_rg(respostas: dict) -> bool:
    return respostas.get("rg_tem_cpf") is False


DOCUMENTOS: list[DocumentoRequerido] = [
    DocumentoRequerido("rg_frente", "RG - Frente", _sempre),
    DocumentoRequerido("rg_verso", "RG - Verso", _sempre),
    DocumentoRequerido("cpf", "CPF", _sem_cpf_no_rg),
    DocumentoRequerido("titulo_eleitor", "Título de Eleitor", _sempre),
    DocumentoRequerido("reservista", "Certificado de Reservista", _somente_homens),
    DocumentoRequerido("comprovante_residencia", "Comprovante de Residência", _sempre),
    DocumentoRequerido(
        "certidao_nascimento_casamento",
        "Certidão de Nascimento OU Certidão de Casamento",
        _sempre,
    ),
    DocumentoRequerido("certificado_ensino_medio", "Certificado do Ensino Médio", _sempre),
    DocumentoRequerido("historico_ensino_medio", "Histórico do Ensino Médio", _sempre),
]


def documentos_aplicaveis(respostas: dict) -> list[DocumentoRequerido]:
    """Filtra a lista de documentos de acordo com as respostas do aluno."""
    return [doc for doc in DOCUMENTOS if doc.condicao(respostas)]


def label_por_id(documento_id: str) -> str:
    for doc in DOCUMENTOS:
        if doc.id == documento_id:
            return doc.label
    return documento_id