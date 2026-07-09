from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from models import db, LancamentoBancario, ContaPagar, Conciliacao, ContaReceber, ContaBancaria, ParcelaCartao, PagamentoCartao, Agendamento, normalizar_nome
from sqlalchemy import func, extract
from datetime import datetime, date
import pandas as pd
import io

bp = Blueprint('financeiro', __name__)


def resolver_conta(nome_ou_id):
    """Retorna (conta_id, nome) a partir de um nome de conta ou id."""
    if not nome_ou_id:
        return None, 'Principal'
    try:
        cid = int(nome_ou_id)
        c = ContaBancaria.query.get(cid)
        return (c.id, c.nome) if c else (None, str(nome_ou_id))
    except (ValueError, TypeError):
        c = ContaBancaria.query.filter_by(nome=nome_ou_id).first()
        return (c.id, c.nome) if c else (None, str(nome_ou_id))


def listar_medicos():
    """Lista de profissionais conhecidos (de agendamentos e lançamentos)."""
    nomes = set()
    for (m,) in db.session.query(Agendamento.medico).distinct():
        if m and m.strip():
            nomes.add(m.strip())
    for (m,) in db.session.query(LancamentoBancario.medico).distinct():
        if m and m.strip():
            nomes.add(m.strip())
    return sorted(nomes, key=lambda s: s.lower())


def detectar_medico(descricao, nomes):
    """Tenta identificar um profissional dentro da descrição do lançamento."""
    if not descricao:
        return ''
    desc = descricao.lower()
    for nome in nomes:
        if nome.lower() in desc:
            return nome
    return ''


# ── EXTRATOS ─────────────────────────────────────────────────────────────────

@bp.route('/extratos')
def extratos():
    page = request.args.get('page', 1, type=int)
    conta_id_str = request.args.get('conta_id', '')

    # Se nenhuma conta selecionada, redireciona para a primeira ativa
    if not conta_id_str:
        primeira = ContaBancaria.query.filter_by(ativa=True).order_by(ContaBancaria.id).first()
        if primeira:
            from flask import redirect, url_for, request as req
            args = req.args.copy()
            args['conta_id'] = str(primeira.id)
            return redirect(url_for('financeiro.extratos', **args))
    data_ini = request.args.get('data_ini', '')
    data_fim = request.args.get('data_fim', '')
    tipo = request.args.get('tipo', '')
    medico = request.args.get('medico', '')

    contas_cadastradas = ContaBancaria.query.filter_by(ativa=True).order_by(ContaBancaria.nome).all()
    conta_selecionada = None

    q = LancamentoBancario.query
    if conta_id_str:
        cid = int(conta_id_str)
        q = q.filter(LancamentoBancario.conta_id == cid)
        conta_selecionada = ContaBancaria.query.get(cid)
    if data_ini:
        q = q.filter(LancamentoBancario.data >= datetime.strptime(data_ini, '%Y-%m-%d').date())
    if data_fim:
        q = q.filter(LancamentoBancario.data <= datetime.strptime(data_fim, '%Y-%m-%d').date())
    if tipo:
        q = q.filter(LancamentoBancario.tipo == tipo)
    if medico:
        q = q.filter(LancamentoBancario.medico.ilike(f'%{medico}%'))

    lancamentos = q.order_by(LancamentoBancario.data.desc()).paginate(page=page, per_page=50)

    # Totais do filtro atual
    base_q = LancamentoBancario.query
    if conta_id_str:
        base_q = base_q.filter(LancamentoBancario.conta_id == int(conta_id_str))
    if data_ini:
        base_q = base_q.filter(LancamentoBancario.data >= datetime.strptime(data_ini, '%Y-%m-%d').date())
    if data_fim:
        base_q = base_q.filter(LancamentoBancario.data <= datetime.strptime(data_fim, '%Y-%m-%d').date())

    total_receitas = db.session.query(func.sum(LancamentoBancario.valor)).filter(
        LancamentoBancario.tipo == 'credito',
        *([LancamentoBancario.conta_id == int(conta_id_str)] if conta_id_str else [])
    ).scalar() or 0
    total_despesas = db.session.query(func.sum(LancamentoBancario.valor)).filter(
        LancamentoBancario.tipo == 'debito',
        *([LancamentoBancario.conta_id == int(conta_id_str)] if conta_id_str else [])
    ).scalar() or 0

    medicos_lista = listar_medicos()

    return render_template('extratos.html',
        lancamentos=lancamentos,
        contas_cadastradas=contas_cadastradas,
        conta_selecionada=conta_selecionada,
        total_receitas=total_receitas,
        total_despesas=abs(total_despesas),
        saldo_filtro=total_receitas + total_despesas,
        medicos_lista=medicos_lista,
        filtros={
            'conta_id': conta_id_str, 'data_ini': data_ini,
            'data_fim': data_fim, 'tipo': tipo, 'medico': medico,
        },
    )


@bp.route('/extratos/importar-ofx', methods=['POST'])
def importar_ofx():
    arquivo = request.files.get('arquivo')
    conta_id_str = request.form.get('conta_id', '')
    conta_nome = request.form.get('conta_nome', 'Principal')
    cid, cnome = resolver_conta(conta_id_str or conta_nome)
    if not arquivo:
        return jsonify({'erro': 'Nenhum arquivo enviado'}), 400
    try:
        from ofxparse import OfxParser
        ofx = OfxParser.parse(arquivo)
        nomes_medicos = listar_medicos()
        inseridos = 0
        duplicados = 0
        for transacao in ofx.account.statement.transactions:
            id_ofx = transacao.id
            existe = LancamentoBancario.query.filter_by(id_ofx=id_ofx).first()
            if existe:
                duplicados += 1
                continue
            valor = float(transacao.amount)
            descricao = transacao.memo or transacao.payee or ''
            lanc = LancamentoBancario(
                conta_id=cid,
                conta=cnome,
                data=transacao.date.date() if hasattr(transacao.date, 'date') else transacao.date,
                descricao=descricao,
                valor=valor,
                tipo='credito' if valor >= 0 else 'debito',
                medico=detectar_medico(descricao, nomes_medicos),
                id_ofx=id_ofx,
                origem='ofx',
            )
            db.session.add(lanc)
            inseridos += 1
        db.session.commit()
        return jsonify({'ok': True, 'inseridos': inseridos, 'duplicados': duplicados})
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500


@bp.route('/extratos/importar-csv', methods=['POST'])
def importar_csv():
    arquivo = request.files.get('arquivo')
    conta_id_str = request.form.get('conta_id', '')
    conta_nome = request.form.get('conta_nome', 'Principal')
    cid, cnome = resolver_conta(conta_id_str or conta_nome)
    if not arquivo:
        return jsonify({'erro': 'Nenhum arquivo enviado'}), 400
    try:
        nome = arquivo.filename.lower()
        if nome.endswith('.csv'):
            df = pd.read_csv(arquivo, encoding='utf-8-sig', sep=None, engine='python')
        elif nome.endswith('.xlsx'):
            df = pd.read_excel(arquivo, engine='openpyxl')
        elif nome.endswith('.xls'):
            df = pd.read_excel(arquivo, engine='xlrd')
        else:
            return jsonify({'erro': 'Formato não suportado. Use CSV, XLS ou XLSX.'}), 400

        df.columns = [c.strip().lower() for c in df.columns]
        nomes_medicos = listar_medicos()
        inseridos = 0

        for _, row in df.iterrows():
            try:
                data_col = next((c for c in ['data', 'date', 'dt_lancamento', 'data_lancamento'] if c in df.columns), None)
                desc_col = next((c for c in ['descricao', 'descrição', 'historico', 'histórico', 'memo', 'description'] if c in df.columns), None)
                valor_col = next((c for c in ['valor', 'value', 'amount', 'vlr'] if c in df.columns), None)

                if not data_col or not desc_col or not valor_col:
                    continue

                data_val = row[data_col]
                if pd.isna(data_val):
                    continue

                if isinstance(data_val, str):
                    for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y']:
                        try:
                            data_obj = datetime.strptime(data_val.strip(), fmt).date()
                            break
                        except:
                            continue
                    else:
                        continue
                else:
                    data_obj = pd.Timestamp(data_val).date()

                valor_raw = str(row[valor_col]).replace('R$', '').replace('.', '').replace(',', '.').strip()
                valor = float(valor_raw)

                descricao = str(row[desc_col]).strip()
                lanc = LancamentoBancario(
                    conta_id=cid,
                    conta=cnome,
                    data=data_obj,
                    descricao=descricao,
                    valor=valor,
                    tipo='credito' if valor >= 0 else 'debito',
                    medico=detectar_medico(descricao, nomes_medicos),
                    origem='csv',
                )
                db.session.add(lanc)
                inseridos += 1
            except:
                continue

        db.session.commit()
        return jsonify({'ok': True, 'inseridos': inseridos})
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500


@bp.route('/extratos/novo', methods=['POST'])
def novo_lancamento():
    data = request.json
    try:
        cid, cnome = resolver_conta(data.get('conta_id') or data.get('conta', ''))
        lanc = LancamentoBancario(
            conta_id=cid,
            conta=cnome,
            data=datetime.strptime(data['data'], '%Y-%m-%d').date(),
            descricao=data['descricao'],
            valor=float(data['valor']),
            tipo=data.get('tipo', 'debito'),
            categoria=data.get('categoria', ''),
            medico=normalizar_nome(data.get('medico', '')),
            origem='manual',
        )
        db.session.add(lanc)
        db.session.commit()
        return jsonify({'ok': True, 'id': lanc.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500


@bp.route('/extratos/<int:id>', methods=['DELETE'])
def excluir_lancamento(id):
    lanc = LancamentoBancario.query.get_or_404(id)
    db.session.delete(lanc)
    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/extratos/<int:id>/medico', methods=['POST'])
def atualizar_medico_lancamento(id):
    """Atribui/altera o profissional de um lançamento (ex.: itens importados do banco)."""
    lanc = LancamentoBancario.query.get_or_404(id)
    lanc.medico = normalizar_nome(request.json.get('medico') or '')
    db.session.commit()
    return jsonify({'ok': True, 'medico': lanc.medico})


@bp.route('/extratos/detectar-medicos', methods=['POST'])
def detectar_medicos_lancamentos():
    """Aplica a detecção automática de profissional nos lançamentos ainda sem médico."""
    nomes = listar_medicos()
    if not nomes:
        return jsonify({'ok': True, 'atualizados': 0})

    sem_medico = LancamentoBancario.query.filter(
        db.or_(LancamentoBancario.medico.is_(None), LancamentoBancario.medico == '')
    ).all()

    atualizados = 0
    for lanc in sem_medico:
        encontrado = detectar_medico(lanc.descricao, nomes)
        if encontrado:
            lanc.medico = encontrado
            atualizados += 1

    if atualizados:
        db.session.commit()
    return jsonify({'ok': True, 'atualizados': atualizados, 'analisados': len(sem_medico)})


# ── CONTAS A PAGAR ────────────────────────────────────────────────────────────

@bp.route('/contas-pagar')
def contas_pagar():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '')
    categoria = request.args.get('categoria', '')
    data_ini = request.args.get('data_ini', '')
    data_fim = request.args.get('data_fim', '')

    q = ContaPagar.query

    # Atualizar status vencido automaticamente
    hoje = date.today()
    vencidas = ContaPagar.query.filter(
        ContaPagar.data_vencimento < hoje,
        ContaPagar.status == 'pendente'
    ).all()
    for c in vencidas:
        c.status = 'vencido'
    if vencidas:
        db.session.commit()

    if status:
        q = q.filter(ContaPagar.status == status)
    if categoria:
        q = q.filter(ContaPagar.categoria == categoria)
    if data_ini:
        q = q.filter(ContaPagar.data_vencimento >= datetime.strptime(data_ini, '%Y-%m-%d').date())
    if data_fim:
        q = q.filter(ContaPagar.data_vencimento <= datetime.strptime(data_fim, '%Y-%m-%d').date())

    contas = q.order_by(ContaPagar.data_vencimento).paginate(page=page, per_page=50)
    categorias = db.session.query(ContaPagar.categoria).distinct().all()

    total_pendente = db.session.query(db.func.sum(ContaPagar.valor)).filter(
        ContaPagar.status.in_(['pendente', 'vencido'])
    ).scalar() or 0

    total_vencido = db.session.query(db.func.sum(ContaPagar.valor)).filter(
        ContaPagar.status == 'vencido'
    ).scalar() or 0

    return render_template('contas_pagar.html',
        contas=contas,
        categorias=[c[0] for c in categorias if c[0]],
        total_pendente=total_pendente,
        total_vencido=total_vencido,
        filtros={'status': status, 'categoria': categoria, 'data_ini': data_ini, 'data_fim': data_fim},
    )


@bp.route('/contas-pagar/nova', methods=['POST'])
def nova_conta():
    data = request.json
    try:
        cid = int(data['conta_bancaria_id']) if data.get('conta_bancaria_id') else None
        conta = ContaPagar(
            descricao=data['descricao'],
            fornecedor=data.get('fornecedor', ''),
            categoria=data.get('categoria', ''),
            valor=float(data['valor']),
            data_vencimento=datetime.strptime(data['data_vencimento'], '%Y-%m-%d').date(),
            status='pendente',
            forma_pagamento=data.get('forma_pagamento') or None,
            conta_bancaria_id=cid,
            recorrente=data.get('recorrente', False),
            periodicidade=data.get('periodicidade', ''),
            observacao=data.get('observacao', ''),
        )
        db.session.add(conta)
        db.session.commit()
        return jsonify({'ok': True, 'id': conta.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500


@bp.route('/contas-pagar/<int:id>/pagar', methods=['POST'])
def pagar_conta(id):
    conta = ContaPagar.query.get_or_404(id)
    data = request.json or {}
    data_pgto = data.get('data_pagamento', date.today().isoformat())
    cid = int(data['conta_bancaria_id']) if data.get('conta_bancaria_id') else conta.conta_bancaria_id
    forma = data.get('forma_pagamento') or conta.forma_pagamento

    if not cid:
        return jsonify({'erro': 'Selecione a conta bancária para registrar o pagamento'}), 400

    conta.data_pagamento = datetime.strptime(data_pgto, '%Y-%m-%d').date()
    conta.status = 'pago'
    conta.forma_pagamento = forma
    conta.conta_bancaria_id = cid

    cb = ContaBancaria.query.get(cid)
    lanc = LancamentoBancario(
        data=conta.data_pagamento,
        descricao=f"Pgto: {conta.descricao}",
        valor=-abs(conta.valor),
        tipo='debito',
        categoria=conta.categoria or 'Despesa',
        conta_id=cid,
        conta=cb.nome if cb else '',
        forma_pagamento=forma,
    )
    db.session.add(lanc)
    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/contas-pagar/<int:id>', methods=['DELETE'])
def excluir_conta(id):
    conta = ContaPagar.query.get_or_404(id)
    db.session.delete(conta)
    db.session.commit()
    return jsonify({'ok': True})


# ── CONCILIAÇÃO ───────────────────────────────────────────────────────────────

@bp.route('/conciliacao')
def conciliacao():
    lancamentos_nao_conciliados = LancamentoBancario.query.filter_by(conciliado=False).order_by(
        LancamentoBancario.data.desc()
    ).all()
    conciliacoes = Conciliacao.query.order_by(Conciliacao.criado_em.desc()).limit(50).all()
    contas = db.session.query(LancamentoBancario.conta).distinct().all()

    return render_template('conciliacao.html',
        lancamentos=lancamentos_nao_conciliados,
        conciliacoes=conciliacoes,
        contas=[c[0] for c in contas],
    )


@bp.route('/conciliacao/conciliar', methods=['POST'])
def conciliar():
    data = request.json
    ids = data.get('ids', [])
    descricao = data.get('descricao', 'Conciliação manual')

    lancamentos = LancamentoBancario.query.filter(LancamentoBancario.id.in_(ids)).all()
    if not lancamentos:
        return jsonify({'erro': 'Nenhum lançamento selecionado'}), 400

    total = sum(l.valor for l in lancamentos)
    conc = Conciliacao(
        descricao=descricao,
        data=date.today(),
        valor_banco=total,
        valor_sistema=total,
        diferenca=0,
        status='conciliado',
    )
    db.session.add(conc)
    db.session.flush()

    for l in lancamentos:
        l.conciliado = True
        l.id_conciliacao = conc.id

    db.session.commit()
    return jsonify({'ok': True, 'conciliacao_id': conc.id})


# ── CONTAS A RECEBER ──────────────────────────────────────────────────────────

@bp.route('/contas-receber')
def contas_receber():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '')
    convenio = request.args.get('convenio', '')
    medico = request.args.get('medico', '')
    data_ini = request.args.get('data_ini', '')
    data_fim = request.args.get('data_fim', '')

    hoje = date.today()

    q = ContaReceber.query
    if status:
        q = q.filter(ContaReceber.status == status)
    if convenio:
        q = q.filter(ContaReceber.convenio == convenio)
    if medico:
        q = q.filter(ContaReceber.medico.ilike(f'%{medico}%'))
    if data_ini:
        q = q.filter(ContaReceber.data_prevista >= datetime.strptime(data_ini, '%Y-%m-%d').date())
    if data_fim:
        q = q.filter(ContaReceber.data_prevista <= datetime.strptime(data_fim, '%Y-%m-%d').date())

    contas = q.order_by(ContaReceber.data_prevista.desc()).paginate(page=page, per_page=50)

    total_pendente = db.session.query(db.func.sum(ContaReceber.valor)).filter(
        ContaReceber.status == 'pendente'
    ).scalar() or 0

    total_recebido_mes = db.session.query(db.func.sum(ContaReceber.valor)).filter(
        ContaReceber.status == 'recebido',
        db.extract('month', ContaReceber.data_recebimento) == hoje.month,
        db.extract('year', ContaReceber.data_recebimento) == hoje.year,
    ).scalar() or 0

    total_cancelado_mes = db.session.query(db.func.sum(ContaReceber.valor)).filter(
        ContaReceber.status == 'cancelado',
        db.extract('month', ContaReceber.data_prevista) == hoje.month,
        db.extract('year', ContaReceber.data_prevista) == hoje.year,
    ).scalar() or 0

    convenios = db.session.query(ContaReceber.convenio).distinct().all()
    medicos = db.session.query(ContaReceber.medico).distinct().all()

    # Parcelas de cartão vinculadas a agendamentos
    qp = db.session.query(ParcelaCartao).join(PagamentoCartao)
    if status:
        status_map = {'pendente': 'pendente', 'recebido': 'recebido', 'cancelado': 'cancelado'}
        qp = qp.filter(ParcelaCartao.status == status_map.get(status, status))
    if data_ini:
        qp = qp.filter(ParcelaCartao.data_prevista >= datetime.strptime(data_ini, '%Y-%m-%d').date())
    if data_fim:
        qp = qp.filter(ParcelaCartao.data_prevista <= datetime.strptime(data_fim, '%Y-%m-%d').date())
    parcelas_cartao = qp.filter(PagamentoCartao.agendamento_id != None).order_by(ParcelaCartao.data_prevista).all()

    total_parcelas_pendente = sum(p.valor_liquido_parcela for p in parcelas_cartao if p.status == 'pendente')

    return render_template('contas_receber.html',
        contas=contas,
        total_pendente=total_pendente + total_parcelas_pendente,
        total_recebido_mes=total_recebido_mes,
        total_cancelado_mes=total_cancelado_mes,
        convenios=[c[0] for c in convenios if c[0]],
        medicos=[m[0] for m in medicos if m[0]],
        parcelas_cartao=parcelas_cartao,
        filtros={
            'status': status, 'convenio': convenio, 'medico': medico,
            'data_ini': data_ini, 'data_fim': data_fim,
        },
    )


@bp.route('/contas-receber/<int:id>/receber', methods=['POST'])
def baixar_conta_receber(id):
    cr = ContaReceber.query.get_or_404(id)
    if cr.status != 'pendente':
        return jsonify({'erro': 'Conta já processada'}), 400

    data = request.json
    data_rec = datetime.strptime(data.get('data_recebimento', date.today().isoformat()), '%Y-%m-%d').date()
    forma = data.get('forma_pagamento', 'dinheiro')
    cid, cnome = resolver_conta(data.get('conta_id'))
    if not cid:
        return jsonify({'erro': 'Selecione a conta bancária'}), 400

    cr.status = 'recebido'
    cr.data_recebimento = data_rec
    cr.forma_pagamento = forma

    # Gera lançamento no extrato sempre
    forma_label = {'dinheiro':'Dinheiro','pix':'Pix','cartao':'Cartão','convenio':'Convênio','cheque':'Cheque'}.get(forma, forma)
    desc = f"Recebimento {forma_label} – {cr.paciente} – {cr.descricao or 'Consulta'}"
    lanc = LancamentoBancario(
        conta_id=cid,
        conta=cnome,
        data=data_rec,
        descricao=desc,
        valor=float(data.get('valor', cr.valor)),
        tipo='credito',
        categoria='Receita consulta',
        medico=normalizar_nome(cr.medico or ''),
        origem='manual',
    )
    db.session.add(lanc)
    db.session.flush()
    cr.lancamento_id = lanc.id

    # Sincroniza status do agendamento
    if cr.agendamento and cr.agendamento.status not in ('realizado', 'falta', 'cancelado'):
        cr.agendamento.status = 'realizado'

    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/contas-receber/<int:id>/cancelar', methods=['POST'])
def cancelar_conta_receber(id):
    cr = ContaReceber.query.get_or_404(id)
    cr.status = 'cancelado'
    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/contas-receber/<int:id>/atualizar-valor', methods=['POST'])
def atualizar_valor_cr(id):
    cr = ContaReceber.query.get_or_404(id)
    novo_valor = request.json.get('valor')
    if novo_valor is None:
        return jsonify({'erro': 'Valor não informado'}), 400
    cr.valor = float(novo_valor)
    db.session.commit()
    return jsonify({'ok': True})


# ── CONTAS BANCÁRIAS ──────────────────────────────────────────────────────────

@bp.route('/contas-bancarias')
def contas_bancarias():
    contas = ContaBancaria.query.order_by(ContaBancaria.nome).all()
    return render_template('contas_bancarias.html', contas=contas)


@bp.route('/contas-bancarias/salvar', methods=['POST'])
def salvar_conta_bancaria():
    data = request.json
    try:
        cid = data.get('id')
        if cid:
            cb = ContaBancaria.query.get_or_404(int(cid))
        else:
            cb = ContaBancaria()
            db.session.add(cb)
        cb.nome = data['nome']
        cb.banco = data.get('banco', '')
        cb.agencia = data.get('agencia', '')
        cb.numero = data.get('numero', '')
        cb.tipo = data.get('tipo', 'corrente')
        cb.ativa = data.get('ativa', True)
        if not cid:
            cb.saldo_inicial = float(data.get('saldo_inicial', 0))
        db.session.commit()
        return jsonify({'ok': True, 'id': cb.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'erro': str(e)}), 500


@bp.route('/contas-bancarias/<int:id>/saldo-inicial', methods=['POST'])
def ajustar_saldo_inicial(id):
    cb = ContaBancaria.query.get_or_404(id)
    cb.saldo_inicial = float(request.json.get('saldo_inicial', 0))
    db.session.commit()
    return jsonify({'ok': True, 'saldo_atual': cb.saldo_atual})


@bp.route('/api/contas-bancarias')
def api_contas_bancarias():
    todas = request.args.get('todas', '0') == '1'
    q = ContaBancaria.query
    if not todas:
        q = q.filter_by(ativa=True)
    contas = q.order_by(ContaBancaria.nome).all()
    return jsonify([c.to_dict() for c in contas])


@bp.route('/api/lancamentos-medico')
def api_lancamentos_medico():
    medico = request.args.get('medico', '')
    mes = request.args.get('mes', type=int)
    ano = request.args.get('ano', type=int)
    conta_id_str = request.args.get('conta_id', '')

    q = LancamentoBancario.query.filter(
        LancamentoBancario.medico == medico,
    )
    if mes and ano:
        q = q.filter(
            extract('month', LancamentoBancario.data) == mes,
            extract('year', LancamentoBancario.data) == ano,
        )
    if conta_id_str:
        q = q.filter(LancamentoBancario.conta_id == int(conta_id_str))

    lancamentos = q.order_by(LancamentoBancario.data.desc()).all()
    return jsonify([{
        'data': l.data.strftime('%d/%m/%Y'),
        'descricao': l.descricao,
        'tipo': l.tipo,
        'valor': l.valor,
        'conta': l.conta,
        'categoria': l.categoria or '',
    } for l in lancamentos])


# ── EXTRATO POR MÉDICO ────────────────────────────────────────────────────────

@bp.route('/extrato-medicos')
def extrato_medicos():
    mes = request.args.get('mes', date.today().month, type=int)
    ano = request.args.get('ano', date.today().year, type=int)
    conta_id_str = request.args.get('conta_id', '')

    base = LancamentoBancario.query.filter(
        extract('month', LancamentoBancario.data) == mes,
        extract('year', LancamentoBancario.data) == ano,
    )
    if conta_id_str:
        base = base.filter(LancamentoBancario.conta_id == int(conta_id_str))

    # Receitas por médico
    receitas_med = db.session.query(
        LancamentoBancario.medico,
        func.sum(LancamentoBancario.valor).label('total'),
        func.count(LancamentoBancario.id).label('qtd'),
    ).filter(
        LancamentoBancario.tipo == 'credito',
        LancamentoBancario.medico.isnot(None),
        LancamentoBancario.medico != '',
        extract('month', LancamentoBancario.data) == mes,
        extract('year', LancamentoBancario.data) == ano,
        *([LancamentoBancario.conta_id == int(conta_id_str)] if conta_id_str else []),
    ).group_by(LancamentoBancario.medico).all()

    # Despesas por médico (lançamentos manuais com médico preenchido)
    despesas_med = db.session.query(
        LancamentoBancario.medico,
        func.sum(LancamentoBancario.valor).label('total'),
        func.count(LancamentoBancario.id).label('qtd'),
    ).filter(
        LancamentoBancario.tipo == 'debito',
        LancamentoBancario.medico.isnot(None),
        LancamentoBancario.medico != '',
        extract('month', LancamentoBancario.data) == mes,
        extract('year', LancamentoBancario.data) == ano,
        *([LancamentoBancario.conta_id == int(conta_id_str)] if conta_id_str else []),
    ).group_by(LancamentoBancario.medico).all()

    # Totais gerais do período
    total_receitas = base.filter(LancamentoBancario.tipo == 'credito')\
        .with_entities(func.sum(LancamentoBancario.valor)).scalar() or 0
    total_despesas = base.filter(LancamentoBancario.tipo == 'debito')\
        .with_entities(func.sum(LancamentoBancario.valor)).scalar() or 0

    # Monta dicionário consolidado por médico
    medicos_dict = {}
    for r in receitas_med:
        medicos_dict.setdefault(r.medico, {'medico': r.medico, 'receitas': 0, 'despesas': 0, 'qtd_receitas': 0, 'qtd_despesas': 0})
        medicos_dict[r.medico]['receitas'] = round(float(r.total), 2)
        medicos_dict[r.medico]['qtd_receitas'] = r.qtd
    for d in despesas_med:
        medicos_dict.setdefault(d.medico, {'medico': d.medico, 'receitas': 0, 'despesas': 0, 'qtd_receitas': 0, 'qtd_despesas': 0})
        medicos_dict[d.medico]['despesas'] = round(abs(float(d.total)), 2)
        medicos_dict[d.medico]['qtd_despesas'] = d.qtd

    medicos_lista = sorted(medicos_dict.values(), key=lambda x: x['receitas'], reverse=True)
    for m in medicos_lista:
        m['liquido'] = round(m['receitas'] - m['despesas'], 2)

    contas_cadastradas = ContaBancaria.query.filter_by(ativa=True).order_by(ContaBancaria.nome).all()

    # Passa hoje para o template
    from datetime import date as _date
    hoje_obj = _date.today()

    return render_template('extrato_medicos.html',
        hoje=hoje_obj,
        medicos=medicos_lista,
        total_receitas=total_receitas,
        total_despesas=abs(total_despesas),
        mes=mes, ano=ano,
        contas_cadastradas=contas_cadastradas,
        conta_id_str=conta_id_str,
        filtros={'mes': mes, 'ano': ano, 'conta_id': conta_id_str},
    )
