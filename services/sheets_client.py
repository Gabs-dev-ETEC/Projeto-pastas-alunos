import json
import re

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

CABECALHO = [
    "Nome", "CPF", "Curso", "Data de Envio", "Dias Úteis desde Envio", "Status", "Aprovado por"
]
COLUNA_DATA_ENVIO = "D"
COLUNA_DIAS_UTEIS = "E"
COLUNA_APROVADO_POR = "G"
STATUS_PADRAO = "Pendente"


class SheetsClient:
    def __init__(self, credentials_json: str):
        info = json.loads(credentials_json)
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES
        )
        self.service = build("sheets", "v4", credentials=credentials)

    def obter_ou_criar_planilha(self, nome: str, pasta_destino_id: str, drive_client) -> str:
        """
        Procura a planilha pelo nome dentro da pasta; se não existir, cria
        JÁ DIRETO dentro da pasta do Drive Compartilhado (não "solta" fora
        dele, que algumas contas do Workspace bloqueiam por política de
        segurança para service accounts) e inicializa cabeçalho, locale e
        formatação condicional.
        """
        mime_sheets = "application/vnd.google-apps.spreadsheet"
        planilha_id = drive_client.buscar_arquivo(nome, mime_sheets, pasta_destino_id)
        if planilha_id:
            return planilha_id

        planilha_id = drive_client.criar_arquivo_vazio(nome, mime_sheets, pasta_destino_id)
        self._inicializar_planilha(planilha_id)
        return planilha_id

    def _inicializar_planilha(self, spreadsheet_id: str) -> None:
        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range="A1:G1",
            valueInputOption="RAW",
            body={"values": [CABECALHO]},
        ).execute()

        self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    # Fixa o locale como pt_BR -- necessário pro separador
                    # de argumento da fórmula (ponto-e-vírgula) funcionar.
                    {
                        "updateSpreadsheetProperties": {
                            "properties": {"locale": "pt_BR"},
                            "fields": "locale",
                        }
                    },
                    # Renomeia a aba de "Página1" para algo mais claro
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": 0,
                                "title": "Envios",
                                "gridProperties": {"frozenRowCount": 1},
                            },
                            "fields": "title,gridProperties.frozenRowCount",
                        }
                    },
                    # Cabeçalho: fundo azul escuro, texto branco em negrito,
                    # fonte um pouco maior, centralizado
                    {
                        "repeatCell": {
                            "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1},
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": {"red": 0.10, "green": 0.22, "blue": 0.45},
                                    "textFormat": {
                                        "bold": True,
                                        "fontSize": 11,
                                        "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                                    },
                                    "horizontalAlignment": "CENTER",
                                    "verticalAlignment": "MIDDLE",
                                }
                            },
                            "fields": (
                                "userEnteredFormat(backgroundColor,textFormat,"
                                "horizontalAlignment,verticalAlignment)"
                            ),
                        }
                    },
                    # Altura um pouco maior pra linha do cabeçalho
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": 0, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                            "properties": {"pixelSize": 34},
                            "fields": "pixelSize",
                        }
                    },
                    # Largura de cada coluna, ajustada ao conteúdo esperado
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                            "properties": {"pixelSize": 220},  # Nome
                            "fields": "pixelSize",
                        }
                    },
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
                            "properties": {"pixelSize": 130},  # CPF
                            "fields": "pixelSize",
                        }
                    },
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
                            "properties": {"pixelSize": 220},  # Curso
                            "fields": "pixelSize",
                        }
                    },
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 3, "endIndex": 4},
                            "properties": {"pixelSize": 120},  # Data de Envio
                            "fields": "pixelSize",
                        }
                    },
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 4, "endIndex": 5},
                            "properties": {"pixelSize": 160},  # Dias Úteis
                            "fields": "pixelSize",
                        }
                    },
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 5, "endIndex": 6},
                            "properties": {"pixelSize": 130},  # Status
                            "fields": "pixelSize",
                        }
                    },
                    {
                        "updateDimensionProperties": {
                            "range": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 6, "endIndex": 7},
                            "properties": {"pixelSize": 180},  # Aprovado por
                            "fields": "pixelSize",
                        }
                    },
                    # Data de Envio: formata como data brasileira de verdade
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": 0, "startRowIndex": 1, "startColumnIndex": 3, "endColumnIndex": 4
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}
                                }
                            },
                            "fields": "userEnteredFormat.numberFormat",
                        }
                    },
                    # Dias Úteis e Status: centralizados, pra ficar mais
                    # fácil de bater o olho e escanear a planilha
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": 0, "startRowIndex": 1, "startColumnIndex": 4, "endColumnIndex": 6
                            },
                            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                            "fields": "userEnteredFormat.horizontalAlignment",
                        }
                    },
                    # Status em negrito, pra se destacar mais dentro da
                    # cor de fundo (verde/amarelo) aplicada condicionalmente
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": 0, "startRowIndex": 1, "startColumnIndex": 5, "endColumnIndex": 6
                            },
                            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                            "fields": "userEnteredFormat.textFormat.bold",
                        }
                    },
                    # Borda fina embaixo do cabeçalho, separando ele dos dados
                    {
                        "updateBorders": {
                            "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 7},
                            "bottom": {
                                "style": "SOLID_MEDIUM",
                                "color": {"red": 0.10, "green": 0.22, "blue": 0.45},
                            },
                        }
                    },
                    # Ativa o filtro (setinhas no cabeçalho) -- deixa a
                    # secretaria filtrar/ordenar por Status, Curso, etc.
                    # direto na planilha, sem precisar de fórmula nenhuma
                    {
                        "setBasicFilter": {
                            "filter": {
                                "range": {"sheetId": 0, "startRowIndex": 0, "startColumnIndex": 0, "endColumnIndex": 7}
                            }
                        }
                    },
                    # Verde quando Status = "Entregue"
                    {
                        "addConditionalFormatRule": {
                            "rule": {
                                "ranges": [
                                    {"sheetId": 0, "startRowIndex": 1, "startColumnIndex": 5, "endColumnIndex": 6}
                                ],
                                "booleanRule": {
                                    "condition": {
                                        "type": "TEXT_EQ",
                                        "values": [{"userEnteredValue": "Entregue"}],
                                    },
                                    "format": {
                                        "backgroundColor": {"red": 0.71, "green": 0.88, "blue": 0.75}
                                    },
                                },
                            },
                            "index": 0,
                        }
                    },
                    # Dropdown na coluna Status -- a secretaria clica na
                    # setinha e escolhe entre as duas opções, em vez de
                    # digitar o texto (evita erro de digitação que faria
                    # a cor condicional abaixo não bater, tipo "entregue"
                    # com letra minúscula não sendo reconhecido).
                    {
                        "setDataValidation": {
                            "range": {
                                "sheetId": 0, "startRowIndex": 1, "startColumnIndex": 5, "endColumnIndex": 6
                            },
                            "rule": {
                                "condition": {
                                    "type": "ONE_OF_LIST",
                                    "values": [
                                        {"userEnteredValue": "Pendente"},
                                        {"userEnteredValue": "Entregue"},
                                    ],
                                },
                                "showCustomUi": True,
                                "strict": True,
                            },
                        }
                    },
                    # Vermelho quando Status = "Pendente"
                    {
                        "addConditionalFormatRule": {
                            "rule": {
                                "ranges": [
                                    {"sheetId": 0, "startRowIndex": 1, "startColumnIndex": 5, "endColumnIndex": 6}
                                ],
                                "booleanRule": {
                                    "condition": {
                                        "type": "TEXT_EQ",
                                        "values": [{"userEnteredValue": STATUS_PADRAO}],
                                    },
                                    "format": {
                                        "backgroundColor": {"red": 0.96, "green": 0.78, "blue": 0.78}
                                    },
                                },
                            },
                            "index": 1,
                        }
                    },
                ]
            },
        ).execute()

    def adicionar_linha(
        self, spreadsheet_id: str, nome: str, cpf: str, curso: str, data_envio_str: str
    ) -> None:
        """
        Adiciona uma linha para um novo envio. data_envio_str no formato
        "DD/MM/AAAA", pra ser reconhecida como data de verdade pela planilha
        (necessário pra fórmula de dias úteis funcionar).
        """
        resposta = (
            self.service.spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range="A:G",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [[nome, cpf, curso, data_envio_str, "", STATUS_PADRAO, ""]]},
            )
            .execute()
        )

        linha = _extrair_numero_linha(resposta["updates"]["updatedRange"])

        # Locale pt_BR usa ponto-e-vírgula como separador de argumento --
        # essencial pra fórmula não dar erro de sintaxe na planilha.
        formula = f"=NETWORKDAYS({COLUNA_DATA_ENVIO}{linha};TODAY())"
        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{COLUNA_DIAS_UTEIS}{linha}",
            valueInputOption="USER_ENTERED",
            body={"values": [[formula]]},
        ).execute()

    def marcar_aprovado(self, spreadsheet_id: str, cpf: str, aprovado_por: str) -> None:
        """
        Preenche a coluna "Aprovado por" com o nome do revisor que aprovou
        a documentação. Procura a ocorrência mais recente do CPF na
        planilha (última linha que bate) -- cobre o caso de reenvio depois
        de uma reprovação, onde o CPF aparece mais de uma vez.

        Não levanta erro se não achar a linha (planilha apagada/renomeada
        manualmente, por exemplo) -- só não escreve nada, pra não travar
        a aprovação por causa disso.
        """
        resposta = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range="B:B")
            .execute()
        )
        valores = resposta.get("values", [])

        linha_encontrada = None
        for indice, linha in enumerate(valores, start=1):
            if linha and linha[0] == cpf:
                linha_encontrada = indice

        if linha_encontrada is None:
            return

        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{COLUNA_APROVADO_POR}{linha_encontrada}",
            valueInputOption="USER_ENTERED",
            body={"values": [[aprovado_por]]},
        ).execute()


def _extrair_numero_linha(intervalo_atualizado: str) -> int:
    """Extrai o número da linha a partir de um intervalo tipo "Página1!A5:F5"."""
    match = re.search(r"!\D*(\d+)", intervalo_atualizado)
    if not match:
        raise ValueError(f"Não consegui extrair a linha de: {intervalo_atualizado}")
    return int(match.group(1))