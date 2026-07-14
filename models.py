from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# Status possíveis de Aluno.status
AGUARDANDO_VALIDACAO = "aguardando_validacao"
APROVADO = "aprovado"
REPROVADO = "reprovado"


class Aluno(db.Model):
    __tablename__ = "alunos"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    cpf = db.Column(db.String(20), nullable=True, unique=True)
    curso = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=True)
    sexo = db.Column(db.String(20), nullable=True)  # usado na regra do reservista
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    # Fluxo de revisão
    status = db.Column(db.String(30), default=AGUARDANDO_VALIDACAO, nullable=False)
    avaliado_por = db.Column(db.String(120), nullable=True)
    avaliado_em = db.Column(db.DateTime, nullable=True)

    # Como o aluno optou por enviar a documentação:
    #   "individual"  -> um arquivo por documento (ver DocumentoEnviado)
    #   "pdf_unico"   -> um único PDF com tudo junto (ver checklist_pdf_unico)
    forma_envio = db.Column(db.String(20), default="individual", nullable=False)

    # Quando forma_envio == "pdf_unico": lista (JSON) dos ids de documento
    # que o próprio aluno confirmou estarem incluídos no PDF único, pra a
    # secretaria conferir contra o que foi de fato enviado.
    checklist_pdf_unico = db.Column(db.Text, nullable=True)

    # PDF final (só existe depois que um revisor aprova)
    drive_file_id = db.Column(db.String(200), nullable=True)
    drive_url = db.Column(db.String(500), nullable=True)
    pdf_gerado_em = db.Column(db.DateTime, nullable=True)

    documentos = db.relationship("DocumentoEnviado", backref="aluno", lazy=True)


class DocumentoEnviado(db.Model):
    __tablename__ = "documentos_enviados"

    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey("alunos.id"), nullable=False)

    tipo_documento = db.Column(db.String(50), nullable=False)  # ex: "rg_frente"
    nome_arquivo = db.Column(db.String(300), nullable=False)

    # Guarda a imagem em si enquanto aguarda revisão -- só é descartada
    # depois que o PDF final é gerado (ver comentário em routes/painel.py)
    conteudo = db.Column(db.LargeBinary, nullable=True)

    status = db.Column(db.String(20), default="pendente")  # pendente / aprovado / ilegivel
    observacao = db.Column(db.Text, nullable=True)  # motivo, quando marcado ilegível

    enviado_em = db.Column(db.DateTime, default=datetime.utcnow)


class Revisor(UserMixin, db.Model):
    __tablename__ = "revisores"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)

    def set_senha(self, senha: str) -> None:
        self.senha_hash = generate_password_hash(senha)

    def checar_senha(self, senha: str) -> bool:
        return check_password_hash(self.senha_hash, senha)
