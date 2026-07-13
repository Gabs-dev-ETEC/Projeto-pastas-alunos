from flask import Blueprint, current_app, jsonify, render_template, request

from models import APROVADO, AGUARDANDO_VALIDACAO, db, Aluno, DocumentoEnviado
from services.capacitacao_generator import ModeloNaoEncontrado, gerar_pdf_capacitacao
from services.documentos_config import documentos_aplicaveis
from services.drive_client import DriveClient
from services.pdf_converter import documentos_para_pdf_unico, juntar_pdfs, sanitizar_nome
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
    sexo = request.form.get("sexo", "").strip()
    tipo_certidao = request.form.get("tipo_certidao", "").strip()
    rg_sem_cpf = request.form.get("rg_sem_cpf") == "on"

    if not nome or not curso or not sexo or not cpf:
        return jsonify({"erro": "Nome, curso, CPF e sexo são obrigatórios."}), 400

    respostas = {
        "sexo": sexo,
        "rg_tem_cpf": not rg_sem_cpf,
        "tipo_certidao": tipo_certidao,
    }
    obrigatorios = documentos_aplicaveis(respostas)

    # Valida que todos os arquivos exigidos por essas respostas realmente
    # vieram na requisição -- o front já faz isso, mas o backend não confia
    # cegamente no front.
    faltando = [doc.label for doc in obrigatorios if doc.id not in request.files]
    if faltando:
        return jsonify({"erro": f"Documentos faltando: {', '.join(faltando)}"}), 400

    aluno = Aluno(nome=nome, cpf=cpf, curso=curso, sexo=sexo)
    db.session.add(aluno)
    db.session.commit()

    # Junta as fotos de todos os documentos exigidos em um único PDF,
    # uma página por documento, na ordem em que aparecem em DOCUMENTOS.
    imagens = [request.files[doc.id].read() for doc in obrigatorios]
    pdf_documentos = documentos_para_pdf_unico(imagens)

    # Gera o certificado de capacitação preenchido com nome e CPF do aluno
    # a partir do modelo .docx do curso, e junta como páginas extras no
    # mesmo PDF -- se não existir modelo cadastrado pra esse curso, segue
    # o fluxo sem a capacitação (não trava o envio do aluno por isso).
    try:
        pdf_capacitacao = gerar_pdf_capacitacao(sanitizar_nome(curso), nome, cpf)
        pdf_bytes = juntar_pdfs([pdf_documentos, pdf_capacitacao])
    except ModeloNaoEncontrado:
        current_app.logger.warning(
            "Sem modelo de capacitação para o curso '%s' -- enviando só os documentos.",
            curso,
        )
        pdf_bytes = pdf_documentos

    drive = DriveClient(current_app.config["GOOGLE_CREDENTIALS_JSON"])

    # Pasta do curso (nivel 1) e, dentro dela, a pasta do aluno (nivel 2).
    # Se quiser SEM subpasta de curso, troque pasta_pai_id abaixo por
    # current_app.config["DRIVE_PASTA_RAIZ_ID"] diretamente.
    pasta_curso_id = drive.obter_ou_criar_pasta(
        sanitizar_nome(curso), current_app.config["DRIVE_PASTA_RAIZ_ID"]
    )
    pasta_aluno_id = drive.obter_ou_criar_pasta(
        sanitizar_nome(nome), pasta_curso_id
    )

    nome_arquivo = f"{sanitizar_nome(nome)}_{sanitizar_nome(curso)}.pdf"

    # Um único upload pro Drive, em vez de um por documento -- bem mais
    # rápido e evita o timeout que acontecia com 10 chamadas sequenciais.
    upload_resultado = drive.enviar_pdf(nome_arquivo, pdf_bytes, pasta_aluno_id)

    registro = DocumentoEnviado(
        aluno_id=aluno.id,
        tipo_documento="documentacao_completa",
        nome_arquivo=nome_arquivo,
        drive_file_id=upload_resultado["id"],
        drive_url=upload_resultado["url"],
    )
    db.session.add(registro)
    db.session.commit()

    # Registra a linha na planilha de controle (Nome | CPF | Curso |
    # Data de Envio | Dias Úteis desde Envio | Status). Isso não deve
    # travar o envio do aluno se der algum problema na planilha -- os
    # documentos já foram salvos no Drive nesse ponto, então só logamos
    # o erro em vez de derrubar a resposta.
    try:
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

    return jsonify({"status": "ok", "aluno_id": aluno.id, "arquivo_enviado": nome_arquivo})