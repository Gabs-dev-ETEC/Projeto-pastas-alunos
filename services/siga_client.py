import requests

ENDPOINT_ALUNO = "/sigaAPI/alunoConsultar"
ENDPOINT_MATRICULA = "/sigaAPI/matriculaConsultar"
ENDPOINT_CURSO = "/sigaAPI/cursoConsultar"

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

    def _get(self, caminho: str, params: dict) -> dict:
        """
        GET genérico contra a API do SIGA. Levanta AlunoNaoEncontrado em
        404 e SigaAPIError em qualquer outra falha (auth, rate limit,
        conexão, JSON inválido ou "sucesso": false no corpo).
        """
        url = self.base_url + caminho
        try:
            resposta = requests.get(
                url, headers=self._headers(), params=params, timeout=TIMEOUT_SEGUNDOS
            )
        except requests.RequestException as exc:
            raise SigaAPIError(f"Falha de conexão com o SIGA: {exc}") from exc

        if resposta.status_code == 404:
            raise AlunoNaoEncontrado()
        if resposta.status_code in (401, 403):
            raise SigaAPIError("Chave de API do SIGA inválida, expirada ou sem permissão.")
        if resposta.status_code == 429:
            raise SigaAPIError("Limite de requisições do SIGA excedido. Tente novamente em instantes.")
        if not resposta.ok:
            raise SigaAPIError(f"SIGA retornou erro {resposta.status_code}: {resposta.text[:300]}")

        try:
            corpo = resposta.json()
        except ValueError as exc:
            raise SigaAPIError("Resposta do SIGA não é um JSON válido.") from exc

        if not corpo.get("sucesso"):
            raise SigaAPIError(corpo.get("mensagem") or "SIGA retornou uma falha não especificada.")

        return corpo.get("dados") or {}

    def buscar_aluno_por_cpf(self, cpf: str) -> dict:
        """
        Busca nome, curso, e-mail e telefone do aluno na API do SIGA a
        partir do CPF. Levanta AlunoNaoEncontrado se o CPF não constar
        na base, ou SigaAPIError em caso de falha de configuração,
        autenticação ou comunicação.

        Curso não vem no /alunoConsultar -- é buscado à parte via
        /matriculaConsultar (que devolve tb_curso_id) + /cursoConsultar
        (que devolve o nome). Se essa segunda etapa falhar por qualquer
        motivo, a busca não é interrompida: o aluno só entra sem curso
        pré-preenchido e digita manualmente na tela.
        """
        cpf_limpo = "".join(c for c in cpf if c.isdigit())
        if len(cpf_limpo) != 11:
            raise SigaAPIError("CPF inválido.")

        dados_aluno = self._get(ENDPOINT_ALUNO, {"cpf": cpf_limpo})
        if not dados_aluno:
            raise AlunoNaoEncontrado(cpf_limpo)

        curso = self._buscar_curso(cpf_limpo)

        return {
            "nome": dados_aluno.get("nome") or "",
            "cpf": cpf_limpo,
            "curso": curso,
            "email": dados_aluno.get("email") or "",
            "telefone": dados_aluno.get("celular") or dados_aluno.get("telefone") or "",
        }

    def _buscar_curso(self, cpf_limpo: str) -> str:
        try:
            matricula = self._get(ENDPOINT_MATRICULA, {"cpf": cpf_limpo})
        except (AlunoNaoEncontrado, SigaAPIError):
            return ""

        curso_id = matricula.get("tb_curso_id")
        if not curso_id:
            return ""

        try:
            curso = self._get(ENDPOINT_CURSO, {"id": curso_id})
        except (AlunoNaoEncontrado, SigaAPIError):
            return ""

        # cursoConsultar?id= costuma devolver um dict único; se algum dia
        # vier lista (ex.: filtro por nome), pega o primeiro item.
        if isinstance(curso, list):
            curso = curso[0] if curso else {}

        return curso.get("nome") or ""
