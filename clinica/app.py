import os
from datetime import datetime
from flask import Flask
from models import db
from routes import dashboard, agendamentos, financeiro, versatilis, cartao

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'clinica-secret-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(BASE_DIR, 'clinica.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

db.init_app(app)

app.register_blueprint(dashboard.bp)
app.register_blueprint(agendamentos.bp)
app.register_blueprint(financeiro.bp)
app.register_blueprint(versatilis.bp)
app.register_blueprint(cartao.bp)

@app.context_processor
def inject_globals():
    hoje = datetime.today()
    return {
        'now_str': hoje.strftime('%d/%m/%Y'),
        'hoje': hoje.strftime('%Y-%m-%d'),
    }

with app.app_context():
    db.create_all()
    from models import seed_contas_bancarias
    seed_contas_bancarias()

if __name__ == '__main__':
    print("\n" + "="*50)
    print("  Sistema de Clínica Médica")
    print("  Acesse: http://localhost:5000")
    print("="*50 + "\n")
    app.run(debug=True, host='0.0.0.0', port=5000)
