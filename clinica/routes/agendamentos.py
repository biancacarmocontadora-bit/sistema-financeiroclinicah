from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from models import db, Agendamento, ContaReceber, LancamentoBancario, ContaBancaria, TaxaCartao, PagamentoCartao, ParcelaCartao
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import pandas as pd
import io

bp = Blueprint('agendamentos', __name__)

STATUS_LABELS = {
    'agendado': 'Agendado',
    'confirmado': 'Confirmado',
    'realizado': 'Realizado',
    'falta': 'Falta',
    'cancelado': 'Cancelado',
}

STATUS_CORES = {
    'agendado': 'primary',
    'confirmado': 'info',
    'realizado': 'success',
    'falta': 'danger',
    'cancelado': 'secondary',
}

# Status que geram/mantêm conta a receber pendente
STATUS_GERA_CR = {'agendado', 'confirmado'}
# Status que cancelam a conta a receber
STATUS_CANCELA_CR = {'falta', 'cancelado'}
# Status que baixam (recebem) a conta a receber
STATUS_BAIXA_CR = {'realizado'}


def tipo_para_taxa_key(cartao_tipo, parcelas):
    if cartao_tipo == 'debito':
        return 'debito'
    if parcelas == 1:
        return 'credito_1x'
    if parcelas <= 6:
        return 'credito_2_6x'
    return 'credito_7_12x'


def sincronizar_parcelas_cartao(ag: Agendamento):
    """Cria/recria PagamentoCartao + ParcelaCartao quando agendamento tem pagamento em cartão."""
    if ag.forma_pagamento != 'cartao':
        return

    # Remove pagamento anterior vinculado a este agendamento
    pag_antigo = PagamentoCartao.query.filter_by(agendamento_id=ag.id).first()
    if pag_antigo:
        ParcelaCartao.query.filter_by(pagamento_id=pag_antigo.id).delete()
        db.session.delete(pag_antigo)
        db.session.flush()

    bandeira = (ag.cartao_bandeira or 'outros').lower()
    tipo_key = tipo_para_taxa_key(ag.cartao_tipo or 'credito', ag.cartao_parcelas or 1)
    # Normaliza variações de nome de bandeira
    ALIAS_BANDEIRA = {
        'master': 'mastercard', 'master card': 'mastercard',
        'visa electron': 'visa', 'american express': 'amex', 'american': 'amex',
        'hiper': 'hipercard',
    }
    bandeira_norm = ALIAS_BANDEIRA.get(bandeira.lower(), bandeira.lower())

    # Tenta match exato, depois por prefixo, depois 'outros'
    taxa_obj = TaxaCartao.query.filter(
        db.func.lower(TaxaCartao.bandeira) == bandeira_norm, TaxaCartao.tipo == tipo_key
    ).first()
    if not taxa_obj:
        # prefixo (ex: "mastercard" começa com "master")
        for t in TaxaCartao.query.filter_by(tipo=tipo_key).all():
            if t.bandeira.lower().startswith(bandeira_norm) or bandeira_norm.startswith(t.bandeira.lower()):
                taxa_obj = t
                break
    if not taxa_obj:
        taxa_obj = TaxaCartao.query.filter(
            db.func.lower(TaxaCartao.bandeira) == 'outros', TaxaCartao.tipo == tipo_key
        ).first()
    taxa_pct = taxa_obj.taxa_percentual if taxa_obj else 0.0
    dias_repasse = taxa_obj.dias_repasse if taxa_obj else 30

    valor_bruto = ag.valor or 0.0
    n = ag.cartao_parcelas or 1
    valor_taxa_total = round(valor_bruto * taxa_pct / 100, 2)
    valor_liquido_total = round(valor_bruto - valor_taxa_total, 2)

    pag = PagamentoCartao(
        agendamento_id=ag.id,
        paciente=ag.paciente,
        descricao=f"Consulta – {ag.tipo_consulta or ag.especialidade or 'Atendimento'}",
        bandeira=bandeira,
        tipo=tipo_key,
        num_parcelas=n,
        valor_bruto=valor_bruto,
        taxa_percentual=taxa_pct,
        valor_taxa=valor_taxa_total,
        valor_liquido=valor_liquido_total,
        data_venda=ag.data_hora.date(),
        conta_id=ag.conta_bancaria_id,
    )
    db.session.add(pag)
    db.session.flush()

    bruto_parcela = round(valor_bruto / n, 2)
    liquido_parcela = round(valor_liquido_total / n, 2)
    acerto = round(valor_liquido_total - liquido_parcela * n, 2)

    data_base = ag.data_hora.date()
    for i in range(1, n + 1):
        if ag.cartao_tipo == 'debito':
            data_prev = data_base + relativedelta(days=dias_repasse)
        else:
            data_prev = data_base + relativedelta(days=dias_repasse) + relativedelta(months=i - 1)

        liq = liquido_parcela + (acerto if i == n else 0)
        taxa_p = round(bruto_parcela * taxa_pct / 100, 2)

        p = ParcelaCartao(
            pagamento_id=pag.id,
            numero=i,
            valor_bruto_parcela=bruto_parcela,
            taxa_parcela=taxa_p,
            valor_liquido_parcela=liq,
            data_prevista=data_prev,
            status='pendente',
        )
        db.session.add(p)


def sincronizar_conta_receber(ag: Agendamento):
    """
    Mantém ContaReceber sincronizada com o status do agendamento.
    Pagamentos em cartão não geram ContaReceber — as parcelas já cobrem.
    """
    cr = ContaReceber.query.filter_by(agendamento_id=ag.id).first()

    # Cartão: cancela/remove ContaReceber se existir
    if ag.forma_pagamento == 'cartao':
        if cr and cr.status == 'pendente':
            cr.status = 'cancelado'
        return

    if ag.status in STATUS_GERA_CR:
        if cr is None:
            cr = ContaReceber(agendamento_id=ag.id)
            db.session.add(cr)
        cr.paciente = ag.paciente
        cr.medico = ag.medico or ''
        cr.convenio = ag.convenio or ''
        cr.descricao = f"Consulta – {ag.tipo_consulta or ag.especialidade or 'Atendimento'}"
        cr.valor = ag.valor or 0.0
        cr.data_prevista = ag.data_hora.date()
        if cr.status == 'cancelado':
            cr.status = 'pendente'

    elif ag.status in STATUS_BAIXA_CR:
        if cr and cr.status == 'pendente':
            cr.status = 'recebido'
            cr.data_recebimento = ag.data_hora.date()

    elif ag.status in STATUS_CANCELA_CR:
        if cr and cr.status == 'pendente':
            cr.status = 'cancelado'


@bp.route('/agendamentos')
def lista():
    page = request.args.get('page', 1, type=int)
    data_ini = request.args.get('data_ini', '')
    data_fim = request.args.get('data_fim', '')
    status = request.args.get('status', '')
    medico = request.args.get('medico', '')
    busca = request.args.get('busca', '')

    q = Agendamento.query

    if data_ini:
        q = q.filter(Agendamento.data_hora >= datetime.strptime(data_ini, '%Y-%m-%d'))
    if data_fim:
        q = q.filter(Agendamento.data_hora <= datetime.strptime(data_fim + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
    if status:
        q = q.filter(Agendamento.status == status)
    if medico:
        q = q.filter(Agendamento.medico.ilike(f'%{medico}%'))
    if busca:
        q = q.filter(Agendamento.paciente.ilike(f'%{busca}%'))

    agendamentos = q.order_by(Agendamento.data_hora.desc()).paginate(page=page, per_page=50)
    medicos = db.session.query(Agendamento.medico).distinct().all()

    return render_template('agendamentos.html',
        agendamentos=agendamentos,
        status_labels=STATUS_LABELS,
        status_cores=STATUS_CORES,
        medicos=[m[0] for m in medicos if m[0]],
        filtros={'data_ini': data_ini, 'data_fim': data_fim, 'status': status, 'medico': medico, 'busca': busca},
    )


@bp.route('/agendamentos/novo', methods=['GET', 'POST'])
def novo():
    if request.method == 'POST':
        ag = Agendamento(
            paciente=request.form['paciente'],
            medico=request.form.get('medico', ''),
            especialidade=request.form.get('especialidade', ''),
            data_hora=datetime.strptime(request.form['data_hora'], '%Y-%m-%dT%H:%M'),
            status=request.form.get('status', 'agendado'),
            convenio=request.form.get('convenio', ''),
            tipo_consulta=request.form.get('tipo_consulta', ''),
            valor=float(request.form.get('valor', 0) or 0),
            forma_pagamento=request.form.get('forma_pagamento', '') or None,
            cartao_tipo=request.form.get('cartao_tipo', '') or None,
            cartao_bandeira=request.form.get('cartao_bandeira', '') or None,
            cartao_parcelas=int(request.form.get('cartao_parcelas', 1) or 1),
            conta_bancaria_id=int(request.form.get('conta_bancaria_id')) if request.form.get('conta_bancaria_id') else None,
            observacao=request.form.get('observacao', ''),
        )
        db.session.add(ag)
        db.session.flush()
        sincronizar_conta_receber(ag)
        sincronizar_parcelas_cartao(ag)
        db.session.commit()
        flash('Agendamento criado com sucesso!', 'success')
        next_url = request.form.get('next') or url_for('agendamentos.lista')
        return redirect(next_url)
    return render_template('agendamento_form.html', ag=None, status_labels=STATUS_LABELS)


@bp.route('/agendamentos/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    ag = Agendamento.query.get_or_404(id)
    if request.method == 'POST':
        ag.paciente = request.form['paciente']
        ag.medico = request.form.get('medico', '')
        ag.especialidade = request.form.get('especialidade', '')
        ag.data_hora = datetime.strptime(request.form['data_hora'], '%Y-%m-%dT%H:%M')
        ag.status = request.form.get('status', 'agendado')
        ag.convenio = request.form.get('convenio', '')
        ag.tipo_consulta = request.form.get('tipo_consulta', '')
        ag.valor = float(request.form.get('valor', 0) or 0)
        ag.forma_pagamento = request.form.get('forma_pagamento', '') or None
        ag.cartao_tipo = request.form.get('cartao_tipo', '') or None
        ag.cartao_bandeira = request.form.get('cartao_bandeira', '') or None
        ag.cartao_parcelas = int(request.form.get('cartao_parcelas', 1) or 1)
        ag.conta_bancaria_id = int(request.form.get('conta_bancaria_id')) if request.form.get('conta_bancaria_id') else None
        ag.observacao = request.form.get('observacao', '')
        sincronizar_conta_receber(ag)
        sincronizar_parcelas_cartao(ag)
        db.session.commit()
        flash('Agendamento atualizado!', 'success')
        next_url = request.form.get('next') or url_for('agendamentos.lista')
        return redirect(next_url)
    return render_template('agendamento_form.html', ag=ag, status_labels=STATUS_LABELS)


@bp.route('/agendamentos/<int:id>/status', methods=['POST'])
def atualizar_status(id):
    ag = Agendamento.query.get_or_404(id)
    ag.status = request.json.get('status', ag.status)
    sincronizar_conta_receber(ag)
    db.session.commit()
    return jsonify({'ok': True, 'status': ag.status})


@bp.route('/agendamentos/importar', methods=['POST'])
def importar():
    import io as _io, os as _os

    # Suporte a caminho local (para .xls do Versatilis com pasta _arquivos)
    caminho_local = request.form.get('caminho_local', '').strip()
    if caminho_local:
        caminho_local = caminho_local.strip('"').strip("'")
        nome = caminho_local.lower()
        try:
            if nome.endswith('.xls'):
                base = _os.path.splitext(caminho_local)[0]
                nome_base = _os.path.basename(base)
                pasta = _os.path.dirname(caminho_local)
                sheet = _os.path.join(pasta, nome_base + '_arquivos', 'sheet001.htm')
                if not _os.path.exists(sheet):
                    # tenta outras variações
                    for f in _os.listdir(pasta):
                        if f.endswith('_arquivos') or f.endswith(' arquivos'):
                            sheet = _os.path.join(pasta, f, 'sheet001.htm')
                            if _os.path.exists(sheet):
                                break
                if not _os.path.exists(sheet):
                    # Sem pasta _arquivos: tenta ler o .xls diretamente como HTML
                    try:
                        dfs = pd.read_html(caminho_local, encoding='utf-8', header=0)
                    except Exception:
                        dfs = pd.read_html(caminho_local, encoding='cp1252', header=0)
                    df = dfs[0]
                else:
                    dfs = pd.read_html(sheet, encoding='utf-8', header=0)
                    df = dfs[0]
            elif nome.endswith('.htm') or nome.endswith('.html'):
                dfs = pd.read_html(caminho_local, encoding='utf-8', header=0)
                df = dfs[0]
            elif nome.endswith('.xlsx'):
                df = pd.read_excel(caminho_local, engine='openpyxl')
            elif nome.endswith('.csv'):
                df = pd.read_csv(caminho_local, encoding='utf-8-sig')
            else:
                return jsonify({'erro': 'Formato não suportado.'}), 400
        except Exception as e:
            return jsonify({'erro': f'Erro ao ler arquivo: {str(e)}'}), 400
    else:
        arquivo = request.files.get('arquivo')
        if not arquivo:
            return jsonify({'erro': 'Nenhum arquivo enviado'}), 400

    try:
        if not caminho_local:
            nome = arquivo.filename.lower()
            if nome.endswith('.csv'):
                df = pd.read_csv(arquivo, encoding='utf-8-sig')
            elif nome.endswith('.xlsx'):
                df = pd.read_excel(arquivo, engine='openpyxl')
            elif nome.endswith('.htm') or nome.endswith('.html'):
                conteudo = arquivo.read()
                dfs = pd.read_html(_io.BytesIO(conteudo), encoding='utf-8', header=0)
                df = dfs[0]
            elif nome.endswith('.xls'):
                try:
                    df = pd.read_excel(arquivo, engine='xlrd')
                except Exception:
                    arquivo.seek(0)
                    conteudo = arquivo.read()
                    if b'_arquivos' in conteudo or b'frameset' in conteudo.lower():
                        return jsonify({'erro': 'Cole o caminho completo do .xls no campo "Caminho do arquivo" para importar automaticamente.'}), 400
                    dfs = pd.read_html(_io.BytesIO(conteudo), encoding='utf-8', header=0)
                    df = dfs[0]
            else:
                return jsonify({'erro': 'Formato não suportado. Use CSV, XLSX ou HTM.'}), 400

        # Normaliza colunas: remove acentos, espaços extras, quebras
        import unicodedata
        def normalizar_col(c):
            c = str(c).strip().replace('\n', ' ')
            while '  ' in c:
                c = c.replace('  ', ' ')
            # Remove acentos
            c = ''.join(ch for ch in unicodedata.normalize('NFD', c) if unicodedata.category(ch) != 'Mn')
            return c
        df.columns = [normalizar_col(c) for c in df.columns]

        # Mapeamento de colunas flexível (Versatilis e genérico)
        mapa_colunas = {
            'paciente': ['PACIENTE', 'paciente', 'nome', 'patient', 'nome_paciente', 'NOME'],
            'medico': ['MEDICO', 'medico', 'profissional', 'doctor'],
            'especialidade': ['ESPECIALIDADE', 'especialidade', 'specialty'],
            'data_hora': ['DATA', 'data_hora', 'data', 'date', 'datetime', 'DATA_HORA', 'data_agendamento'],
            'hora': ['Unnamed: 1', 'hora', 'time', 'HORA'],
            'status': ['STATUS AGENDAMENTO', 'status', 'situacao', 'STATUS'],
            'convenio': ['CONVENIO', 'convenio', 'plano', 'PLANO'],
            'valor': ['VALOR', 'valor', 'value', 'preco'],
            'tipo_consulta': ['PROCEDIMENTO', 'procedimento', 'tipo_consulta', 'tipo', 'TIPO'],
            'id_externo': ['CODCONSULTA', 'id', 'ID', 'codigo', 'id_agendamento'],
        }

        # Mapa de status do Versatilis para status internos
        STATUS_VERSATILIS = {
            'procedimento confirmado': 'confirmado',
            'consulta confirmada': 'confirmado',
            'confirmado': 'confirmado',
            'procedimento cancelado pelo paciente': 'cancelado',
            'consulta cancelada pelo paciente': 'cancelado',
            'procedimento cancelado': 'cancelado',
            'consulta cancelada': 'cancelado',
            'cancelado': 'cancelado',
            'procedimento realizado': 'realizado',
            'consulta realizada': 'realizado',
            'realizado': 'realizado',
            'agendado': 'agendado',
            'falta': 'falta',
            'paciente faltou': 'falta',
            'nao compareceu': 'falta',
            'não compareceu': 'falta',
        }
        col_map = {}
        for campo, opcoes in mapa_colunas.items():
            for op in opcoes:
                if op in df.columns:
                    col_map[campo] = op
                    break

        if 'paciente' not in col_map:
            return jsonify({'erro': 'Coluna "paciente" não encontrada. Verifique o arquivo.'}), 400
        if 'data_hora' not in col_map:
            return jsonify({'erro': 'Coluna de data não encontrada.'}), 400

        inseridos = 0
        atualizados = 0
        erros = 0

        for _, row in df.iterrows():
            try:
                paciente = str(row[col_map['paciente']]).strip()
                if not paciente or paciente == 'nan':
                    continue

                data_val = row[col_map['data_hora']]
                hora_val = row.get(col_map.get('hora', ''), '') if col_map.get('hora') else ''

                if pd.isna(data_val):
                    continue

                if isinstance(data_val, str):
                    for fmt in ['%d/%m/%Y %H:%M', '%Y-%m-%d %H:%M', '%d/%m/%Y', '%Y-%m-%d']:
                        try:
                            data_hora = datetime.strptime(data_val.strip(), fmt)
                            break
                        except:
                            continue
                    else:
                        continue
                else:
                    data_hora = pd.Timestamp(data_val).to_pydatetime()

                if hora_val and not pd.isna(hora_val):
                    try:
                        h, m = str(hora_val).strip().split(':')[:2]
                        data_hora = data_hora.replace(hour=int(h), minute=int(m))
                    except:
                        pass

                id_ext = str(row.get(col_map.get('id_externo', ''), '')).strip() if col_map.get('id_externo') else None
                if id_ext == 'nan':
                    id_ext = None

                ag_existente = Agendamento.query.filter_by(id_externo=id_ext).first() if id_ext else None

                if ag_existente:
                    ag = ag_existente
                    atualizados += 1
                else:
                    ag = Agendamento()
                    db.session.add(ag)
                    inseridos += 1

                ag.paciente = paciente
                ag.id_externo = id_ext
                ag.data_hora = data_hora
                ag.medico = str(row[col_map['medico']]).strip() if col_map.get('medico') and not pd.isna(row.get(col_map['medico'])) else ''
                ag.especialidade = str(row[col_map['especialidade']]).strip() if col_map.get('especialidade') and not pd.isna(row.get(col_map['especialidade'])) else ''
                if col_map.get('status') and not pd.isna(row.get(col_map['status'])):
                    status_raw = str(row[col_map['status']]).strip().lower()
                    ag.status = STATUS_VERSATILIS.get(status_raw, status_raw if status_raw in ('agendado','confirmado','realizado','falta','cancelado') else 'agendado')
                else:
                    ag.status = 'agendado'
                ag.convenio = str(row[col_map['convenio']]).strip() if col_map.get('convenio') and not pd.isna(row.get(col_map['convenio'])) else ''
                ag.tipo_consulta = str(row[col_map['tipo_consulta']]).strip() if col_map.get('tipo_consulta') and not pd.isna(row.get(col_map['tipo_consulta'])) else ''
                ag.valor = float(row[col_map['valor']]) if col_map.get('valor') and not pd.isna(row.get(col_map['valor'])) else 0.0
                db.session.flush()
                sincronizar_conta_receber(ag)

            except Exception as e:
                erros += 1
                continue

        db.session.commit()
        return jsonify({'ok': True, 'inseridos': inseridos, 'atualizados': atualizados, 'erros': erros})

    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500
