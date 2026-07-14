import os


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql://localhost/documentacao_alunos"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20MB por requisição de upload

    # Google Drive - Service Account (mesma credencial que você já usa no
    # projeto financeiro, só precisa garantir que o escopo do Drive esteja
    # habilitado para essa service account)
    GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")

    # ID da pasta raiz no Drive dentro da qual as pastas de curso/aluno
    # serão criadas. Pegue esse ID na URL da pasta no Google Drive.
    DRIVE_PASTA_RAIZ_ID = os.environ.get("DRIVE_PASTA_RAIZ_ID", "")

    # Nome da planilha de controle de envios, criada uma única vez dentro
    # da pasta raiz acima.
    NOME_PLANILHA_CONTROLE = os.environ.get(
        "NOME_PLANILHA_CONTROLE", "Controle de Documentação - Alunos"
    )

    # SIGA - busca de aluno por CPF (Instituição > Configurações > API)
    SIGA_BASE_URL = os.environ.get("SIGA_BASE_URL", "https://etec.sistemasiga.net")
    SIGA_API_KEY = os.environ.get("SIGA_API_KEY", "")

    # Necessário pro login do painel de revisão funcionar (sessão do
    # Flask). Gere um valor aleatório longo, por exemplo com:
    # python3 -c "import secrets; print(secrets.token_hex(32))"
    SECRET_KEY = os.environ.get("SECRET_KEY", "")

    # E-mail (Gmail/SMTP) -- avisa o aluno quando a secretaria aprova ou
    # marca pendência na documentação. Pra usar o Gmail, gere uma "senha de
    # app" em https://myaccount.google.com/apppasswords (não dá pra usar a
    # senha normal da conta com SMTP).
    SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_SENHA = os.environ.get("SMTP_SENHA", "")
    SMTP_REMETENTE_NOME = os.environ.get("SMTP_REMETENTE_NOME", "Secretaria Acadêmica")

    # Token temporário pra liberar a rota /painel/setup-inicial, usada só
    # pra criar o primeiro revisor sem precisar do Shell do Render (pago
    # no plano free). Configure essa variável, use a rota, depois APAGUE
    # ela no Render -- sem ela, a rota volta a responder 404 sozinha.
    SETUP_TOKEN = os.environ.get("SETUP_TOKEN", "")
