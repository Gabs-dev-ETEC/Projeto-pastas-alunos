"""
Cliente para a API do SIGA (busca de dados do aluno por CPF).

Base: https://etec.sistemasiga.net/sigaAPI/
Documentação: https://etec.sistemasiga.net/sigaAPI/documentacao

⚠️ IMPORTANTE: a página de documentação exige login para ser vista, então
o endpoint (`ENDPOINT_BUSCA_CPF`), o header de autenticação e os nomes dos
campos no JSON de resposta abaixo estão configurados com o padrão mais
comum pra esse tipo de API (mesmo usado em "Instituição > Configurações >
API" do SIGA). Se a chamada retornar 404 mesmo pra um CPF que existe, ou
401 mesmo com a chave certa, é só ajustar:
  1) ENDPOINT_BUSCA_CPF (o caminho da rota de busca)
  2) o header em `_headers()` (ex.: pode ser "apikey" em vez de
     "Authorization: Bearer ...")
  3) os nomes de campo em `_normalizar()` (ex.: pode vir "nomeCompleto"
     em vez de "nome")
usando o exemplo de requisição que aparece na documentação.
"""

import requests

ENDPOINT_BUSCA_CPF = "/sigaAPI/alunos/cpf/{cpf}"

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
            "Authorization": f"Bearer {self.api_key}",
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

        url = self.base_url + ENDPOINT_BUSCA_CPF.format(cpf=cpf_limpo)

        try:
            resposta = requests.get(url, headers=self._headers(), timeout=TIMEOUT_SEGUNDOS)
        except requests.RequestException as exc:
            raise SigaAPIError(f"Falha de conexão com o SIGA: {exc}") from exc

        if resposta.status_code == 404:
            raise AlunoNaoEncontrado(cpf_limpo)
        if resposta.status_code in (401, 403):
            raise SigaAPIError("Chave de API do SIGA inválida, expirada ou sem permissão.")
        if not resposta.ok:
            raise SigaAPIError(
                f"SIGA retornou erro {resposta.status_code}: {resposta.text[:300]}"
            )

        try:
            dados = resposta.json()
        except ValueError as exc:
            raise SigaAPIError("Resposta do SIGA não é um JSON válido.") from exc

        return self._normalizar(dados, cpf_limpo)

    @staticmethod
    def _normalizar(dados: dict, cpf_limpo: str) -> dict:
        # Tenta alguns nomes de campo alternativos, já que a doc não pôde
        # ser conferida -- ajuste aqui se os nomes reais forem diferentes.
        return {
            "nome": dados.get("nome") or dados.get("nomeCompleto") or dados.get("nome_completo") or "",
            "cpf": cpf_limpo,
            "curso": dados.get("curso") or dados.get("nomeCurso") or dados.get("nome_curso") or "",
            "email": dados.get("email") or dados.get("emailAluno") or "",
            "telefone": dados.get("telefone") or dados.get("celular") or dados.get("fone") or "",
        }
