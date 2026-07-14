import json

from flask import Blueprint, current_app, jsonify, render_template, request

from models import APROVADO, AGUARDANDO_VALIDACAO, db, Aluno, DocumentoEnviado
from services.documentos_config import documentos_aplicaveis
from services.drive_client import DriveClient
from services.sheets_client import SheetsClient
from services.siga_client import AlunoNaoEncontrado, SigaAPIError, SigaClient

upload_bp = Blueprint("upload", __name__)


@upload_bp.route("/")
def formulario():
    return render_template("upload.html")


@upload_bp.route("/buscar-cpf", methods=["POST"])
def buscar_cpf():
    """
    Recebe o CPF informado pelo aluno e devolve o que a tela precisa
    mostrar antes de liberar o envio de documentos:

    - "aguardando_validacao": já tem envio dessa pessoa esperando revisão
    - "aprovado": documentação dessa pessoa já foi conferida e aprovada
    - "novo": ainda não tem envio -- devolve nome/curso/email/telefone
      buscados no SIGA pra pessoa conferir na tela antes de continuar
    """
    cpf = (request.get_json(silent=True) or {}).get("cpf", "").strip()
    cpf_limpo = "".join(c for c in cpf if c.isdigit())
    if len(cpf_limpo) != 11:
        return jsonify({"erro": "CPF inválido."}), 400

    aluno_existente = Aluno.query.filter_by(cpf=cpf_limpo).first()
    if aluno_existente and aluno_existente.status == APROVADO:
        return jsonify({"status": "aprovado"})
    if aluno_existente and aluno_existente.status == AGUARDANDO_VALIDACAO:
        return jsonify({"status": "aguardando_validacao"})

    # CPF novo (ou reprovado, liberado pra reenviar): busca os dados
    # cadastrais no SIGA pra pessoa conferir antes de prosseguir.
    try:
        siga = SigaClient(
            current_app.config["SIGA_BASE_URL"], current_app.config["SIGA_API_KEY"]
        )
        dados = siga.buscar_aluno_por_cpf(cpf_limpo)
    except AlunoNaoEncontrado:
        return jsonify({"erro": "CPF não encontrado no SIGA. Confira o número digitado."}), 404
    except SigaAPIError:
        current_app.logger.exception("Falha ao consultar o SIGA para o CPF informado.")
        return jsonify({"erro": "Não foi possível consultar o SIGA agora. Tente novamente em instantes."}), 502

    return jsonify({"status": "novo", **dados})


@upload_bp.route("/enviar", methods=["POST"])
def enviar():
    nome = request.form.get("nome", "").strip()
    curso = request.form.get("curso", "").strip()
    cpf = request.form.get("cpf", "").strip()
    email = request.form.get("email", "").strip()
    telefone = request.form.get("telefone", "").strip()
    sexo = request.form.get("sexo", "").strip()
    rg_sem_cpf = request.form.get("rg_sem_cpf") == "on"
    forma_envio = request.form.get("forma_envio", "individual").strip()
    if forma_envio not in ("individual", "pdf_unico"):
        forma_envio = "individual"

    if not nome or not curso or not sexo or not cpf:
        return jsonify({"erro": "Nome, curso, CPF e sexo são obrigatórios."}), 400

    respostas = {
        "sexo": sexo,
        "rg_tem_cpf": not rg_sem_cpf,
    }
    obrigatorios = documentos_aplicaveis(respostas)

    aluno = Aluno(nome=nome, cpf=cpf, curso=curso, sexo=sexo, forma_envio=forma_envio)
    db.session.add(aluno)
    db.session.flush()  # garante aluno.id antes de criar os documentos

    if forma_envio == "pdf_unico":
        # Aluno optou por mandar um único PDF com toda a documentação em
        # vez de um arquivo por documento. Nesse caso não dá pra conferir
        # arquivo por arquivo -- em vez disso exigimos que o aluno confirme,
        # num checklist, quais documentos estão dentro desse PDF, e essa
        # lista fica salva pra secretaria conferir contra o PDF enviado.
        arquivo_pdf = request.files.get("pdf_completo")
        if arquivo_pdf is None or not arquivo_pdf.filename:
            return jsonify({"erro": "Envie o arquivo PDF com a documentação completa."}), 400

        try:
            checklist_ids = json.loads(request.form.get("checklist", "[]"))
        except ValueError:
            checklist_ids = []
        if not isinstance(checklist_ids, list):
            checklist_ids = []

        faltando = [doc.label for doc in obrigatorios if doc.id not in checklist_ids]
        if faltando:
            return jsonify(
                {"erro": f"Confirme no checklist que o PDF contém: {', '.join(faltando)}"}
            ), 400

        conteudo_pdf = arquivo_pdf.read()
        registro = DocumentoEnviado(
            aluno_id=aluno.id,
            tipo_documento="pdf_completo",
            nome_arquivo=arquivo_pdf.filename or "documentacao-completa.pdf",
            conteudo=conteudo_pdf,
            status="pendente",
        )
        db.session.add(registro)
        aluno.checklist_pdf_unico = json.dumps(checklist_ids)
    else:
        # Valida que todos os arquivos exigidos por essas respostas
        # realmente vieram na requisição -- o front já faz isso, mas o
        # backend não confia cegamente no front.
        faltando = [doc.label for doc in obrigatorios if doc.id not in request.files]
        if faltando:
            return jsonify({"erro": f"Documentos faltando: {', '.join(faltando)}"}), 400

        # Guarda a foto (ou PDF, se o aluno usou "Anexar arquivo") de cada
        # documento aguardando revisão. O PDF final só é gerado (documentos
        # + certificado de capacitação) e sobe pro Drive quando um revisor
        # aprova no painel -- ver routes/painel.py: aprovar().
        for doc in obrigatorios:
            arquivo = request.files[doc.id]
            registro = DocumentoEnviado(
                aluno_id=aluno.id,
                tipo_documento=doc.id,
                nome_arquivo=arquivo.filename or f"{doc.id}.jpg",
                conteudo=arquivo.read(),
                status="pendente",
            )
            db.session.add(registro)

    db.session.commit()

    # Registra a linha na planilha de controle (Nome | CPF | Curso |
    # Data de Envio | Dias Úteis desde Envio | Status) assim que o aluno
    # envia -- a planilha serve pra secretaria acompanhar prazo, então não
    # espera a revisão. Não deve travar o envio se der problema na
    # planilha -- os documentos já foram salvos no banco nesse ponto.
    try:
        drive = DriveClient(current_app.config["GOOGLE_CREDENTIALS_JSON"])
        sheets = SheetsClient(current_app.config["GOOGLE_CREDENTIALS_JSON"])
        planilha_id = sheets.obter_ou_criar_planilha(
            current_app.config["NOME_PLANILHA_CONTROLE"],
            current_app.config["DRIVE_PASTA_RAIZ_ID"],
            drive,
        )
        sheets.adicionar_linha(
            planilha_id, nome, cpf, curso, aluno.criado_em.strftime("%d/%m/%Y")
        )
    except Exception:
        current_app.logger.exception(
            "Falha ao registrar envio na planilha de controle (aluno_id=%s)", aluno.id
        )

    return jsonify({"status": "ok", "aluno_id": aluno.id})
