from flask import Blueprint, render_template, request, jsonify
from models import db, Agendamento, ConfiguracaoVersatilis
from datetime import datetime, date
import requests as req

bp = Blueprint('versatilis', __name__)


def get_config(chave, padrao=''):
    cfg = ConfiguracaoVersatilis.query.filter_by(chave=chave).first()
    return cfg.valor if cfg else padrao


def set_config(chave, valor):
    cfg = ConfiguracaoVersatilis.query.filter_by(chave=chave).first()
    if cfg:
        cfg.valor = valor
    else:
        cfg = ConfiguracaoVersatilis(chave=chave, valor=valor)
        db.session.add(cfg)
    db.session.commit()


@bp.route('/versatilis')
def configuracoes():
    configs = {
        'url_base': get_config('url_base'),
        'api_key': get_config('api_key'),
        'usuario': get_config('usuario'),
        'senha': get_config('senha'),
        'clinica_id': get_config('clinica_id'),
        'ultimo_sync': get_config('ultimo_sync', 'Nunca'),
    }
    return render_template('versatilis.html', configs=configs)


@bp.route('/versatilis/salvar-config', methods=['POST'])
def salvar_config():
    for chave in ['url_base', 'api_key', 'usuario', 'senha', 'clinica_id']:
        valor = request.form.get(chave, '')
        set_config(chave, valor)
    return jsonify({'ok': True})


@bp.route('/versatilis/testar-conexao', methods=['POST'])
def testar_conexao():
    url_base = get_config('url_base')
    api_key = get_config('api_key')
    usuario = get_config('usuario')
    senha = get_config('senha')

    if not url_base:
        return jsonify({'ok': False, 'erro': 'URL da API não configurada'})

    try:
        headers = {}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        # Tenta endpoint comum de health check / autenticação
        for endpoint in ['/api/health', '/api/v1/health', '/health', '/api/auth']:
            try:
                resp = req.get(f"{url_base.rstrip('/')}{endpoint}", headers=headers, timeout=5)
                if resp.status_code < 500:
                    return jsonify({'ok': True, 'mensagem': f'Conexão OK (status {resp.status_code})'})
            except:
                continue

        return jsonify({'ok': False, 'erro': 'Não foi possível conectar. Verifique a URL e credenciais.'})
    except Exception as e:
        return jsonify({'ok': False, 'erro': str(e)})


@bp.route('/versatilis/sincronizar', methods=['POST'])
def sincronizar():
    url_base = get_config('url_base')
    api_key = get_config('api_key')
    data_ini = request.json.get('data_ini', date.today().isoformat())
    data_fim = request.json.get('data_fim', date.today().isoformat())

    if not url_base:
        return jsonify({'ok': False, 'erro': 'Configure a URL da API do Versatilis primeiro'})

    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    # Endpoints comuns do Versatilis / sistemas de clínica
    endpoints_tentativa = [
        f'/api/agendamentos?data_inicio={data_ini}&data_fim={data_fim}',
        f'/api/v1/agendamentos?data_inicio={data_ini}&data_fim={data_fim}',
        f'/api/appointments?start={data_ini}&end={data_fim}',
        f'/api/v1/schedule?start={data_ini}&end={data_fim}',
    ]

    dados = None
    for endpoint in endpoints_tentativa:
        try:
            resp = req.get(f"{url_base.rstrip('/')}{endpoint}", headers=headers, timeout=10)
            if resp.status_code == 200:
                dados = resp.json()
                break
        except:
            continue

    if dados is None:
        return jsonify({
            'ok': False,
            'erro': 'Não foi possível buscar agendamentos. Use a importação CSV como alternativa.',
            'dica': 'Exporte os agendamentos do Versatilis como CSV e use a função de importação.'
        })

    # Processar os dados recebidos
    inseridos = 0
    atualizados = 0

    lista = dados if isinstance(dados, list) else dados.get('data', dados.get('agendamentos', dados.get('items', [])))

    for item in lista:
        try:
            id_ext = str(item.get('id', '') or item.get('codigo', '')).strip()
            ag = Agendamento.query.filter_by(id_externo=id_ext).first() if id_ext else None

            if not ag:
                ag = Agendamento()
                db.session.add(ag)
                inseridos += 1
            else:
                atualizados += 1

            ag.id_externo = id_ext
            ag.paciente = item.get('paciente', item.get('patient', item.get('nome_paciente', '')))
            ag.medico = item.get('medico', item.get('profissional', item.get('doctor', '')))
            ag.especialidade = item.get('especialidade', item.get('specialty', ''))
            ag.convenio = item.get('convenio', item.get('plano', ''))
            ag.tipo_consulta = item.get('tipo_consulta', item.get('procedimento', ''))
            ag.valor = float(item.get('valor', 0) or 0)

            status_raw = str(item.get('status', item.get('situacao', 'agendado'))).lower()
            mapa_status = {
                'agendado': 'agendado', 'scheduled': 'agendado',
                'confirmado': 'confirmado', 'confirmed': 'confirmado',
                'realizado': 'realizado', 'attended': 'realizado', 'present': 'realizado',
                'falta': 'falta', 'no-show': 'falta', 'absent': 'falta', 'ausente': 'falta',
                'cancelado': 'cancelado', 'canceled': 'cancelado', 'cancelled': 'cancelado',
            }
            ag.status = mapa_status.get(status_raw, 'agendado')

            data_str = item.get('data_hora', item.get('data', item.get('date', item.get('datetime', ''))))
            if data_str:
                for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M', '%d/%m/%Y %H:%M', '%Y-%m-%d']:
                    try:
                        ag.data_hora = datetime.strptime(str(data_str)[:19], fmt)
                        break
                    except:
                        continue
        except:
            continue

    db.session.commit()
    set_config('ultimo_sync', datetime.now().strftime('%d/%m/%Y %H:%M'))

    return jsonify({'ok': True, 'inseridos': inseridos, 'atualizados': atualizados})
