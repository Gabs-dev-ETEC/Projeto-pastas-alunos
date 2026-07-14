

import requests

ENDPOINT_BUSCA_CPF = "/sigaAPI/alunoConsultar"

TIMEOUT_SEGUNDOS = 10


class AlunoNaoEncontrado(Exception):
    """CPF não encontrado na base do SIGA."""


class SigaAPIError(Exception):
    """Erro de configuração, autenticação ou comunicação com o SIGA."""


class SigaClient:
    def __init__(self, base_url: str, api_key: str):
        if not base_url or not api_key:
            raise SigaAPIError(
                "SIGA_BASE_URL e SIGA_API_KEY precisam estar configurados."
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict:
        return {
            "X-API-Key": self.api_key,
            "Accept": "application/json",
        }

    def buscar_aluno_por_cpf(self, cpf: str) -> dict:
        """
        Busca nome, curso, e-mail e telefone do aluno na API do SIGA a
        partir do CPF. Levanta AlunoNaoEncontrado se o CPF não constar
        na base, ou SigaAPIError em caso de falha de configuração,
        autenticação ou comunicação.
        """
        cpf_limpo = "".join(c for c in cpf if c.isdigit())
        if len(cpf_limpo) != 11:
            raise SigaAPIError("CPF inválido.")

        url = self.base_url + ENDPOINT_BUSCA_CPF

        try:
            resposta = requests.get(
                url,
                headers=self._headers(),
                params={"cpf": cpf_limpo},
                timeout=TIMEOUT_SEGUNDOS,
            )
        except requests.RequestException as exc:
            raise SigaAPIError(f"Falha de conexão com o SIGA: {exc}") from exc

        if resposta.status_code == 404:
            raise AlunoNaoEncontrado(cpf_limpo)
        if resposta.status_code in (401, 403):
            raise SigaAPIError("Chave de API do SIGA inválida, expirada ou sem permissão.")
        if resposta.status_code == 429:
            raise SigaAPIError("Limite de requisições do SIGA excedido. Tente novamente em instantes.")
        if not resposta.ok:
            raise SigaAPIError(
                f"SIGA retornou erro {resposta.status_code}: {resposta.text[:300]}"
            )

        try:
            corpo = resposta.json()
        except ValueError as exc:
            raise SigaAPIError("Resposta do SIGA não é um JSON válido.") from exc

        # A API do SIGA envelopa a resposta em {"sucesso": bool, "dados": {...}}
        if not corpo.get("sucesso"):
            raise SigaAPIError(corpo.get("mensagem") or "SIGA retornou uma falha não especificada.")

        dados = corpo.get("dados") or {}
        if not dados:
            raise AlunoNaoEncontrado(cpf_limpo)

        return self._normalizar(dados, cpf_limpo)

    @staticmethod
    def _normalizar(dados: dict, cpf_limpo: str) -> dict:
        return {
            "nome": dados.get("nome") or "",
            "cpf": cpf_limpo,
            "curso": dados.get("curso") or "",
            "email": dados.get("email") or "",
            "telefone": dados.get("celular") or dados.get("telefone") or "",
        }
