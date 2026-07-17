"""
Envio de e-mail via SMTP (pensado pro Gmail, mas funciona com qualquer
SMTP comum). Usado pra avisar o aluno quando a secretaria aprova ou marca
pendência na documentação enviada.

Configuração necessária (ver config.py / variáveis de ambiente):
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_SENHA, SMTP_REMETENTE_NOME

Pra usar Gmail: ative a verificação em duas etapas na conta e gere uma
"senha de app" em https://myaccount.google.com/apppasswords -- a senha
normal da conta não funciona com SMTP.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class EmailNaoConfigurado(Exception):
    """SMTP_USER/SMTP_SENHA não configurados -- não dá pra enviar."""


def enviar_email(host: str, port: int, usuario: str, senha: str, remetente_nome: str,
                  destinatario: str, assunto: str, corpo_texto: str) -> None:
    """
    Envia um e-mail simples (texto puro) via SMTP com STARTTLS.
    Lança EmailNaoConfigurado se usuario/senha não estiverem preenchidos,
    ou smtplib.SMTPException/OSError em caso de falha de envio -- quem
    chamar decide se quer logar e seguir em frente ou propagar o erro.
    """
    if not usuario or not senha:
        raise EmailNaoConfigurado("SMTP_USER e SMTP_SENHA precisam estar configurados.")
    if not destinatario:
        raise ValueError("Aluno sem e-mail cadastrado -- não há para quem enviar.")

    mensagem = MIMEMultipart()
    mensagem["From"] = f"{remetente_nome} <{usuario}>"
    mensagem["To"] = destinatario
    mensagem["Subject"] = assunto
    mensagem.attach(MIMEText(corpo_texto, "plain", "utf-8"))

    with smtplib.SMTP(host, port, timeout=15) as servidor:
        servidor.starttls()
        servidor.login(usuario, senha)
        servidor.sendmail(usuario, [destinatario], mensagem.as_string())


def corpo_aprovacao(nome: str) -> str:
    return (
        f"Olá, {nome}!\n\n"
        "Sua documentação foi conferida e aprovada pela secretaria.\n\n"
        "Não é necessário fazer mais nada por enquanto. Qualquer dúvida, "
        "fale com a gente pelo WhatsApp.\n\n"
        "Atenciosamente,\nSecretaria Acadêmica"
    )


def corpo_pendencia(nome: str, pendencias: list[str]) -> str:
    lista = "\n".join(f"- {item}" for item in pendencias)
    return (
        f"Olá, {nome}!\n\n"
        "Analisamos sua documentação e encontramos pendências nos itens abaixo:\n\n"
        f"{lista}\n\n"
        "Acesse o link que você usou para enviar a documentação e reenvie "
        "apenas os itens pendentes.\n\n"
        "Qualquer dúvida, fale com a gente pelo WhatsApp.\n\n"
        "Atenciosamente,\nSecretaria Acadêmica"
    )