"""
Cliente para o Google Drive, usando Service Account.

Modo usado aqui: Drive Compartilhado.
A service account é adicionada como membro do Drive Compartilhado
(papel "Gerente de conteúdo"), diretamente pela interface do Drive.
Não precisa de delegação nem de DRIVE_USUARIO_DELEGADO.
"""

import io
import json

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveClient:
    def __init__(self, credentials_json: str):
        info = json.loads(credentials_json)
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES
        )
        self.service = build("drive", "v3", credentials=credentials)

    def _buscar_pasta(self, nome: str, pasta_pai_id: str) -> str | None:
        return self.buscar_arquivo(
            nome, "application/vnd.google-apps.folder", pasta_pai_id
        )

    def buscar_arquivo(self, nome: str, mime_type: str, pasta_pai_id: str) -> str | None:
        query = (
            f"name = '{nome}' and '{pasta_pai_id}' in parents "
            f"and mimeType = '{mime_type}' and trashed = false"
        )
        resultado = (
            self.service.files()
            .list(
                q=query,
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                corpora="allDrives",
            )
            .execute()
        )
        arquivos = resultado.get("files", [])
        return arquivos[0]["id"] if arquivos else None

    def criar_arquivo_vazio(self, nome: str, mime_type: str, pasta_pai_id: str) -> str:
        """
        Cria um arquivo do Google Workspace (planilha, documento, etc.)
        já diretamente dentro da pasta indicada. Importante: criar direto
        na pasta (em vez de criar "solto" e mover depois) é o que faz
        funcionar em contas do Workspace com política restritiva contra
        service accounts criando arquivos fora de um Drive Compartilhado.
        """
        metadata = {"name": nome, "mimeType": mime_type, "parents": [pasta_pai_id]}
        arquivo = (
            self.service.files()
            .create(body=metadata, fields="id", supportsAllDrives=True)
            .execute()
        )
        return arquivo["id"]

    def obter_ou_criar_pasta(self, nome: str, pasta_pai_id: str) -> str:
        pasta_id = self._buscar_pasta(nome, pasta_pai_id)
        if pasta_id:
            return pasta_id

        metadata = {
            "name": nome,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [pasta_pai_id],
        }
        pasta = (
            self.service.files()
            .create(body=metadata, fields="id", supportsAllDrives=True)
            .execute()
        )
        return pasta["id"]

    def enviar_pdf(self, nome_arquivo: str, pdf_bytes: bytes, pasta_id: str) -> dict:
        metadata = {"name": nome_arquivo, "parents": [pasta_id]}
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf")
        arquivo = (
            self.service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        return {"id": arquivo["id"], "url": arquivo.get("webViewLink")}