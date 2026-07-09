from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import re

db = SQLAlchemy()


def normalizar_nome(nome):
    """Padroniza nome de profissional: remove espaços duplicados e sobras.
    Ex.: 'HARUKI  MATSUNAGA ' -> 'HARUKI MATSUNAGA'. Mantém None/'' como estão."""
    if not nome:
        return nome
    return re.sub(r'\s+', ' ', str(nome)).strip()


class ContaBancaria(db.Model):
    __tablename__ = 'contas_bancarias'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    banco = db.Column(db.String(100))
    agencia = db.Column(db.String(20))
    numero = db.Column(db.String(30))
    tipo = db.Column(db.String(30), default='corrente')   # corrente, poupanca, investimento, caixa
    ativa = db.Column(db.Boolean, default=True)
    saldo_inicial = db.Column(db.Float, default=0.0)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    lancamentos = db.relationship('LancamentoBancario', backref='conta_obj',
                                   foreign_keys='LancamentoBancario.conta_id', lazy='dynamic')

    @property
    def saldo_atual(self):
        from sqlalchemy import func
        soma = db.session.query(func.sum(LancamentoBancario.valor)).filter(
            LancamentoBancario.conta_id == self.id
        ).scalar() or 0
        return round(self.saldo_inicial + soma, 2)

    def to_dict(self):
        return {
            'id': self.id,
            'nome': self.nome,
            'banco': self.banco,
            'agencia': self.agencia,
            'numero': self.numero,
            'tipo': self.tipo,
            'ativa': self.ativa,
            'saldo_inicial': self.saldo_inicial,
            'saldo_atual': self.saldo_atual,
        }


CONTAS_PADRAO = [
    ('Caixa Clínica',      'Interno',       '',      '',        'caixa'),
    ('Banco Principal',    'Bradesco',      '0001',  '12345-6', 'corrente'),
    ('Conta Convênios',    'Itaú',          '0234',  '78901-2', 'corrente'),
    ('Conta Particular',   'Santander',     '0456',  '34567-8', 'corrente'),
    ('Conta Poupança',     'Caixa Econômica','0013', '98765-4', 'poupanca'),
    ('Conta Investimento', 'XP Investimentos','',   '',         'investimento'),
    ('Conta Reserva',      'Nubank',        '',      '',        'corrente'),
]


def seed_contas_bancarias():
    """Popula as 7 contas padrão se a tabela estiver vazia."""
    if ContaBancaria.query.count() == 0:
        for nome, banco, agencia, numero, tipo in CONTAS_PADRAO:
            db.session.add(ContaBancaria(
                nome=nome, banco=banco, agencia=agencia, numero=numero, tipo=tipo
            ))
        db.session.commit()


class Agendamento(db.Model):
    __tablename__ = 'agendamentos'
    id = db.Column(db.Integer, primary_key=True)
    id_externo = db.Column(db.String(100), unique=True, nullable=True)  # ID do Versatilis
    paciente = db.Column(db.String(200), nullable=False)
    medico = db.Column(db.String(200))
    especialidade = db.Column(db.String(100))
    data_hora = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(50), default='agendado')  # agendado, confirmado, realizado, falta, cancelado
    convenio = db.Column(db.String(100))
    tipo_consulta = db.Column(db.String(100))
    valor = db.Column(db.Float, default=0.0)
    forma_pagamento = db.Column(db.String(50))
    cartao_tipo = db.Column(db.String(20))       # debito, credito
    cartao_bandeira = db.Column(db.String(50))
    cartao_parcelas = db.Column(db.Integer, default=1)
    conta_bancaria_id = db.Column(db.Integer, db.ForeignKey('contas_bancarias.id'), nullable=True)
    observacao = db.Column(db.Text)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'id_externo': self.id_externo,
            'paciente': self.paciente,
            'medico': self.medico,
            'especialidade': self.especialidade,
            'data_hora': self.data_hora.strftime('%Y-%m-%d %H:%M') if self.data_hora else '',
            'status': self.status,
            'convenio': self.convenio,
            'tipo_consulta': self.tipo_consulta,
            'valor': self.valor,
            'observacao': self.observacao,
        }


class LancamentoBancario(db.Model):
    __tablename__ = 'lancamentos_bancarios'
    id = db.Column(db.Integer, primary_key=True)
    conta_id = db.Column(db.Integer, db.ForeignKey('contas_bancarias.id'), nullable=True)
    conta = db.Column(db.String(100), nullable=False)   # mantido para compatibilidade / OFX
    data = db.Column(db.Date, nullable=False)
    descricao = db.Column(db.String(300), nullable=False)
    valor = db.Column(db.Float, nullable=False)         # positivo = crédito, negativo = débito
    tipo = db.Column(db.String(20), default='debito')   # credito / debito
    categoria = db.Column(db.String(100))
    medico = db.Column(db.String(200))                  # médico vinculado (preenchido nas receitas)
    conciliado = db.Column(db.Boolean, default=False)
    id_conciliacao = db.Column(db.Integer, db.ForeignKey('conciliacoes.id'), nullable=True)
    id_ofx = db.Column(db.String(200))
    origem = db.Column(db.String(50), default='manual') # manual / ofx / csv / cartao
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'conta_id': self.conta_id,
            'conta': self.conta,
            'data': self.data.strftime('%Y-%m-%d') if self.data else '',
            'descricao': self.descricao,
            'valor': self.valor,
            'tipo': self.tipo,
            'categoria': self.categoria,
            'medico': self.medico,
            'conciliado': self.conciliado,
            'origem': self.origem,
        }


class ContaPagar(db.Model):
    __tablename__ = 'contas_pagar'
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(300), nullable=False)
    fornecedor = db.Column(db.String(200))
    categoria = db.Column(db.String(100))
    valor = db.Column(db.Float, nullable=False)
    data_vencimento = db.Column(db.Date, nullable=False)
    data_pagamento = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='pendente')  # pendente, pago, vencido, cancelado
    forma_pagamento = db.Column(db.String(50))
    conta_bancaria_id = db.Column(db.Integer, db.ForeignKey('contas_bancarias.id'), nullable=True)
    recorrente = db.Column(db.Boolean, default=False)
    periodicidade = db.Column(db.String(20))  # mensal, semanal, anual
    observacao = db.Column(db.Text)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'descricao': self.descricao,
            'fornecedor': self.fornecedor,
            'categoria': self.categoria,
            'valor': self.valor,
            'data_vencimento': self.data_vencimento.strftime('%Y-%m-%d') if self.data_vencimento else '',
            'data_pagamento': self.data_pagamento.strftime('%Y-%m-%d') if self.data_pagamento else '',
            'status': self.status,
            'recorrente': self.recorrente,
            'periodicidade': self.periodicidade,
        }


class Conciliacao(db.Model):
    __tablename__ = 'conciliacoes'
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200))
    data = db.Column(db.Date)
    valor_sistema = db.Column(db.Float)
    valor_banco = db.Column(db.Float)
    diferenca = db.Column(db.Float)
    status = db.Column(db.String(20), default='pendente')  # pendente, conciliado, divergente
    lancamentos = db.relationship('LancamentoBancario', backref='conciliacao', lazy=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)


class ContaReceber(db.Model):
    """Gerada automaticamente quando agendamento fica agendado/confirmado."""
    __tablename__ = 'contas_receber'
    id = db.Column(db.Integer, primary_key=True)
    agendamento_id = db.Column(db.Integer, db.ForeignKey('agendamentos.id'), nullable=False, unique=True)
    paciente = db.Column(db.String(200), nullable=False)
    medico = db.Column(db.String(200))
    descricao = db.Column(db.String(300))
    convenio = db.Column(db.String(100))
    valor = db.Column(db.Float, nullable=False)
    data_prevista = db.Column(db.Date, nullable=False)   # data da consulta
    data_recebimento = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='pendente')  # pendente, recebido, cancelado
    forma_pagamento = db.Column(db.String(50))             # dinheiro, pix, cartao, convenio
    lancamento_id = db.Column(db.Integer, db.ForeignKey('lancamentos_bancarios.id'), nullable=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agendamento = db.relationship('Agendamento', backref=db.backref('conta_receber', uselist=False))

    def to_dict(self):
        return {
            'id': self.id,
            'agendamento_id': self.agendamento_id,
            'paciente': self.paciente,
            'medico': self.medico,
            'descricao': self.descricao,
            'convenio': self.convenio,
            'valor': self.valor,
            'data_prevista': self.data_prevista.strftime('%Y-%m-%d') if self.data_prevista else '',
            'data_recebimento': self.data_recebimento.strftime('%Y-%m-%d') if self.data_recebimento else '',
            'status': self.status,
            'forma_pagamento': self.forma_pagamento,
        }


class TaxaCartao(db.Model):
    """Taxa por bandeira e quantidade de parcelas (ex: Visa 2x = 2.5%)."""
    __tablename__ = 'taxas_cartao'
    id = db.Column(db.Integer, primary_key=True)
    bandeira = db.Column(db.String(50), nullable=False)   # Visa, Master, Elo, Amex, Hipercard
    tipo = db.Column(db.String(20), nullable=False)        # debito, credito_1x, credito_2_6x, credito_7_12x
    taxa_percentual = db.Column(db.Float, nullable=False)  # ex: 2.5 = 2,5%
    dias_repasse = db.Column(db.Integer, default=30)       # dias para crédito cair na conta por parcela
    ativo = db.Column(db.Boolean, default=True)

    __table_args__ = (db.UniqueConstraint('bandeira', 'tipo', name='uq_bandeira_tipo'),)

    def to_dict(self):
        return {
            'id': self.id,
            'bandeira': self.bandeira,
            'tipo': self.tipo,
            'taxa_percentual': self.taxa_percentual,
            'dias_repasse': self.dias_repasse,
        }


class PagamentoCartao(db.Model):
    """Pagamento recebido via cartão — gera N parcelas provisionadas."""
    __tablename__ = 'pagamentos_cartao'
    id = db.Column(db.Integer, primary_key=True)
    agendamento_id = db.Column(db.Integer, db.ForeignKey('agendamentos.id'), nullable=True)
    paciente = db.Column(db.String(200), nullable=False)
    descricao = db.Column(db.String(300))
    bandeira = db.Column(db.String(50), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)        # debito / credito
    num_parcelas = db.Column(db.Integer, default=1)
    valor_bruto = db.Column(db.Float, nullable=False)      # valor cobrado do paciente
    taxa_percentual = db.Column(db.Float, nullable=False)  # taxa aplicada
    valor_taxa = db.Column(db.Float, nullable=False)       # R$ da taxa total
    valor_liquido = db.Column(db.Float, nullable=False)    # valor_bruto - valor_taxa
    data_venda = db.Column(db.Date, nullable=False)
    conta_id = db.Column(db.Integer, db.ForeignKey('contas_bancarias.id'), nullable=True)
    status = db.Column(db.String(20), default='ativo')     # ativo, cancelado
    observacao = db.Column(db.Text)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    parcelas = db.relationship('ParcelaCartao', backref='pagamento', lazy=True,
                                cascade='all, delete-orphan')
    agendamento = db.relationship('Agendamento', backref='pagamentos_cartao', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'paciente': self.paciente,
            'descricao': self.descricao,
            'bandeira': self.bandeira,
            'tipo': self.tipo,
            'num_parcelas': self.num_parcelas,
            'valor_bruto': self.valor_bruto,
            'taxa_percentual': self.taxa_percentual,
            'valor_taxa': self.valor_taxa,
            'valor_liquido': self.valor_liquido,
            'data_venda': self.data_venda.strftime('%Y-%m-%d') if self.data_venda else '',
            'status': self.status,
        }


class ParcelaCartao(db.Model):
    """Cada parcela provisionada de um pagamento em cartão."""
    __tablename__ = 'parcelas_cartao'
    id = db.Column(db.Integer, primary_key=True)
    pagamento_id = db.Column(db.Integer, db.ForeignKey('pagamentos_cartao.id'), nullable=False)
    numero = db.Column(db.Integer, nullable=False)         # 1, 2, 3...
    valor_bruto_parcela = db.Column(db.Float, nullable=False)
    taxa_parcela = db.Column(db.Float, nullable=False)     # R$ de taxa desta parcela
    valor_liquido_parcela = db.Column(db.Float, nullable=False)
    data_prevista = db.Column(db.Date, nullable=False)     # quando cai na conta
    data_recebimento = db.Column(db.Date, nullable=True)   # quando efetivamente recebeu
    status = db.Column(db.String(20), default='pendente')  # pendente, recebido, cancelado
    lancamento_id = db.Column(db.Integer, db.ForeignKey('lancamentos_bancarios.id'), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'pagamento_id': self.pagamento_id,
            'numero': self.numero,
            'valor_bruto_parcela': self.valor_bruto_parcela,
            'taxa_parcela': self.taxa_parcela,
            'valor_liquido_parcela': self.valor_liquido_parcela,
            'data_prevista': self.data_prevista.strftime('%Y-%m-%d') if self.data_prevista else '',
            'data_recebimento': self.data_recebimento.strftime('%Y-%m-%d') if self.data_recebimento else '',
            'status': self.status,
        }


class ConfiguracaoVersatilis(db.Model):
    __tablename__ = 'config_versatilis'
    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(100), unique=True, nullable=False)
    valor = db.Column(db.Text)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
