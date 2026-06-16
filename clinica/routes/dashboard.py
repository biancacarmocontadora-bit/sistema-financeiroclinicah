from flask import Blueprint, render_template, jsonify, request
from models import db, Agendamento, LancamentoBancario, ContaPagar
from datetime import datetime, date, timedelta
from sqlalchemy import func, extract

bp = Blueprint('dashboard', __name__)


@bp.route('/')
def index():
    hoje = date.today()
    mes_atual = hoje.month
    ano_atual = hoje.year

    # KPIs do mês
    total_consultas = Agendamento.query.filter(
        extract('month', Agendamento.data_hora) == mes_atual,
        extract('year', Agendamento.data_hora) == ano_atual
    ).count()

    realizadas = Agendamento.query.filter(
        extract('month', Agendamento.data_hora) == mes_atual,
        extract('year', Agendamento.data_hora) == ano_atual,
        Agendamento.status == 'realizado'
    ).count()

    faltas = Agendamento.query.filter(
        extract('month', Agendamento.data_hora) == mes_atual,
        extract('year', Agendamento.data_hora) == ano_atual,
        Agendamento.status == 'falta'
    ).count()

    canceladas = Agendamento.query.filter(
        extract('month', Agendamento.data_hora) == mes_atual,
        extract('year', Agendamento.data_hora) == ano_atual,
        Agendamento.status == 'cancelado'
    ).count()

    taxa_falta = round((faltas / total_consultas * 100) if total_consultas > 0 else 0, 1)

    receita_mes = db.session.query(func.sum(Agendamento.valor)).filter(
        extract('month', Agendamento.data_hora) == mes_atual,
        extract('year', Agendamento.data_hora) == ano_atual,
        Agendamento.status == 'realizado'
    ).scalar() or 0

    contas_vencer = ContaPagar.query.filter(
        ContaPagar.data_vencimento >= hoje,
        ContaPagar.data_vencimento <= hoje + timedelta(days=7),
        ContaPagar.status == 'pendente'
    ).count()

    contas_vencidas = ContaPagar.query.filter(
        ContaPagar.data_vencimento < hoje,
        ContaPagar.status == 'pendente'
    ).count()

    # Agendamentos de hoje
    agendamentos_hoje = Agendamento.query.filter(
        func.date(Agendamento.data_hora) == hoje
    ).order_by(Agendamento.data_hora).all()

    return render_template('dashboard.html',
        total_consultas=total_consultas,
        realizadas=realizadas,
        faltas=faltas,
        canceladas=canceladas,
        taxa_falta=taxa_falta,
        receita_mes=receita_mes,
        contas_vencer=contas_vencer,
        contas_vencidas=contas_vencidas,
        agendamentos_hoje=agendamentos_hoje,
        hoje=hoje,
        mes_nome=hoje.strftime('%B/%Y'),
    )


@bp.route('/api/grafico-consultas')
def grafico_consultas():
    ano = request.args.get('ano', date.today().year, type=int)
    dados = []
    for mes in range(1, 13):
        total = Agendamento.query.filter(
            extract('month', Agendamento.data_hora) == mes,
            extract('year', Agendamento.data_hora) == ano
        ).count()
        realizadas = Agendamento.query.filter(
            extract('month', Agendamento.data_hora) == mes,
            extract('year', Agendamento.data_hora) == ano,
            Agendamento.status == 'realizado'
        ).count()
        faltas = Agendamento.query.filter(
            extract('month', Agendamento.data_hora) == mes,
            extract('year', Agendamento.data_hora) == ano,
            Agendamento.status == 'falta'
        ).count()
        dados.append({'mes': mes, 'total': total, 'realizadas': realizadas, 'faltas': faltas})
    return jsonify(dados)


@bp.route('/api/grafico-receita')
def grafico_receita():
    ano = request.args.get('ano', date.today().year, type=int)
    dados = []
    for mes in range(1, 13):
        receita = db.session.query(func.sum(Agendamento.valor)).filter(
            extract('month', Agendamento.data_hora) == mes,
            extract('year', Agendamento.data_hora) == ano,
            Agendamento.status == 'realizado'
        ).scalar() or 0
        dados.append({'mes': mes, 'receita': float(receita)})
    return jsonify(dados)


@bp.route('/api/grafico-convenios')
def grafico_convenios():
    mes = request.args.get('mes', date.today().month, type=int)
    ano = request.args.get('ano', date.today().year, type=int)
    resultados = db.session.query(
        Agendamento.convenio,
        func.count(Agendamento.id).label('total')
    ).filter(
        extract('month', Agendamento.data_hora) == mes,
        extract('year', Agendamento.data_hora) == ano
    ).group_by(Agendamento.convenio).all()
    return jsonify([{'convenio': r.convenio or 'Particular', 'total': r.total} for r in resultados])
