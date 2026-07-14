import io
import json
from datetime import datetime

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from PIL import Image

from models import (
    AGUARDANDO_VALIDACAO,
    APROVADO,
    REPROVADO,
    Aluno,
    DocumentoEnviado,
    Revisor,
    db,
)
from services.capacitacao_generator import ModeloNaoEncontrado, gerar_pdf_capacitacao
from services.documentos_config import documentos_aplicaveis, label_por_id
from services.drive_client import DriveClient
from services.email_client import EmailNaoConfigurado, corpo_aprovacao, corpo_pendencia, enviar_email
from services.pdf_converter import documentos_para_pdf_unico, eh_pdf, juntar_pdfs, sanitizar_nome
from services.sheets_client import SheetsClient

painel_bp = Blueprint("painel", __name__, url_prefix="/painel")


def _detectar_mimetype(conteudo: bytes) -> str:
    """Descobre o content-type certo pra servir o arquivo de volta pro navegador."""
    if eh_pdf(conteudo):
        return "application/pdf"
    try:
        with Image.open(io.BytesIO(conteudo)) as imagem:
            formato = (imagem.format or "JPEG").upper()
    except Exception:
        formato = "JPEG"
    return "image/jpeg" if formato == "JPEG" else f"image/{formato.lower()}"


def _avisar_aluno_por_email(aluno, assunto: str, corpo: str) -> None:
    """
    Envia o aviso por e-mail pro aluno. Nunca lança exceção pra fora --
    se o SMTP não estiver configurado, o aluno não tiver e-mail salvo, ou o
    envio falhar por qualquer motivo, só loga o erro. A aprovação/reprovação
    em si (banco + Drive) já está garantida antes dessa chamada acontecer,
    então um problema aqui não pode derrubar a resposta pro revisor.
    """
    if not aluno.email:
        current_app.logger.warning(
            "Aluno %s (id=%s) sem e-mail cadastrado -- aviso não enviado.",
            aluno.nome, aluno.id,
        )
        return
    try:
        enviar_email(
            host=current_app.config["SMTP_HOST"],
            port=current_app.config["SMTP_PORT"],
            usuario=current_app.config["SMTP_USER"],
            senha=current_app.config["SMTP_SENHA"],
            remetente_nome=current_app.config["SMTP_REMETENTE_NOME"],
            destinatario=aluno.email,
            assunto=assunto,
            corpo_texto=corpo,
        )
    except EmailNaoConfigurado:
        current_app.logger.warning(
            "SMTP não configurado (SMTP_USER/SMTP_SENHA) -- aviso por e-mail não enviado "
            "para aluno_id=%s.", aluno.id,
        )
    except Exception:
        current_app.logger.exception(
            "Falha ao enviar e-mail de aviso para aluno_id=%s.", aluno.id
        )


@painel_bp.route("/setup-inicial", methods=["GET", "POST"])
def setup_inicial():

    token_esperado = current_app.config.get("SETUP_TOKEN", "")
    if not token_esperado or request.args.get("token") != token_esperado:
        abort(404)

    mensagem = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        nome = request.form.get("nome", "").strip()
        senha = request.form.get("senha", "")

        if not username or not nome or not senha:
            mensagem = "Preencha usuário, nome e senha."
        else:
            revisor = Revisor.query.filter_by(username=username).first()
            if revisor is None:
                revisor = Revisor(username=username, nome=nome)
                db.session.add(revisor)
            else:
                revisor.nome = nome
            revisor.set_senha(senha)
            db.session.commit()
            mensagem = f"Revisor '{username}' criado/atualizado com sucesso."

    return render_template(
        "setup_inicial.html", mensagem=mensagem, token=request.args.get("token")
    )


@painel_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("painel.lista"))

    erro = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        senha = request.form.get("senha", "")
        revisor = Revisor.query.filter_by(username=username).first()
        if revisor and revisor.checar_senha(senha):
            login_user(revisor)
            return redirect(request.args.get("next") or url_for("painel.lista"))
        erro = "Usuário ou senha inválidos."

    return render_template("login.html", erro=erro)


@painel_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("painel.login"))


@painel_bp.route("/aluno/<int:aluno_id>/excluir", methods=["POST"])
@login_required
def excluir(aluno_id):
    """
    Exclui completamente o envio de documentação de um aluno (o registro
    do aluno e todos os documentos anexados). Não mexe em nada que já
    tenha ido pro Drive/planilha -- só limpa o que está no banco, pra
    liberar o CPF pra um novo envio do zero. Ação irreversível.
    """
    aluno = Aluno.query.get_or_404(aluno_id)
    DocumentoEnviado.query.filter_by(aluno_id=aluno.id).delete()
    db.session.delete(aluno)
    db.session.commit()
    return jsonify({"status": "ok"})


@painel_bp.route("/")
@login_required
def lista():
    alunos = (
        Aluno.query.filter_by(status=AGUARDANDO_VALIDACAO)
        .order_by(Aluno.criado_em.asc())
        .all()
    )
    return render_template("lista.html", alunos=alunos)


@painel_bp.route("/aluno/<int:aluno_id>")
@login_required
def revisar(aluno_id):
    aluno = Aluno.query.get_or_404(aluno_id)
    documentos = (
        DocumentoEnviado.query.filter_by(aluno_id=aluno.id)
        .order_by(DocumentoEnviado.id.asc())
        .all()
    )
    # `label` e `eh_pdf` não são colunas do modelo -- são só atributos em
    # memória pra o template mostrar o nome bonito (ex: "RG - Frente" em
    # vez de "rg_frente") e decidir entre exibir <img> ou um link de PDF.
    for doc in documentos:
        doc.label = label_por_id(doc.tipo_documento)
        doc.eh_pdf = eh_pdf(doc.conteudo) if doc.conteudo else False

    # Quando o aluno mandou um único PDF com tudo (forma_envio ==
    # "pdf_unico"), não temos um arquivo por documento pra conferir -- em
    # vez disso mostramos o checklist que o próprio aluno preencheu,
    # dizendo o que ele afirma que está dentro do PDF.
    checklist = None
    if aluno.forma_envio == "pdf_unico":
        respostas = {"sexo": aluno.sexo, "rg_tem_cpf": True}
        try:
            marcados = set(json.loads(aluno.checklist_pdf_unico or "[]"))
        except ValueError:
            marcados = set()
        checklist = [
            {"label": doc.label, "marcado": doc.id in marcados}
            for doc in documentos_aplicaveis(respostas)
        ]

    # O template ficou salvo como templates/painel.py (extensão errada --
    # o conteúdo é HTML normal). Renderiza normal, mas o ideal é renomear
    # esse arquivo pra templates/painel.html numa próxima limpeza.
    return render_template(
        "painel.py", aluno=aluno, documentos=documentos, checklist=checklist
    )


@painel_bp.route("/aluno/<int:aluno_id>/documento/<int:documento_id>/imagem")
@login_required
def imagem_documento(aluno_id, documento_id):
    doc = DocumentoEnviado.query.filter_by(id=documento_id, aluno_id=aluno_id).first()
    if doc is None or not doc.conteudo:
        abort(404)
    return Response(doc.conteudo, mimetype=_detectar_mimetype(doc.conteudo))


@painel_bp.route("/aluno/<int:aluno_id>/aprovar", methods=["POST"])
@login_required
def aprovar(aluno_id):
    aluno = Aluno.query.get_or_404(aluno_id)
    if aluno.status != AGUARDANDO_VALIDACAO:
        return jsonify({"erro": "Esse aluno já foi avaliado."}), 400

    documentos = (
        DocumentoEnviado.query.filter_by(aluno_id=aluno.id)
        .order_by(DocumentoEnviado.id.asc())
        .all()
    )
    if not documentos or any(doc.conteudo is None for doc in documentos):
        return jsonify({"erro": "Documentação incompleta -- não dá pra gerar o PDF final."}), 400
    if any(doc.status == "ilegivel" for doc in documentos):
        return jsonify(
            {"erro": "Há documentos marcados como pendentes/ilegíveis. Use \"Enviar pendências\"."}
        ), 400

    # Junta as fotos de todos os documentos num único PDF, igual ao
    # fluxo de envio original (routes/upload.py: enviar()).
    imagens = [doc.conteudo for doc in documentos]
    pdf_documentos = documentos_para_pdf_unico(imagens)

    try:
        pdf_capacitacao = gerar_pdf_capacitacao(
            sanitizar_nome(aluno.curso), aluno.nome, aluno.cpf
        )
        pdf_bytes = juntar_pdfs([pdf_documentos, pdf_capacitacao])
    except ModeloNaoEncontrado:
        current_app.logger.warning(
            "Sem modelo de capacitação para o curso '%s' -- aprovando só com os documentos.",
            aluno.curso,
        )
        pdf_bytes = pdf_documentos

    drive = DriveClient(current_app.config["GOOGLE_CREDENTIALS_JSON"])
    pasta_curso_id = drive.obter_ou_criar_pasta(
        sanitizar_nome(aluno.curso), current_app.config["DRIVE_PASTA_RAIZ_ID"]
    )
    pasta_aluno_id = drive.obter_ou_criar_pasta(sanitizar_nome(aluno.nome), pasta_curso_id)
    nome_arquivo = f"{sanitizar_nome(aluno.nome)}_{sanitizar_nome(aluno.curso)}.pdf"
    resultado = drive.enviar_pdf(nome_arquivo, pdf_bytes, pasta_aluno_id)

    aluno.status = APROVADO
    aluno.avaliado_por = current_user.nome
    aluno.avaliado_em = datetime.utcnow()
    aluno.drive_file_id = resultado["id"]
    aluno.drive_url = resultado["url"]
    aluno.pdf_gerado_em = datetime.utcnow()

    # Descarta as imagens guardadas no banco -- só existiam pra essa
    # revisão; o PDF final já está no Drive.
    for doc in documentos:
        doc.conteudo = None
        doc.status = "aprovado"

    db.session.commit()

    # Marca na planilha de controle quem aprovou. Feito depois do commit
    # de propósito: se a planilha falhar (fora do ar, renomeada, etc.), a
    # aprovação em si (banco + Drive) já está garantida -- só loga o erro
    # em vez de derrubar a resposta pro revisor.
    try:
        sheets = SheetsClient(current_app.config["GOOGLE_CREDENTIALS_JSON"])
        planilha_id = sheets.obter_ou_criar_planilha(
            current_app.config["NOME_PLANILHA_CONTROLE"],
            current_app.config["DRIVE_PASTA_RAIZ_ID"],
            drive,
        )
        sheets.marcar_aprovado(planilha_id, aluno.cpf, current_user.nome)
    except Exception:
        current_app.logger.exception(
            "Falha ao marcar 'Aprovado por' na planilha de controle (aluno_id=%s)", aluno.id
        )

    _avisar_aluno_por_email(
        aluno, "Documentação aprovada", corpo_aprovacao(aluno.nome)
    )

    return jsonify({"status": "ok", "drive_url": aluno.drive_url})


@painel_bp.route("/aluno/<int:aluno_id>/reprovar", methods=["POST"])
@login_required
def reprovar(aluno_id):
    aluno = Aluno.query.get_or_404(aluno_id)
    if aluno.status != AGUARDANDO_VALIDACAO:
        return jsonify({"erro": "Esse aluno já foi avaliado."}), 400

    dados = request.get_json(silent=True) or {}
    pendencias = dados.get("pendencias") or []
    if not pendencias:
        return jsonify({"erro": "Informe ao menos uma pendência."}), 400

    algum_marcado = False
    labels_pendencias = []
    for pendencia in pendencias:
        doc = DocumentoEnviado.query.filter_by(
            id=pendencia.get("documento_id"), aluno_id=aluno.id
        ).first()
        if doc is None:
            continue
        doc.status = "ilegivel"
        doc.observacao = (pendencia.get("motivo") or "").strip()
        algum_marcado = True
        rotulo = label_por_id(doc.tipo_documento)
        labels_pendencias.append(f"{rotulo} ({doc.observacao})" if doc.observacao else rotulo)

    if not algum_marcado:
        return jsonify({"erro": "Nenhum dos documentos informados pertence a esse aluno."}), 400

    # Libera o CPF pra reenvio -- routes/upload.py (buscar_cpf) trata
    # "reprovado" igual a "novo", liberando o aluno a mandar tudo de novo.
    aluno.status = REPROVADO
    aluno.avaliado_por = current_user.nome
    aluno.avaliado_em = datetime.utcnow()

    db.session.commit()

    _avisar_aluno_por_email(
        aluno, "Pendência na sua documentação", corpo_pendencia(aluno.nome, labels_pendencias)
    )

    return jsonify({"status": "ok"})
