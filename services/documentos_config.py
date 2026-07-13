"""
Definição de quais documentos são exigidos e em que condição.

Cada documento tem:
  - id: identificador usado internamente (nome de arquivo, campo do form)
  - label: nome exibido pro aluno
  - condicao: função que recebe as respostas do aluno (dict) e devolve
              True/False dizendo se esse documento deve ser pedido
  - grupo: documentos com o mesmo grupo são alternativas entre si
           (o aluno manda um OU outro, não os dois)

As "respostas do aluno" (dict `respostas`) vêm de perguntas simples feitas
antes da lista de upload aparecer, por exemplo:
  {"sexo": "masculino", "rg_tem_cpf": False, "tipo_certidao": "nascimento"}
"""

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


def _certidao_nascimento(respostas: dict) -> bool:
    return respostas.get("tipo_certidao") == "nascimento"


def _certidao_casamento(respostas: dict) -> bool:
    return respostas.get("tipo_certidao") == "casamento"


DOCUMENTOS: list[DocumentoRequerido] = [
    DocumentoRequerido("rg_frente", "RG - Frente", _sempre),
    DocumentoRequerido("rg_verso", "RG - Verso", _sempre),
    DocumentoRequerido("cpf", "CPF", _sem_cpf_no_rg),
    DocumentoRequerido("titulo_eleitor", "Título de Eleitor", _sempre),
    DocumentoRequerido("reservista", "Certificado de Reservista", _somente_homens),
    DocumentoRequerido("comprovante_residencia", "Comprovante de Residência", _sempre),
    DocumentoRequerido(
        "certidao_nascimento", "Certidão de Nascimento", _certidao_nascimento, grupo="certidao"
    ),
    DocumentoRequerido(
        "certidao_casamento", "Certidão de Casamento", _certidao_casamento, grupo="certidao"
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
