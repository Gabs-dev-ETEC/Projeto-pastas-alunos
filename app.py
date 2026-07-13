import click
from flask import Flask
from flask_login import LoginManager

from config import Config
from models import db, Revisor
from routes.upload import upload_bp
from routes.painel import painel_bp

login_manager = LoginManager()
login_manager.login_view = "painel.login"


@login_manager.user_loader
def carregar_revisor(revisor_id):
    return Revisor.query.get(int(revisor_id))


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)

    app.register_blueprint(upload_bp)
    app.register_blueprint(painel_bp)

    with app.app_context():
        db.create_all()

    @app.cli.command("criar-revisor")
    @click.argument("username")
    @click.argument("nome")
    @click.password_option()
    def criar_revisor(username, nome, password):
        """Cria (ou reseta a senha de) um usuário do painel de revisão.

        Uso: flask criar-revisor fulano "Fulano de Tal"
        (vai pedir a senha interativamente, duas vezes, sem ela aparecer
        na tela nem ficar salva no histórico do terminal)
        """
        revisor = Revisor.query.filter_by(username=username).first()
        if revisor is None:
            revisor = Revisor(username=username, nome=nome)
            db.session.add(revisor)
        else:
            revisor.nome = nome
        revisor.set_senha(password)
        db.session.commit()
        click.echo(f"Revisor '{username}' criado/atualizado com sucesso.")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5001)
