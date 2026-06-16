from flask import Blueprint, render_template, request, jsonify
from models import db, PagamentoCartao, ParcelaCartao, TaxaCartao, LancamentoBancario
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from sqlalchemy import func, extract

bp = Blueprint('cartao', __name__)

BANDEIRAS = ['Visa', 'Mastercard', 'Elo', 'Amex', 'Hipercard']

# Tipo legível
TIPO_LABEL = {
    'debito': 'Débito',
    'credito_1x': 'Crédito 1x',
    'credito_2_6x': 'Crédito 2–6x',
    'credito_7_12x': 'Crédito 7–12x',
}

# Taxas padrão caso o usuário não tenha configurado ainda
TAXAS_PADRAO = [
    ('Visa',       'debito',        1.49, 1),
    ('Visa',       'credito_1x',    2.49, 30),
    ('Visa',       'credito_2_6x',  2.99, 30),
    ('Visa',       'credito_7_12x', 3.49, 30),
    ('Mastercard', 'debito',        1.49, 1),
    ('Mastercard', 'credito_1x',    2.49, 30),
    ('Mastercard', 'credito_2_6x',  2.99, 30),
    ('Mastercard', 'credito_7_12x', 3.49, 30),
    ('Elo',        'debito',        1.69, 1),
    ('Elo',        'credito_1x',    2.69, 30),
    ('Elo',        'credito_2_6x',  3.19, 30),
    ('Elo',        'credito_7_12x', 3.69, 30),
    ('Amex',       'credito_1x',    3.09, 30),
    ('Amex',       'credito_2_6x',  3.59, 30),
    ('Amex',       'credito_7_12x', 4.09, 30),
    ('Hipercard',  'credito_1x',    2.69, 30),
    ('Hipercard',  'credito_2_6x',  3.19, 30),
    ('Hipercard',  'credito_7_12x', 3.69, 30),
    ('outros',     'debito',        1.49, 1),
    ('outros',     'credito_1x',    2.49, 30),
    ('outros',     'credito_2_6x',  2.99, 30),
    ('outros',     'credito_7_12x', 3.49, 30),
]


def garantir_taxas_padrao():
    """Popula taxas padrão se a tabela estiver vazia."""
    if TaxaCartao.query.count() == 0:
        for bandeira, tipo, taxa, dias in TAXAS_PADRAO:
            db.session.add(TaxaCartao(
                bandeira=bandeira, tipo=tipo,
                taxa_percentual=taxa, dias_repasse=dias
            ))
        db.session.commit()


def tipo_credito_para(num_parcelas: int) -> str:
    if num_parcelas <= 1:
        return 'credito_1x'
    elif num_parcelas <= 6:
        return 'credito_2_6x'
    else:
        return 'credito_7_12x'


def buscar_taxa(bandeira: str, tipo: str) -> TaxaCartao | None:
    return TaxaCartao.query.filter_by(bandeira=bandeira, tipo=tipo).first()


def calcular_parcelas(valor_bruto: float, num_parcelas: int, taxa_pct: float,
                      data_venda: date, dias_repasse: int, tipo: str) -> list[dict]:
    """Retorna lista de dicts com dados de cada parcela."""
    valor_bruto_parcela = round(valor_bruto / num_parcelas, 2)
    # Ajuste de arredondamento na última parcela
    ajuste = round(valor_bruto - valor_bruto_parcela * num_parcelas, 2)

    taxa_unit = taxa_pct / 100
    parcelas = []

    for i in range(1, num_parcelas + 1):
        vbp = valor_bruto_parcela + (ajuste if i == num_parcelas else 0)
        taxa_r = round(vbp * taxa_unit, 2)
        vlp = round(vbp - taxa_r, 2)

        if tipo == 'debito':
            data_prev = data_venda + timedelta(days=dias_repasse)
        else:
            # Crédito: D+30 para 1ª parcela, +30 dias para cada parcela seguinte
            data_prev = data_venda + relativedelta(days=dias_repasse) + relativedelta(months=i - 1)

        parcelas.append({
            'numero': i,
            'valor_bruto_parcela': vbp,
            'taxa_parcela': taxa_r,
            'valor_liquido_parcela': vlp,
            'data_prevista': data_prev,
        })

    return parcelas


# ── ROTAS ────────────────────────────────────────────────────────────────────

@bp.route('/cartao')
def lista():
    garantir_taxas_padrao()
    page = request.args.get('page', 1, type=int)
    bandeira = request.args.get('bandeira', '')
    status = request.args.get('status', '')
    data_ini = request.args.get('data_ini', '')
    data_fim = request.args.get('data_fim', '')

    q = PagamentoCartao.query
    if bandeira:
        q = q.filter(PagamentoCartao.bandeira == bandeira)
    if status:
        q = q.filter(PagamentoCartao.status == status)
    if data_ini:
        q = q.filter(PagamentoCartao.data_venda >= datetime.strptime(data_ini, '%Y-%m-%d').date())
    if data_fim:
        q = q.filter(PagamentoCartao.data_venda <= datetime.strptime(data_fim, '%Y-%m-%d').date())

    pagamentos = q.order_by(PagamentoCartao.data_venda.desc()).paginate(page=page, per_page=50)

    # KPIs
    hoje = date.today()
    mes = hoje.month
    ano = hoje.year

    bruto_mes = db.session.query(func.sum(PagamentoCartao.valor_bruto)).filter(
        extract('month', PagamentoCartao.data_venda) == mes,
        extract('year', PagamentoCartao.data_venda) == ano,
        PagamentoCartao.status == 'ativo',
    ).scalar() or 0

    taxas_mes = db.session.query(func.sum(PagamentoCartao.valor_taxa)).filter(
        extract('month', PagamentoCartao.data_venda) == mes,
        extract('year', PagamentoCartao.data_venda) == ano,
        PagamentoCartao.status == 'ativo',
    ).scalar() or 0

    liquido_mes = bruto_mes - taxas_mes

    # Recebíveis próximos 30 dias
    receber_30d = db.session.query(func.sum(ParcelaCartao.valor_liquido_parcela)).filter(
        ParcelaCartao.data_prevista >= hoje,
        ParcelaCartao.data_prevista <= hoje + timedelta(days=30),
        ParcelaCartao.status == 'pendente',
    ).scalar() or 0

    return render_template('cartao.html',
        pagamentos=pagamentos,
        bandeiras=BANDEIRAS,
        tipo_label=TIPO_LABEL,
        filtros={'bandeira': bandeira, 'status': status, 'data_ini': data_ini, 'data_fim': data_fim},
        bruto_mes=bruto_mes,
        taxas_mes=taxas_mes,
        liquido_mes=liquido_mes,
        receber_30d=receber_30d,
    )


@bp.route('/cartao/parcelas')
def parcelas():
    """Visão de recebíveis futuros provisionados."""
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'pendente')
    data_ini = request.args.get('data_ini', '')
    data_fim = request.args.get('data_fim', '')

    q = ParcelaCartao.query.join(PagamentoCartao).filter(PagamentoCartao.status == 'ativo')
    if status:
        q = q.filter(ParcelaCartao.status == status)
    if data_ini:
        q = q.filter(ParcelaCartao.data_prevista >= datetime.strptime(data_ini, '%Y-%m-%d').date())
    if data_fim:
        q = q.filter(ParcelaCartao.data_prevista <= datetime.strptime(data_fim, '%Y-%m-%d').date())

    parcelas_pg = q.order_by(ParcelaCartao.data_prevista).paginate(page=page, per_page=50)

    hoje = date.today()
    total_pendente = db.session.query(func.sum(ParcelaCartao.valor_liquido_parcela)).filter(
        ParcelaCartao.status == 'pendente'
    ).scalar() or 0

    total_vencido = db.session.query(func.sum(ParcelaCartao.valor_liquido_parcela)).filter(
        ParcelaCartao.status == 'pendente',
        ParcelaCartao.data_prevista < hoje,
    ).scalar() or 0

    return render_template('cartao_parcelas.html',
        parcelas=parcelas_pg,
        total_pendente=total_pendente,
        total_vencido=total_vencido,
        filtros={'status': status, 'data_ini': data_ini, 'data_fim': data_fim},
    )


@bp.route('/cartao/simular', methods=['POST'])
def simular():
    """Retorna preview das parcelas antes de salvar."""
    data = request.json
    try:
        bandeira = data['bandeira']
        tipo_pgto = data['tipo']        # 'debito' ou 'credito'
        num_parcelas = int(data.get('num_parcelas', 1))
        valor_bruto = float(data['valor_bruto'])
        data_venda = datetime.strptime(data['data_venda'], '%Y-%m-%d').date()

        if tipo_pgto == 'debito':
            tipo_taxa = 'debito'
        else:
            tipo_taxa = tipo_credito_para(num_parcelas)

        taxa_obj = buscar_taxa(bandeira, tipo_taxa)
        if not taxa_obj:
            return jsonify({'erro': f'Taxa não configurada para {bandeira} / {TIPO_LABEL.get(tipo_taxa, tipo_taxa)}'}), 400

        parcelas_calc = calcular_parcelas(
            valor_bruto, num_parcelas, taxa_obj.taxa_percentual,
            data_venda, taxa_obj.dias_repasse, tipo_pgto
        )

        total_taxa = sum(p['taxa_parcela'] for p in parcelas_calc)
        total_liquido = sum(p['valor_liquido_parcela'] for p in parcelas_calc)

        return jsonify({
            'ok': True,
            'taxa_percentual': taxa_obj.taxa_percentual,
            'total_taxa': round(total_taxa, 2),
            'total_liquido': round(total_liquido, 2),
            'parcelas': [
                {**p, 'data_prevista': p['data_prevista'].strftime('%d/%m/%Y')}
                for p in parcelas_calc
            ]
        })
    except Exception as e:
        return jsonify({'erro': str(e)}), 400


@bp.route('/cartao/registrar', methods=['POST'])
def registrar():
    """Salva o pagamento e gera as parcelas provisionadas."""
    data = request.json
    try:
        bandeira = data['bandeira']
        tipo_pgto = data['tipo']
        num_parcelas = int(data.get('num_parcelas', 1))
        valor_bruto = float(data['valor_bruto'])
        data_venda = datetime.strptime(data['data_venda'], '%Y-%m-%d').date()

        if tipo_pgto == 'debito':
            tipo_taxa = 'debito'
            num_parcelas = 1
        else:
            tipo_taxa = tipo_credito_para(num_parcelas)

        taxa_obj = buscar_taxa(bandeira, tipo_taxa)
        if not taxa_obj:
            return jsonify({'erro': f'Taxa não configurada para {bandeira} / {tipo_taxa}'}), 400

        parcelas_calc = calcular_parcelas(
            valor_bruto, num_parcelas, taxa_obj.taxa_percentual,
            data_venda, taxa_obj.dias_repasse, tipo_pgto
        )

        total_taxa = round(sum(p['taxa_parcela'] for p in parcelas_calc), 2)
        total_liquido = round(valor_bruto - total_taxa, 2)

        pgto = PagamentoCartao(
            agendamento_id=data.get('agendamento_id'),
            paciente=data['paciente'],
            descricao=data.get('descricao', ''),
            bandeira=bandeira,
            tipo=tipo_pgto,
            num_parcelas=num_parcelas,
            valor_bruto=valor_bruto,
            taxa_percentual=taxa_obj.taxa_percentual,
            valor_taxa=total_taxa,
            valor_liquido=total_liquido,
            data_venda=data_venda,
            observacao=data.get('observacao', ''),
        )
        db.session.add(pgto)
        db.session.flush()

        for p in parcelas_calc:
            db.session.add(ParcelaCartao(
                pagamento_id=pgto.id,
                numero=p['numero'],
                valor_bruto_parcela=p['valor_bruto_parcela'],
                taxa_parcela=p['taxa_parcela'],
                valor_liquido_parcela=p['valor_liquido_parcela'],
                data_prevista=p['data_prevista'],
            ))

        db.session.commit()
        return jsonify({'ok': True, 'id': pgto.id, 'num_parcelas': num_parcelas,
                        'valor_liquido': total_liquido, 'valor_taxa': total_taxa})
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500


@bp.route('/cartao/parcela/<int:id>/receber', methods=['POST'])
def receber_parcela(id):
    """Marca a parcela como recebida e cria lançamento bancário."""
    parcela = ParcelaCartao.query.get_or_404(id)
    data_rec = request.json.get('data_recebimento', date.today().isoformat())
    conta_id = request.json.get('conta_id')

    # Resolve conta bancária
    conta_obj = None
    conta_nome = 'Principal'
    if conta_id:
        from models import ContaBancaria
        conta_obj = ContaBancaria.query.get(int(conta_id))
        if conta_obj:
            conta_nome = conta_obj.nome

    parcela.status = 'recebido'
    parcela.data_recebimento = datetime.strptime(data_rec, '%Y-%m-%d').date()

    pgto = parcela.pagamento
    paciente = pgto.agendamento.paciente if pgto.agendamento else (pgto.paciente or '')
    desc = f"Cartão {pgto.bandeira} {parcela.numero}/{pgto.num_parcelas} – {paciente}"

    lanc = LancamentoBancario(
        conta=conta_nome,
        conta_id=conta_obj.id if conta_obj else None,
        data=parcela.data_recebimento,
        descricao=desc,
        valor=parcela.valor_liquido_parcela,
        tipo='credito',
        categoria='Recebimento cartão',
        origem='cartao',
        medico=pgto.agendamento.medico if pgto.agendamento else None,
    )
    db.session.add(lanc)
    db.session.flush()
    parcela.lancamento_id = lanc.id
    db.session.commit()

    return jsonify({'ok': True, 'lancamento_id': lanc.id})


@bp.route('/cartao/<int:id>/cancelar', methods=['POST'])
def cancelar_pagamento(id):
    pgto = PagamentoCartao.query.get_or_404(id)
    pgto.status = 'cancelado'
    for p in pgto.parcelas:
        if p.status == 'pendente':
            p.status = 'cancelado'
    db.session.commit()
    return jsonify({'ok': True})


# ── TAXAS ────────────────────────────────────────────────────────────────────

@bp.route('/cartao/taxas')
def taxas():
    garantir_taxas_padrao()
    todas = TaxaCartao.query.order_by(TaxaCartao.bandeira, TaxaCartao.tipo).all()
    return render_template('cartao_taxas.html', taxas=todas, bandeiras=BANDEIRAS, tipo_label=TIPO_LABEL)


@bp.route('/cartao/taxas/salvar', methods=['POST'])
def salvar_taxas():
    data = request.json
    try:
        for item in data:
            taxa = TaxaCartao.query.get(item['id'])
            if taxa:
                taxa.taxa_percentual = float(item['taxa_percentual'])
                taxa.dias_repasse = int(item['dias_repasse'])
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500


@bp.route('/cartao/taxas/nova', methods=['POST'])
def nova_taxa():
    data = request.json
    try:
        existe = TaxaCartao.query.filter_by(bandeira=data['bandeira'], tipo=data['tipo']).first()
        if existe:
            existe.taxa_percentual = float(data['taxa_percentual'])
            existe.dias_repasse = int(data.get('dias_repasse', 30))
            existe.ativo = True
        else:
            db.session.add(TaxaCartao(
                bandeira=data['bandeira'],
                tipo=data['tipo'],
                taxa_percentual=float(data['taxa_percentual']),
                dias_repasse=int(data.get('dias_repasse', 30)),
            ))
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500


@bp.route('/api/taxas-cartao')
def api_taxas():
    """Retorna taxas para uso no frontend (cálculo de simulação)."""
    garantir_taxas_padrao()
    taxas = TaxaCartao.query.filter_by(ativo=True).all()
    return jsonify([t.to_dict() for t in taxas])
