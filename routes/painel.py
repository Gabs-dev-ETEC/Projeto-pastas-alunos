"""
Painel de revisão da documentação enviada pelos alunos.

Fluxo:
  1. Revisor loga (Flask-Login) e vê a lista de alunos com status
     "aguardando_validacao".
  2. Abre um aluno e vê as fotos de cada documento enviado (guardadas em
     DocumentoEnviado.conteudo enquanto aguardam revisão).
  3. Aprova -> gera o PDF final (documentos + certificado de capacitação,
     igual ao fluxo de routes/upload.py), sobe pro Drive e descarta as
     imagens do banco (só existiam pra essa revisão).
     Reprova -> marca os documentos problemáticos como "ilegivel" com o
     motivo, e libera o CPF do aluno pra reenvio (ver comentário em
     routes/upload.py sobre o status REPROVADO ser tratado como "novo").
"""

import io
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
from services.documentos_config import label_por_id
from services.drive_client import DriveClient
from services.pdf_converter import documentos_para_pdf_unico, juntar_pdfs, sanitizar_nome
from services.sheets_client import SheetsClient

painel_bp = Blueprint("painel", __name__, url_prefix="/painel")


def _detectar_mimetype(conteudo: bytes) -> str:
    """Descobre o content-type certo pra servir a imagem de volta pro navegador."""
    try:
        with Image.open(io.BytesIO(conteudo)) as imagem:
            formato = (imagem.format or "JPEG").upper()
    except Exception:
        formato = "JPEG"
    return "image/jpeg" if formato == "JPEG" else f"image/{formato.lower()}"


@painel_bp.route("/setup-inicial", methods=["GET", "POST"])
def setup_inicial():
    """
    Cria (ou reseta a senha de) um usuário revisor sem precisar de acesso
    ao Shell do Render (que é pago no plano free). Só funciona se a
    variável de ambiente SETUP_TOKEN estiver configurada -- sem ela, essa
    rota devolve 404 como se não existisse.

    IMPORTANTE: depois de criar os revisores que precisar, apague a
    variável SETUP_TOKEN no Render (aba Environment). Isso desliga essa
    rota automaticamente, sem precisar mexer em nenhum código de novo.
    """
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
    # `label` não é coluna do modelo -- é só um atributo em memória pra o
    # template mostrar o nome bonito (ex: "RG - Frente") em vez do id
    # interno (ex: "rg_frente").
    for doc in documentos:
        doc.label = label_por_id(doc.tipo_documento)

    # O template ficou salvo como templates/painel.py (extensão errada --
    # o conteúdo é HTML normal). Renderiza normal, mas o ideal é renomear
    # esse arquivo pra templates/painel.html numa próxima limpeza.
    return render_template("painel.py", aluno=aluno, documentos=documentos)


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
    for pendencia in pendencias:
        doc = DocumentoEnviado.query.filter_by(
            id=pendencia.get("documento_id"), aluno_id=aluno.id
        ).first()
        if doc is None:
            continue
        doc.status = "ilegivel"
        doc.observacao = (pendencia.get("motivo") or "").strip()
        algum_marcado = True

    if not algum_marcado:
        return jsonify({"erro": "Nenhum dos documentos informados pertence a esse aluno."}), 400

    # Libera o CPF pra reenvio -- routes/upload.py (buscar_cpf) trata
    # "reprovado" igual a "novo", liberando o aluno a mandar tudo de novo.
    aluno.status = REPROVADO
    aluno.avaliado_por = current_user.nome
    aluno.avaliado_em = datetime.utcnow()

    db.session.commit()
    return jsonify({"status": "ok"})
