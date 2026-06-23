import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, date, timedelta
import calendar
import io
import os
import uuid

st.set_page_config(
    page_title="Sistema Financeiro - Grupo Empresarial",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── Banco de dados: PostgreSQL (nuvem) ou SQLite (local) ────────────────────
USE_POSTGRES = False
try:
    if "DATABASE_URL" in st.secrets:
        import psycopg2
        import psycopg2.extras
        USE_POSTGRES = True
except Exception:
    pass

if not USE_POSTGRES:
    import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "financeiro.db")

def get_conn():
    if USE_POSTGRES:
        import urllib.parse
        url = urllib.parse.urlparse(st.secrets["DATABASE_URL"])
        try:
            return psycopg2.connect(
                host=url.hostname,
                port=url.port or 5432,
                dbname=url.path.lstrip("/"),
                user=url.username,
                password=url.password,
                sslmode="require",
                connect_timeout=15,
            )
        except Exception as e:
            st.error(f"DB host={url.hostname} port={url.port} user={url.username} | {e}")
            raise
    return sqlite3.connect(DB_PATH)

def q(sql, params=()):
    conn = get_conn()
    if USE_POSTGRES:
        sql_pg = sql.replace("?", "%s")
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql_pg, params if params else None)
        cols = [d.name for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        conn.close()
        if rows:
            return pd.DataFrame([dict(r) for r in rows])
        return pd.DataFrame(columns=cols)
    else:
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        conn.close()
        return pd.DataFrame(rows, columns=cols)

def run(sql, params=()):
    conn = get_conn()
    if USE_POSTGRES:
        sql_pg = sql.replace("?", "%s")
        cur = conn.cursor()
        cur.execute(sql_pg, params if params else None)
        conn.commit()
    else:
        conn.execute(sql, params)
        conn.commit()
    conn.close()

def run_many(sql, data):
    conn = get_conn()
    if USE_POSTGRES:
        sql_pg = sql.replace("?", "%s")
        cur = conn.cursor()
        cur.executemany(sql_pg, [tuple(r) for r in data])
        conn.commit()
    else:
        conn.executemany(sql, data)
        conn.commit()
    conn.close()

def init_db():
    conn = get_conn()
    if USE_POSTGRES:
        cur = conn.cursor()
        for stmt in [
            """CREATE TABLE IF NOT EXISTS companies (
                id SERIAL PRIMARY KEY, name TEXT NOT NULL, cnpj TEXT, active INTEGER DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS banks (
                id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL, name TEXT NOT NULL,
                account_type TEXT, balance_initial REAL DEFAULT 0, active INTEGER DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS professionals (
                id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL, name TEXT NOT NULL,
                role TEXT, active INTEGER DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL, name TEXT NOT NULL,
                type TEXT NOT NULL, active INTEGER DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL, bank_id INTEGER,
                professional_id INTEGER, category_id INTEGER, type TEXT NOT NULL,
                description TEXT NOT NULL, amount REAL NOT NULL,
                date_competencia TEXT NOT NULL, date_caixa TEXT NOT NULL,
                payment_method TEXT DEFAULT 'dinheiro', status TEXT DEFAULT 'pago',
                installment_group TEXT, installment_num INTEGER, installment_total INTEGER,
                notes TEXT, created_at TIMESTAMP DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS card_fees (
                id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL, card_type TEXT NOT NULL,
                installments INTEGER NOT NULL, fee_percent REAL NOT NULL,
                days_to_receive INTEGER NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS agendamentos (
                id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL,
                paciente TEXT NOT NULL, medico TEXT, especialidade TEXT,
                data_hora TEXT NOT NULL, status TEXT DEFAULT 'agendado',
                convenio TEXT, tipo_consulta TEXT, valor REAL DEFAULT 0,
                forma_pagamento TEXT, cartao_bandeira TEXT,
                cartao_parcelas INTEGER DEFAULT 1, observacao TEXT,
                criado_em TIMESTAMP DEFAULT NOW())""",
        ]:
            cur.execute(stmt)
        # Migra colunas de cartao em bancos existentes (Postgres)
        for col, definition in [("cartao_bandeira", "TEXT"), ("cartao_parcelas", "INTEGER DEFAULT 1")]:
            try:
                cur.execute(f"ALTER TABLE agendamentos ADD COLUMN IF NOT EXISTS {col} {definition}")
            except Exception:
                pass
        # Garante que existe ao menos uma empresa
        cur.execute("SELECT COUNT(*) FROM companies")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO companies (name, cnpj, active) VALUES (%s, %s, %s)", ("Minha Clinica", "", 1))
            conn.commit()
            cur.execute("SELECT id FROM companies LIMIT 1")
            empresa_id = cur.fetchone()[0]
            cur.executemany("INSERT INTO card_fees (company_id, card_type, installments, fee_percent, days_to_receive) VALUES (%s,%s,%s,%s,%s)", [
                (empresa_id, "credito_vista", 1, 2.5, 30),
                (empresa_id, "credito_2x",   2, 3.5, 30),
                (empresa_id, "credito_3x",   3, 4.0, 30),
                (empresa_id, "credito_6x",   6, 5.5, 30),
                (empresa_id, "credito_12x", 12, 7.0, 30),
                (empresa_id, "debito",        1, 1.5,  1),
            ])
            cur.executemany("INSERT INTO categories (company_id, name, type) VALUES (%s,%s,%s)", [
                (empresa_id, "Consultas",       "receita"),
                (empresa_id, "Procedimentos",   "receita"),
                (empresa_id, "Outros Servicos", "receita"),
                (empresa_id, "Salarios",        "despesa"),
                (empresa_id, "Aluguel",         "despesa"),
                (empresa_id, "Materiais",       "despesa"),
                (empresa_id, "Impostos",        "despesa"),
                (empresa_id, "Outras Despesas", "despesa"),
            ])
        conn.commit()
        conn.close()
    else:
        cur = conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, cnpj TEXT, active INTEGER DEFAULT 1);
            CREATE TABLE IF NOT EXISTS banks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL, name TEXT NOT NULL,
                account_type TEXT, balance_initial REAL DEFAULT 0, active INTEGER DEFAULT 1,
                FOREIGN KEY(company_id) REFERENCES companies(id));
            CREATE TABLE IF NOT EXISTS professionals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL, name TEXT NOT NULL,
                role TEXT, active INTEGER DEFAULT 1,
                FOREIGN KEY(company_id) REFERENCES companies(id));
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL, name TEXT NOT NULL,
                type TEXT NOT NULL, active INTEGER DEFAULT 1,
                FOREIGN KEY(company_id) REFERENCES companies(id));
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL, bank_id INTEGER,
                professional_id INTEGER, category_id INTEGER,
                type TEXT NOT NULL, description TEXT NOT NULL,
                amount REAL NOT NULL, date_competencia TEXT NOT NULL,
                date_caixa TEXT NOT NULL, payment_method TEXT DEFAULT 'dinheiro',
                status TEXT DEFAULT 'pago', installment_group TEXT,
                installment_num INTEGER, installment_total INTEGER,
                notes TEXT, created_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY(company_id) REFERENCES companies(id),
                FOREIGN KEY(bank_id) REFERENCES banks(id),
                FOREIGN KEY(professional_id) REFERENCES professionals(id),
                FOREIGN KEY(category_id) REFERENCES categories(id));
            CREATE TABLE IF NOT EXISTS card_fees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL, card_type TEXT NOT NULL,
                installments INTEGER NOT NULL, fee_percent REAL NOT NULL,
                days_to_receive INTEGER NOT NULL,
                FOREIGN KEY(company_id) REFERENCES companies(id));
            CREATE TABLE IF NOT EXISTS agendamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                paciente TEXT NOT NULL,
                medico TEXT,
                especialidade TEXT,
                data_hora TEXT NOT NULL,
                status TEXT DEFAULT 'agendado',
                convenio TEXT,
                tipo_consulta TEXT,
                valor REAL DEFAULT 0,
                forma_pagamento TEXT,
                cartao_bandeira TEXT,
                cartao_parcelas INTEGER DEFAULT 1,
                observacao TEXT,
                criado_em TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY(company_id) REFERENCES companies(id));
        """)
        # Migra colunas de cartao em bancos existentes
        for col, definition in [("cartao_bandeira", "TEXT"), ("cartao_parcelas", "INTEGER DEFAULT 1")]:
            try:
                cur.execute(f"ALTER TABLE agendamentos ADD COLUMN {col} {definition}")
                conn.commit()
            except Exception:
                pass
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM companies")
        if cur.fetchone()[0] == 0:
            cur.executemany("INSERT INTO companies (name, cnpj) VALUES (?, ?)", [
                ("Empresa Alpha Ltda", "00.000.000/0001-01"),
                ("Empresa Beta Ltda", "00.000.000/0002-02"),
                ("Empresa Gamma Ltda", "00.000.000/0003-03"),
            ])
            conn.commit()
            cur.execute("SELECT id FROM companies")
            cids = [r[0] for r in cur.fetchall()]
            for cid in cids:
                cur.executemany("INSERT INTO banks (company_id, name, account_type, balance_initial) VALUES (?,?,?,?)", [
                    (cid, "Banco do Brasil", "Conta Corrente", 0),
                    (cid, "Caixa", "Conta Corrente", 0),
                    (cid, "Nubank", "Conta Digital", 0),
                ])
                cur.executemany("INSERT INTO categories (company_id, name, type) VALUES (?,?,?)", [
                    (cid, "Consultas", "receita"),
                    (cid, "Procedimentos", "receita"),
                    (cid, "Outros Servicos", "receita"),
                    (cid, "Salarios", "despesa"),
                    (cid, "Aluguel", "despesa"),
                    (cid, "Materiais", "despesa"),
                    (cid, "Marketing", "despesa"),
                    (cid, "Impostos", "despesa"),
                    (cid, "Outras Despesas", "despesa"),
                ])
                cur.executemany("INSERT INTO card_fees (company_id, card_type, installments, fee_percent, days_to_receive) VALUES (?,?,?,?,?)", [
                    (cid, "credito_vista", 1, 2.5, 30),
                    (cid, "credito_2x", 2, 3.5, 30),
                    (cid, "credito_3x", 3, 4.0, 30),
                    (cid, "credito_6x", 6, 5.5, 30),
                    (cid, "credito_12x", 12, 7.0, 30),
                    (cid, "debito", 1, 1.5, 1),
                ])
            conn.commit()
        conn.close()

init_db()

st.markdown("""
<style>
[data-testid="stSidebar"] { background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%); }
[data-testid="stSidebar"] * { color: #e0e0e0 !important; }
.metric-card {
    background: white; border-radius: 12px; padding: 16px 20px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08); border-left: 4px solid #667eea;
    margin-bottom: 8px;
}
.metric-receita { border-left-color: #27ae60; }
.metric-despesa { border-left-color: #e74c3c; }
.metric-saldo   { border-left-color: #3498db; }
.metric-value   { font-size: 1.6rem; font-weight: 700; margin: 4px 0; }
.metric-label   { font-size: 0.8rem; color: #666; text-transform: uppercase; letter-spacing: 1px; }
</style>
""", unsafe_allow_html=True)

def get_installments_from_method(payment_method):
    """Extrai numero de parcelas do nome do metodo de pagamento."""
    pm = payment_method.lower()
    if pm.endswith("_vista") or pm == "debito":
        return 1
    parts = pm.replace("_", " ").split()
    # Caso 1: numero junto com x, ex: '2x', '3x', '12x'
    for p in parts:
        if p.endswith("x") and p[:-1].isdigit():
            return int(p[:-1])
    # Caso 2: numero separado, ex: 'credito 3 x', 'credito_4_x'
    for p in parts:
        if p.isdigit() and int(p) > 1:
            return int(p)
    return 1

def find_card_fee(card_fees_df, payment_method):
    """Busca taxa de cartao compativel com o metodo de pagamento."""
    if card_fees_df.empty:
        return pd.DataFrame()
    pm = payment_method.lower()
    inst = get_installments_from_method(pm)
    # 1) Busca exata
    match = card_fees_df[card_fees_df["card_type"].str.lower() == pm]
    if not match.empty:
        return match.head(1)
    # 2) Busca pela primeira palavra do card_type dentro do payment_method + parcelas corretas
    match2 = card_fees_df[
        card_fees_df.apply(lambda r: r["card_type"].lower().split()[0] in pm, axis=1) &
        (card_fees_df["installments"] == inst)
    ]
    if not match2.empty:
        return match2.head(1)
    # 3) Fallback: primeira palavra do card_type dentro do payment_method (qualquer parcela)
    match3 = card_fees_df[
        card_fees_df.apply(lambda r: r["card_type"].lower().split()[0] in pm, axis=1)
    ]
    if not match3.empty:
        inst_match = match3[match3["installments"] == inst]
        if not inst_match.empty:
            return inst_match.head(1)
        return match3.head(1)
    return pd.DataFrame()

def fmt_brl(v):
    try:
        return "R$ {:,.2f}".format(float(v)).replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "R$ 0,00"

def get_companies():
    return q("SELECT * FROM companies WHERE active=1 ORDER BY name")

def get_banks(company_id):
    return q("SELECT * FROM banks WHERE company_id=? AND active=1 ORDER BY name", (company_id,))

def get_professionals(company_id):
    return q("SELECT * FROM professionals WHERE company_id=? AND active=1 ORDER BY name", (company_id,))

def get_categories(company_id, type_filter=None):
    if type_filter:
        return q("SELECT * FROM categories WHERE company_id=? AND type=? AND active=1 ORDER BY name", (company_id, type_filter))
    return q("SELECT * FROM categories WHERE company_id=? AND active=1 ORDER BY name", (company_id,))

def get_card_fees(company_id):
    return q("SELECT * FROM card_fees WHERE company_id=? ORDER BY installments", (company_id,))

def get_balance(company_id, bank_id=None, up_to_date=None):
    if up_to_date is None:
        up_to_date = date.today().strftime("%Y-%m-%d")
    if bank_id:
        init = q("SELECT balance_initial FROM banks WHERE id=?", (bank_id,))
        bal = float(init.iloc[0]["balance_initial"]) if not init.empty else 0
        df = q("""SELECT type, SUM(amount) as s FROM transactions
            WHERE company_id=? AND bank_id=? AND date_caixa<=? AND status='pago'
            GROUP BY type""", (company_id, bank_id, up_to_date))
    else:
        init = q("SELECT SUM(balance_initial) as s FROM banks WHERE company_id=? AND active=1", (company_id,))
        bal = float(init.iloc[0]["s"] or 0) if not init.empty else 0
        df = q("""SELECT type, SUM(amount) as s FROM transactions
            WHERE company_id=? AND date_caixa<=? AND status='pago'
            GROUP BY type""", (company_id, up_to_date))
    for _, row in df.iterrows():
        if row["type"] == "receita":
            bal += float(row["s"])
        else:
            bal -= float(row["s"])
    return bal

companies = get_companies()
cid = int(companies["id"].iloc[0]) if not companies.empty else 1
sel_company_name = companies["name"].iloc[0] if not companies.empty else "Clinica"

with st.sidebar:
    st.markdown("## Financeiro")
    st.markdown("---")
    page = st.radio("Menu", [
        "Dashboard",
        "Agendamentos",
        "Bancos",
        "Nova Entrada",
        "Nova Saida",
        "Transferencia",
        "Extrato",
        "Parcelas Cartao",
        "Fluxo de Caixa",
        "DRE",
        "Configuracoes"
    ])
    st.markdown("---")
    st.markdown("Hoje: " + date.today().strftime("%d/%m/%Y"))
    try:
        import socket
        ip = socket.gethostbyname(socket.gethostname())
        st.markdown("**Rede:** `{}:8501`".format(ip))
    except:
        pass

if page == "Dashboard":
    st.title("Dashboard Financeiro")
    today = date.today()
    mes_nomes = ["Janeiro","Fevereiro","Marco","Abril","Maio","Junho",
                 "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
    col_mes, col_ano, col_prof_dash, col_regime = st.columns([2, 1, 2, 2])
    with col_mes:
        mes_sel = st.selectbox("Mes", range(1, 13), index=today.month - 1,
                               format_func=lambda m: mes_nomes[m - 1])
    with col_ano:
        ano_sel = st.selectbox("Ano", list(range(today.year, today.year - 6, -1)))
    with col_prof_dash:
        profs_dash = get_professionals(cid)
        prof_dash_opts = {"Todos": None}
        if not profs_dash.empty:
            for _, p in profs_dash.iterrows():
                prof_dash_opts[p["name"]] = int(p["id"])
        prof_dash_sel = st.selectbox("Profissional", list(prof_dash_opts.keys()))
    with col_regime:
        regime_dash = st.selectbox("Regime", ["Competencia", "Caixa"])

    prof_dash_id = prof_dash_opts[prof_dash_sel]
    prof_sql = " AND professional_id=?" if prof_dash_id else ""
    prof_param = (prof_dash_id,) if prof_dash_id else ()
    campo_dash = "date_competencia" if regime_dash == "Competencia" else "date_caixa"

    first_month = date(ano_sel, mes_sel, 1)
    last_day = calendar.monthrange(ano_sel, mes_sel)[1]
    last_month = date(ano_sel, mes_sel, last_day)

    receitas_mes = q("""SELECT COALESCE(SUM(amount),0) as s FROM transactions
        WHERE company_id=? AND type='receita' AND {c}>=? AND {c}<=?""".format(c=campo_dash) + prof_sql,
        (cid, first_month.strftime("%Y-%m-%d"), last_month.strftime("%Y-%m-%d")) + prof_param)
    despesas_mes = q("""SELECT COALESCE(SUM(amount),0) as s FROM transactions
        WHERE company_id=? AND type='despesa' AND {c}>=? AND {c}<=?""".format(c=campo_dash) + prof_sql,
        (cid, first_month.strftime("%Y-%m-%d"), last_month.strftime("%Y-%m-%d")) + prof_param)

    r_val = float(receitas_mes.iloc[0]["s"]) if not receitas_mes.empty else 0
    d_val = float(despesas_mes.iloc[0]["s"]) if not despesas_mes.empty else 0
    lucro = r_val - d_val
    saldo_caixa = get_balance(cid)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown("<div class='metric-card metric-receita'><div class='metric-label'>Receitas do Mes</div><div class='metric-value' style='color:#27ae60'>" + fmt_brl(r_val) + "</div></div>", unsafe_allow_html=True)
    with col2:
        st.markdown("<div class='metric-card metric-despesa'><div class='metric-label'>Despesas do Mes</div><div class='metric-value' style='color:#e74c3c'>" + fmt_brl(d_val) + "</div></div>", unsafe_allow_html=True)
    with col3:
        cor = "#27ae60" if lucro >= 0 else "#e74c3c"
        st.markdown("<div class='metric-card'><div class='metric-label'>Resultado do Mes</div><div class='metric-value' style='color:" + cor + "'>" + fmt_brl(lucro) + "</div></div>", unsafe_allow_html=True)
    with col4:
        cor2 = "#27ae60" if saldo_caixa >= 0 else "#e74c3c"
        st.markdown("<div class='metric-card metric-saldo'><div class='metric-label'>Saldo em Caixa</div><div class='metric-value' style='color:" + cor2 + "'>" + fmt_brl(saldo_caixa) + "</div></div>", unsafe_allow_html=True)

    st.markdown("---")
    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Receitas x Despesas (ultimos 6 meses)")
        rows = []
        for i in range(5, -1, -1):
            m = today.month - i
            y = today.year
            while m <= 0:
                m += 12
                y -= 1
            fm = date(y, m, 1).strftime("%Y-%m-%d")
            lm = date(y, m, calendar.monthrange(y, m)[1]).strftime("%Y-%m-%d")
            meses_abrev = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]
            label = "{}/{}".format(meses_abrev[m-1], str(y)[2:])
            r = q("SELECT COALESCE(SUM(amount),0) as s FROM transactions WHERE company_id=? AND type='receita' AND {c}>=? AND {c}<=?".format(c=campo_dash) + prof_sql, (cid, fm, lm) + prof_param)
            d = q("SELECT COALESCE(SUM(amount),0) as s FROM transactions WHERE company_id=? AND type='despesa' AND {c}>=? AND {c}<=?".format(c=campo_dash) + prof_sql, (cid, fm, lm) + prof_param)
            rows.append({"mes": label, "Receitas": float(r.iloc[0]["s"]), "Despesas": float(d.iloc[0]["s"])})
        df_chart = pd.DataFrame(rows)
        fig = go.Figure()
        fig.add_bar(x=df_chart["mes"], y=df_chart["Receitas"], name="Receitas", marker_color="#27ae60")
        fig.add_bar(x=df_chart["mes"], y=df_chart["Despesas"], name="Despesas", marker_color="#e74c3c")
        fig.update_layout(barmode="group", height=300, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.subheader("Despesas por Categoria")
        df_cat = q("""SELECT c.name, SUM(t.amount) as total
            FROM transactions t JOIN categories c ON t.category_id=c.id
            WHERE t.company_id=? AND t.type='despesa'
              AND t.{c}>=? AND t.{c}<=?""".format(c=campo_dash) + prof_sql + """
            GROUP BY c.name ORDER BY total DESC LIMIT 8""",
            (cid, first_month.strftime("%Y-%m-%d"), last_month.strftime("%Y-%m-%d")) + prof_param)
        if not df_cat.empty:
            fig2 = px.pie(df_cat, names="name", values="total", hole=0.4,
                         color_discrete_sequence=px.colors.qualitative.Set3)
            fig2.update_layout(height=300, margin=dict(t=10, b=10))
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Sem despesas no mes para exibir.")

    st.subheader("Saldo por Banco")
    banks_dash = get_banks(cid)
    if not banks_dash.empty:
        bank_data = []
        for _, brow in banks_dash.iterrows():
            saldo = get_balance(cid, int(brow["id"]))
            bank_data.append({"Banco": brow["name"], "Tipo": brow["account_type"], "Saldo": fmt_brl(saldo)})
        st.dataframe(pd.DataFrame(bank_data), use_container_width=True, hide_index=True)

    st.markdown("---")
    col_banco, col_prof = st.columns(2)

    with col_banco:
        st.subheader("Receitas e Despesas por Banco (mes)")
        df_banco = q("""SELECT b.name as "Banco",
            COALESCE(SUM(CASE WHEN t.type='receita' THEN t.amount ELSE 0 END),0) as "Receitas",
            COALESCE(SUM(CASE WHEN t.type='despesa' THEN t.amount ELSE 0 END),0) as "Despesas"
            FROM transactions t LEFT JOIN banks b ON t.bank_id=b.id
            WHERE t.company_id=? AND t.{c}>=? AND t.{c}<=?""".format(c=campo_dash) + prof_sql + """
            GROUP BY b.name ORDER BY "Receitas" DESC""",
            (cid, first_month.strftime("%Y-%m-%d"), last_month.strftime("%Y-%m-%d")) + prof_param)
        if not df_banco.empty:
            df_banco["Resultado"] = df_banco["Receitas"] - df_banco["Despesas"]
            df_banco["Receitas"] = df_banco["Receitas"].apply(fmt_brl)
            df_banco["Despesas"] = df_banco["Despesas"].apply(fmt_brl)
            df_banco["Resultado"] = df_banco["Resultado"].apply(fmt_brl)
            st.dataframe(df_banco, use_container_width=True, hide_index=True)
        else:
            st.info("Sem lancamentos no mes.")

    with col_prof:
        st.subheader("Receitas e Despesas por Profissional (mes)")
        df_prof = q("""SELECT COALESCE(p.name, 'Sem Profissional') as "Profissional",
            COALESCE(b.name, '-') as "Banco",
            COALESCE(SUM(CASE WHEN t.type='receita' THEN t.amount ELSE 0 END),0) as "Receitas",
            COALESCE(SUM(CASE WHEN t.type='despesa' THEN t.amount ELSE 0 END),0) as "Despesas"
            FROM transactions t
            LEFT JOIN professionals p ON t.professional_id=p.id
            LEFT JOIN banks b ON t.bank_id=b.id
            WHERE t.company_id=? AND t.{c}>=? AND t.{c}<=?""".format(c=campo_dash) + prof_sql + """
            GROUP BY p.name, b.name ORDER BY "Profissional", "Receitas" DESC""",
            (cid, first_month.strftime("%Y-%m-%d"), last_month.strftime("%Y-%m-%d")) + prof_param)
        if not df_prof.empty:
            df_prof["Resultado"] = df_prof["Receitas"] - df_prof["Despesas"]
            df_prof["Receitas"] = df_prof["Receitas"].apply(fmt_brl)
            df_prof["Despesas"] = df_prof["Despesas"].apply(fmt_brl)
            df_prof["Resultado"] = df_prof["Resultado"].apply(fmt_brl)
            st.dataframe(df_prof, use_container_width=True, hide_index=True)
        else:
            st.info("Sem lancamentos no mes.")

    st.markdown("---")
    st.subheader("Ultimas 10 Transacoes")
    df_last = q("""SELECT t.date_competencia as "Data", t.description as "Descricao",
               t.type as "Tipo", t.amount as "Valor", t.payment_method as "Forma",
               t.status as "Status", b.name as "Banco"
        FROM transactions t LEFT JOIN banks b ON t.bank_id=b.id
        WHERE t.company_id=?""" + prof_sql + """
        ORDER BY t.created_at DESC LIMIT 10""", (cid,) + prof_param)
    if not df_last.empty:
        df_last["Valor"] = df_last["Valor"].apply(fmt_brl)
        df_last["Data"] = pd.to_datetime(df_last["Data"]).dt.strftime("%d/%m/%Y")
        df_last["Tipo"] = df_last["Tipo"].map({"receita": "Receita", "despesa": "Despesa"})
        st.dataframe(df_last, use_container_width=True, hide_index=True)

elif page == "Bancos":
    st.title("Gestao de Bancos")
    banks = get_banks(cid)
    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("Saldo Atual por Banco")
        if not banks.empty:
            rows = []
            for _, b in banks.iterrows():
                saldo = get_balance(cid, int(b["id"]))
                rows.append({"ID": int(b["id"]), "Banco": b["name"], "Tipo": b["account_type"],
                             "Saldo Inicial": fmt_brl(b["balance_initial"]), "Saldo Atual": fmt_brl(saldo)})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum banco cadastrado.")
    with col2:
        st.subheader("Adicionar Banco")
        with st.form("form_banco"):
            nb_nome = st.text_input("Nome do Banco")
            nb_tipo = st.selectbox("Tipo de Conta", ["Conta Corrente", "Conta Poupanca", "Conta Digital", "Caixa Fisico"])
            nb_saldo = st.number_input("Saldo Inicial (R$)", value=0.0, step=0.01)
            if st.form_submit_button("Adicionar"):
                if nb_nome:
                    run("INSERT INTO banks (company_id, name, account_type, balance_initial) VALUES (?,?,?,?)", (cid, nb_nome, nb_tipo, nb_saldo))
                    st.success("Banco adicionado!")
                    st.rerun()
                else:
                    st.error("Informe o nome do banco.")
    st.markdown("---")
    st.subheader("Editar / Desativar Banco")
    if not banks.empty:
        bank_sel = st.selectbox("Selecionar banco", banks["name"].tolist(), key="bank_edit_sel")
        b_row = banks[banks["name"] == bank_sel].iloc[0]
        tipo_list = ["Conta Corrente", "Conta Poupanca", "Conta Digital", "Caixa Fisico"]
        idx = tipo_list.index(b_row["account_type"]) if b_row["account_type"] in tipo_list else 0
        col_e1, col_e2, col_e3 = st.columns(3)
        with col_e1:
            new_name = st.text_input("Nome", value=b_row["name"], key="edit_bname")
        with col_e2:
            new_type = st.selectbox("Tipo", tipo_list, index=idx)
        with col_e3:
            new_bal = st.number_input("Saldo Inicial", value=float(b_row["balance_initial"]), key="edit_bbal")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Salvar Alteracoes", key="save_bank"):
                run("UPDATE banks SET name=?, account_type=?, balance_initial=? WHERE id=?", (new_name, new_type, new_bal, int(b_row["id"])))
                st.success("Banco atualizado!")
                st.rerun()
        with c2:
            if st.button("Desativar Banco", key="del_bank"):
                run("UPDATE banks SET active=0 WHERE id=?", (int(b_row["id"]),))
                st.success("Banco desativado.")
                st.rerun()

elif page == "Nova Entrada":
    st.title("Nova Entrada de Receita")
    banks = get_banks(cid)
    categories = get_categories(cid, "receita")
    professionals = get_professionals(cid)
    card_fees_df = get_card_fees(cid)

    if banks.empty:
        st.warning("Cadastre ao menos um banco antes de lancar entradas.")
        st.stop()

    bank_opts = {r["name"]: int(r["id"]) for _, r in banks.iterrows()}
    cat_opts = {r["name"]: int(r["id"]) for _, r in categories.iterrows()} if not categories.empty else {}
    prof_opts = {"Nenhum": None}
    if not professionals.empty:
        for _, r in professionals.iterrows():
            prof_opts[r["name"]] = int(r["id"])

    FORMAS_PAGAMENTO = {
        "Dinheiro": "dinheiro",
        "PIX": "pix",
        "Debito em Conta": "debito_em_conta",
        "Credito em Conta": "credito_em_conta",
        "TED / DOC": "ted/doc",
        "Boleto Bancario": "boleto",
        "Deposito Bancario": "deposito",
        "Cheque": "cheque",
    }
    if not card_fees_df.empty:
        for _, cf in card_fees_df.iterrows():
            ct = cf["card_type"].strip()
            inst = int(cf["installments"])
            key = "Cartao {}".format(ct)
            val = ct.lower().replace(" ", "_")
            FORMAS_PAGAMENTO[key] = val
    forma_label = st.selectbox("Forma de Pagamento", list(FORMAS_PAGAMENTO.keys()))
    payment_method = FORMAS_PAGAMENTO[forma_label]
    is_card = not find_card_fee(card_fees_df, payment_method).empty

    if is_card and not card_fees_df.empty:
        fee_row = find_card_fee(card_fees_df, payment_method)
        if not fee_row.empty:
            fee_pct = float(fee_row.iloc[0]["fee_percent"])
            days = int(fee_row.iloc[0]["days_to_receive"])
            parcelas = int(fee_row.iloc[0]["installments"])
            st.info("Taxa: {}% | Recebimento em {} dias | {} parcela(s)".format(fee_pct, days, parcelas))

    with st.form("form_entrada", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            descricao = st.text_input("Descricao")
            valor = st.number_input("Valor Bruto (R$)", min_value=0.01, step=0.01)
            data_comp = st.date_input("Data de Competencia", value=date.today())
            banco = st.selectbox("Banco", list(bank_opts.keys()))
        with col2:
            categoria = st.selectbox("Categoria", list(cat_opts.keys()) if cat_opts else ["Sem categoria"])
            profissional = st.selectbox("Profissional", list(prof_opts.keys()))
            status = st.selectbox("Status", ["pago", "pendente", "cancelado"])
            obs = st.text_area("Observacoes", height=80)

        submitted = st.form_submit_button("Lancar Entrada", use_container_width=True)

        if submitted:
            if not descricao or valor <= 0:
                st.error("Preencha descricao e valor.")
            else:
                bank_id = bank_opts[banco]
                cat_id = cat_opts.get(categoria) if cat_opts else None
                prof_id = prof_opts.get(profissional)

                if is_card and not card_fees_df.empty:
                    fee_row2 = find_card_fee(card_fees_df, payment_method)
                    if not fee_row2.empty:
                        fee_pct2 = float(fee_row2.iloc[0]["fee_percent"])
                        days2 = int(fee_row2.iloc[0]["days_to_receive"])
                        parcelas2 = int(fee_row2.iloc[0]["installments"])
                        valor_liq_parcela = round(valor * (1 - fee_pct2 / 100) / parcelas2, 2)
                        grp = str(uuid.uuid4())[:8]
                        insert_data = []
                        for i in range(1, parcelas2 + 1):
                            d_caixa = data_comp + timedelta(days=days2 * i if parcelas2 > 1 else days2)
                            desc_p = descricao + " [{}/{}]".format(i, parcelas2)
                            insert_data.append((
                                cid, bank_id, prof_id, cat_id,
                                "receita", desc_p, valor_liq_parcela,
                                data_comp.strftime("%Y-%m-%d"),
                                d_caixa.strftime("%Y-%m-%d"),
                                payment_method,
                                "pendente" if i > 1 else status,
                                grp, i, parcelas2, obs
                            ))
                        run_many("""INSERT INTO transactions
                            (company_id, bank_id, professional_id, category_id, type, description,
                             amount, date_competencia, date_caixa, payment_method, status,
                             installment_group, installment_num, installment_total, notes)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", insert_data)
                        st.success("{} parcela(s) lancada(s)! Valor liquido por parcela: {}".format(parcelas2, fmt_brl(valor_liq_parcela)))
                    else:
                        run("""INSERT INTO transactions
                            (company_id, bank_id, professional_id, category_id, type, description,
                             amount, date_competencia, date_caixa, payment_method, status, notes)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (cid, bank_id, prof_id, cat_id, "receita", descricao, valor,
                             data_comp.strftime("%Y-%m-%d"), data_comp.strftime("%Y-%m-%d"),
                             payment_method, status, obs))
                        st.success("Entrada lancada!")
                else:
                    run("""INSERT INTO transactions
                        (company_id, bank_id, professional_id, category_id, type, description,
                         amount, date_competencia, date_caixa, payment_method, status, notes)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (cid, bank_id, prof_id, cat_id, "receita", descricao, valor,
                         data_comp.strftime("%Y-%m-%d"), data_comp.strftime("%Y-%m-%d"),
                         payment_method, status, obs))
                    st.success("Entrada lancada com sucesso!")

elif page == "Nova Saida":
    st.title("Nova Saida de Despesa")
    banks = get_banks(cid)
    categories = get_categories(cid, "despesa")
    professionals = get_professionals(cid)

    if banks.empty:
        st.warning("Cadastre ao menos um banco antes de lancar saidas.")
        st.stop()

    bank_opts = {r["name"]: int(r["id"]) for _, r in banks.iterrows()}
    cat_opts = {r["name"]: int(r["id"]) for _, r in categories.iterrows()} if not categories.empty else {}
    prof_opts = {"Nenhum": None}
    if not professionals.empty:
        for _, r in professionals.iterrows():
            prof_opts[r["name"]] = int(r["id"])

    with st.form("form_saida", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            descricao = st.text_input("Descricao")
            valor = st.number_input("Valor (R$)", min_value=0.01, step=0.01)
            data_comp = st.date_input("Data de Competencia", value=date.today())
            data_caixa = st.date_input("Data de Pagamento", value=date.today())
            banco = st.selectbox("Banco", list(bank_opts.keys()))
        with col2:
            categoria = st.selectbox("Categoria", list(cat_opts.keys()) if cat_opts else ["Sem categoria"])
            profissional = st.selectbox("Profissional", list(prof_opts.keys()))
            card_fees_saida = get_card_fees(cid)
            FORMAS_SAIDA = {
                "Dinheiro": "dinheiro",
                "PIX": "pix",
                "Debito em Conta": "debito_em_conta",
                "Credito em Conta": "credito_em_conta",
                "TED / DOC": "ted/doc",
                "Boleto Bancario": "boleto",
                "Deposito Bancario": "deposito",
                "Cheque": "cheque",
            }
            if not card_fees_saida.empty:
                for _, cf in card_fees_saida.iterrows():
                    ct = cf["card_type"].strip()
                    key = "Cartao {}".format(ct)
                    val = ct.lower().replace(" ", "_")
                    FORMAS_SAIDA[key] = val
            forma_saida_label = st.selectbox("Forma de Pagamento", list(FORMAS_SAIDA.keys()))
            payment_method = FORMAS_SAIDA[forma_saida_label]
            status = st.selectbox("Status", ["pago", "pendente", "cancelado"])
            obs = st.text_area("Observacoes", height=80)
        parcelado = st.checkbox("Parcelar esta despesa?")
        num_parcelas = 1
        if parcelado:
            num_parcelas = st.number_input("Numero de parcelas", min_value=2, max_value=60, value=2, step=1)
        submitted = st.form_submit_button("Lancar Saida", use_container_width=True)
        if submitted:
            if not descricao or valor <= 0:
                st.error("Preencha descricao e valor.")
            else:
                bank_id = bank_opts[banco]
                cat_id = cat_opts.get(categoria) if cat_opts else None
                prof_id = prof_opts.get(profissional)
                valor_parcela = round(valor / num_parcelas, 2)
                if parcelado and num_parcelas > 1:
                    grp = str(uuid.uuid4())[:8]
                    insert_data = []
                    for i in range(1, int(num_parcelas) + 1):
                        d_c = data_caixa + timedelta(days=30 * (i - 1))
                        desc_p = descricao + " [{}/{}]".format(i, int(num_parcelas))
                        insert_data.append((
                            cid, bank_id, prof_id, cat_id,
                            "despesa", desc_p, valor_parcela,
                            data_comp.strftime("%Y-%m-%d"), d_c.strftime("%Y-%m-%d"),
                            payment_method,
                            "pendente" if i > 1 else status,
                            grp, i, int(num_parcelas), obs
                        ))
                    run_many("""INSERT INTO transactions
                        (company_id, bank_id, professional_id, category_id, type, description,
                         amount, date_competencia, date_caixa, payment_method, status,
                         installment_group, installment_num, installment_total, notes)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", insert_data)
                    st.success("{} parcelas lancadas! Valor por parcela: {}".format(int(num_parcelas), fmt_brl(valor_parcela)))
                else:
                    run("""INSERT INTO transactions
                        (company_id, bank_id, professional_id, category_id, type, description,
                         amount, date_competencia, date_caixa, payment_method, status, notes)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (cid, bank_id, prof_id, cat_id, "despesa", descricao, valor,
                         data_comp.strftime("%Y-%m-%d"), data_caixa.strftime("%Y-%m-%d"),
                         payment_method, status, obs))
                    st.success("Saida lancada com sucesso!")

elif page == "Transferencia":
    st.title("Transferencia entre Bancos")
    banks_transf = get_banks(cid)
    if banks_transf.empty or len(banks_transf) < 2:
        st.warning("Cadastre ao menos dois bancos para realizar transferencias.")
        st.stop()

    bank_opts_t = {r["name"]: int(r["id"]) for _, r in banks_transf.iterrows()}

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Nova Transferencia")
        with st.form("form_transf", clear_on_submit=True):
            banco_origem = st.selectbox("Banco de Origem", list(bank_opts_t.keys()), key="t_orig")
            banco_destino = st.selectbox("Banco de Destino", list(bank_opts_t.keys()), key="t_dest")
            valor_transf = st.number_input("Valor (R$)", min_value=0.01, step=0.01)
            data_transf = st.date_input("Data", value=date.today())
            obs_transf = st.text_area("Observacao", height=70)
            submitted_t = st.form_submit_button("Realizar Transferencia", use_container_width=True)
            if submitted_t:
                if banco_origem == banco_destino:
                    st.error("Banco de origem e destino nao podem ser iguais.")
                elif valor_transf <= 0:
                    st.error("Informe um valor valido.")
                else:
                    bid_orig = bank_opts_t[banco_origem]
                    bid_dest = bank_opts_t[banco_destino]
                    desc_orig = "Transferencia para {} - {}".format(banco_destino, obs_transf or "")
                    desc_dest = "Transferencia de {} - {}".format(banco_origem, obs_transf or "")
                    data_str = data_transf.strftime("%Y-%m-%d")
                    run("""INSERT INTO transactions
                        (company_id, bank_id, type, description, amount,
                         date_competencia, date_caixa, payment_method, status, notes)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (cid, bid_orig, "despesa", desc_orig, valor_transf,
                         data_str, data_str, "transferencia", "pago", obs_transf))
                    run("""INSERT INTO transactions
                        (company_id, bank_id, type, description, amount,
                         date_competencia, date_caixa, payment_method, status, notes)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (cid, bid_dest, "receita", desc_dest, valor_transf,
                         data_str, data_str, "transferencia", "pago", obs_transf))
                    st.success("Transferencia de {} realizada: {} → {}".format(
                        fmt_brl(valor_transf), banco_origem, banco_destino))
                    st.rerun()

    with col2:
        st.subheader("Saldo Atual por Banco")
        saldos = []
        for _, b in banks_transf.iterrows():
            saldos.append({"Banco": b["name"], "Saldo": fmt_brl(get_balance(cid, int(b["id"])))})
        st.dataframe(pd.DataFrame(saldos), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Historico de Transferencias")
    df_transf = q("""SELECT t.date_competencia as "Data", t.description as "Descricao",
               t.amount as "Valor", t.type as "Tipo", b.name as "Banco"
        FROM transactions t LEFT JOIN banks b ON t.bank_id=b.id
        WHERE t.company_id=? AND t.payment_method='transferencia'
        ORDER BY t.date_competencia DESC, t.created_at DESC LIMIT 50""", (cid,))
    if not df_transf.empty:
        df_transf["Valor"] = df_transf["Valor"].apply(fmt_brl)
        df_transf["Data"] = pd.to_datetime(df_transf["Data"]).dt.strftime("%d/%m/%Y")
        df_transf["Tipo"] = df_transf["Tipo"].map({"receita": "Entrada", "despesa": "Saida"})
        st.dataframe(df_transf, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma transferencia realizada ainda.")

elif page == "Extrato":
    st.title("Extrato de Transacoes")
    today = date.today()
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        dt_ini = st.date_input("De", value=today.replace(day=1))
    with col2:
        dt_fim = st.date_input("Ate", value=today)
    with col3:
        tipo_filt = st.selectbox("Tipo", ["Todos", "receita", "despesa"])
    with col4:
        banks_ext = get_banks(cid)
        bank_filt_opts = {"Todos": None}
        if not banks_ext.empty:
            for _, b in banks_ext.iterrows():
                bank_filt_opts[b["name"]] = int(b["id"])
        bank_filt = st.selectbox("Banco", list(bank_filt_opts.keys()))
    with col5:
        profs_ext = get_professionals(cid)
        prof_filt_opts = {"Todos": None}
        if not profs_ext.empty:
            for _, p in profs_ext.iterrows():
                prof_filt_opts[p["name"]] = int(p["id"])
        prof_filt = st.selectbox("Profissional", list(prof_filt_opts.keys()))
    with col6:
        data_filt = st.selectbox("Filtrar por", ["Competencia", "Caixa"])

    campo_data = "t.date_competencia" if data_filt == "Competencia" else "t.date_caixa"
    ordem_data = "t.date_competencia" if data_filt == "Competencia" else "t.date_caixa"

    sql = """SELECT t.id, t.date_competencia as "Competencia", t.date_caixa as "Caixa",
               t.description as "Descricao", t.type as "Tipo", t.amount as "Valor",
               t.payment_method as "Forma", t.status as "Status",
               b.name as "Banco", c.name as "Categoria",
               COALESCE(p.name, '-') as "Profissional",
               t.installment_num as "Parc", t.installment_total as "Total_Parc"
        FROM transactions t
        LEFT JOIN banks b ON t.bank_id=b.id
        LEFT JOIN categories c ON t.category_id=c.id
        LEFT JOIN professionals p ON t.professional_id=p.id
        WHERE t.company_id=? AND {campo}>=? AND {campo}<=?""".format(campo=campo_data)
    params = [cid, dt_ini.strftime("%Y-%m-%d"), dt_fim.strftime("%Y-%m-%d")]
    if tipo_filt != "Todos":
        sql += " AND t.type=?"
        params.append(tipo_filt)
    bank_id_filt = bank_filt_opts[bank_filt]
    if bank_id_filt is not None:
        sql += " AND t.bank_id=?"
        params.append(bank_id_filt)
    prof_id_filt = prof_filt_opts[prof_filt]
    if prof_id_filt is not None:
        sql += " AND t.professional_id=?"
        params.append(prof_id_filt)
    sql += " ORDER BY {} DESC, t.created_at DESC".format(ordem_data)

    df = q(sql, tuple(params))
    if df.empty:
        st.info("Nenhuma transacao encontrada.")
    else:
        r_total = df[df["Tipo"] == "receita"]["Valor"].sum()
        d_total = df[df["Tipo"] == "despesa"]["Valor"].sum()
        saldo_anterior = get_balance(cid, bank_id_filt, dt_ini.strftime("%Y-%m-%d"))
        saldo_final = saldo_anterior + r_total - d_total
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Receitas", fmt_brl(r_total))
        c2.metric("Total Despesas", fmt_brl(d_total))
        c3.metric("Saldo Anterior", fmt_brl(saldo_anterior))
        c4.metric("Saldo Final", fmt_brl(saldo_final))

        df_show = df.copy()
        df_show["Valor"] = df_show["Valor"].apply(fmt_brl)
        df_show["Competencia"] = pd.to_datetime(df_show["Competencia"]).dt.strftime("%d/%m/%Y")
        df_show["Caixa"] = pd.to_datetime(df_show["Caixa"]).dt.strftime("%d/%m/%Y")
        df_show["Tipo"] = df_show["Tipo"].map({"receita": "Receita", "despesa": "Despesa"})
        df_show["Parcela"] = df_show.apply(
            lambda r: "{}/{}".format(int(r["Parc"]), int(r["Total_Parc"])) if pd.notna(r["Parc"]) else "-", axis=1)
        st.dataframe(df_show[["id","Competencia","Caixa","Descricao","Tipo","Valor","Forma","Status","Banco","Categoria","Profissional","Parcela"]],
                     use_container_width=True, hide_index=True)

        st.markdown("---")
        col_edit, col_del = st.columns(2)

        with col_edit:
            st.subheader("Editar Lancamento")
            edit_id = st.number_input("ID do lancamento", min_value=1, step=1, key="edit_id")
            df_edit = q("SELECT * FROM transactions WHERE id=? AND company_id=?", (int(edit_id), cid))
            if not df_edit.empty and st.button("Carregar", key="btn_load"):
                st.session_state["edit_row"] = df_edit.iloc[0].to_dict()
            if "edit_row" in st.session_state:
                row = st.session_state["edit_row"]
                banks_e = get_banks(cid)
                cats_e = get_categories(cid)
                profs_e = get_professionals(cid)
                bank_opts_e = {r["name"]: int(r["id"]) for _, r in banks_e.iterrows()} if not banks_e.empty else {}
                cat_opts_e = {r["name"]: int(r["id"]) for _, r in cats_e.iterrows()} if not cats_e.empty else {}
                prof_opts_e = {"Nenhum": None}
                if not profs_e.empty:
                    for _, p in profs_e.iterrows():
                        prof_opts_e[p["name"]] = int(p["id"])
                with st.form("form_edit"):
                    new_desc = st.text_input("Descricao", value=str(row["description"]))
                    new_valor = st.number_input("Valor", value=float(row["amount"]), min_value=0.01, step=0.01)
                    new_comp = st.date_input("Data Competencia", value=date.fromisoformat(str(row["date_competencia"])))
                    new_caixa = st.date_input("Data Caixa", value=date.fromisoformat(str(row["date_caixa"])))
                    new_status = st.selectbox("Status", ["pago","pendente","cancelado"],
                        index=["pago","pendente","cancelado"].index(row["status"]) if row["status"] in ["pago","pendente","cancelado"] else 0)
                    bank_names_e = list(bank_opts_e.keys())
                    cur_bank = next((n for n, i in bank_opts_e.items() if i == row["bank_id"]), bank_names_e[0] if bank_names_e else "")
                    new_banco = st.selectbox("Banco", bank_names_e, index=bank_names_e.index(cur_bank) if cur_bank in bank_names_e else 0) if bank_names_e else None
                    new_obs = st.text_area("Observacoes", value=str(row["notes"] or ""), height=60)
                    if st.form_submit_button("Salvar Alteracoes", use_container_width=True):
                        new_bid = bank_opts_e.get(new_banco) if new_banco else row["bank_id"]
                        run("""UPDATE transactions SET description=?, amount=?, date_competencia=?,
                            date_caixa=?, status=?, bank_id=?, notes=? WHERE id=? AND company_id=?""",
                            (new_desc, new_valor, new_comp.strftime("%Y-%m-%d"),
                             new_caixa.strftime("%Y-%m-%d"), new_status, new_bid,
                             new_obs, int(row["id"]), cid))
                        del st.session_state["edit_row"]
                        st.success("Lancamento {} atualizado!".format(int(row["id"])))
                        st.rerun()

        with col_del:
            st.subheader("Excluir Lancamento")
            del_id = st.number_input("ID do lancamento", min_value=1, step=1, key="del_id_ext")
            if st.button("Excluir", key="btn_del"):
                run("DELETE FROM transactions WHERE id=? AND company_id=?", (int(del_id), cid))
                st.success("Lancamento {} excluido!".format(int(del_id)))
                st.rerun()

        st.markdown("---")
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Extrato")
        st.download_button("Exportar Excel", data=buf.getvalue(),
                           file_name="extrato_{}_{}.xlsx".format(dt_ini, dt_fim),
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

elif page == "Parcelas Cartao":
    st.title("Parcelas de Cartao de Credito")
    today = date.today()
    df = q("""SELECT t.id, t.date_competencia as "Competencia", t.date_caixa as "Recebimento",
               t.description as "Descricao", t.amount as "Valor", t.status as "Status",
               t.payment_method as "Cartao", b.name as "Banco",
               t.installment_num as "Num", t.installment_total as "Total",
               t.installment_group as "Grupo"
        FROM transactions t LEFT JOIN banks b ON t.bank_id=b.id
        WHERE t.company_id=?
          AND t.payment_method NOT IN (
              'dinheiro','pix','debito_em_conta','credito_em_conta',
              'ted/doc','boleto','deposito','cheque','transferencia'
          )
        ORDER BY t.date_caixa ASC""", (cid,))
    if df.empty:
        st.info("Nenhuma parcela de cartao encontrada.")
    else:
        pendente = df[df["Status"] == "pendente"]["Valor"].sum()
        recebido = df[df["Status"] == "pago"]["Valor"].sum()
        c1, c2 = st.columns(2)
        c1.metric("A Receber (Pendente)", fmt_brl(pendente))
        c2.metric("Ja Recebido", fmt_brl(recebido))
        status_filt = st.selectbox("Filtrar por Status", ["Todos", "pendente", "pago"])
        df_show = df if status_filt == "Todos" else df[df["Status"] == status_filt]
        df_fmt = df_show.copy()
        df_fmt["Valor"] = df_fmt["Valor"].apply(fmt_brl)
        df_fmt["Competencia"] = pd.to_datetime(df_fmt["Competencia"]).dt.strftime("%d/%m/%Y")
        df_fmt["Recebimento"] = pd.to_datetime(df_fmt["Recebimento"]).dt.strftime("%d/%m/%Y")
        df_fmt["Parcela"] = df_fmt.apply(
            lambda r: "{}/{}".format(int(r["Num"]), int(r["Total"])) if pd.notna(r["Num"]) else "-", axis=1)
        st.dataframe(df_fmt[["id","Competencia","Recebimento","Descricao","Cartao","Parcela","Valor","Status","Banco"]],
                     use_container_width=True, hide_index=True)
        st.markdown("---")
        col_recv, col_del = st.columns(2)
        with col_recv:
            st.subheader("Marcar parcela como Recebida")
            parc_id = st.number_input("ID da parcela", min_value=1, step=1, key="recv_id")
            if st.button("Confirmar Recebimento", key="btn_recv"):
                run("UPDATE transactions SET status='pago', date_caixa=? WHERE id=? AND company_id=?",
                    (today.strftime("%Y-%m-%d"), int(parc_id), cid))
                st.success("Parcela marcada como recebida!")
                st.rerun()
        with col_del:
            st.subheader("Excluir Parcela")
            del_parc_id = st.number_input("ID da parcela", min_value=1, step=1, key="del_parc_id")
            del_grupo = st.checkbox("Excluir todas as parcelas do grupo")
            if st.button("Excluir Parcela", key="btn_del_parc"):
                if del_grupo:
                    grp_row = q("SELECT installment_group FROM transactions WHERE id=? AND company_id=?", (int(del_parc_id), cid))
                    if not grp_row.empty and grp_row.iloc[0]["installment_group"]:
                        grp = grp_row.iloc[0]["installment_group"]
                        run("DELETE FROM transactions WHERE installment_group=? AND company_id=?", (grp, cid))
                        st.success("Todas as parcelas do grupo excluidas!")
                    else:
                        run("DELETE FROM transactions WHERE id=? AND company_id=?", (int(del_parc_id), cid))
                        st.success("Parcela {} excluida!".format(int(del_parc_id)))
                else:
                    run("DELETE FROM transactions WHERE id=? AND company_id=?", (int(del_parc_id), cid))
                    st.success("Parcela {} excluida!".format(int(del_parc_id)))
                st.rerun()

elif page == "Fluxo de Caixa":
    st.title("Fluxo de Caixa (Regime de Caixa)")
    today = date.today()
    col1, col2 = st.columns(2)
    with col1:
        dt_ini = st.date_input("De", value=today.replace(day=1))
    with col2:
        dt_fim = st.date_input("Ate", value=today)

    df_in = q("""SELECT date_caixa as data, SUM(amount) as total FROM transactions
        WHERE company_id=? AND type='receita' AND status='pago'
          AND date_caixa>=? AND date_caixa<=?
        GROUP BY date_caixa ORDER BY date_caixa""",
        (cid, dt_ini.strftime("%Y-%m-%d"), dt_fim.strftime("%Y-%m-%d")))
    df_out = q("""SELECT date_caixa as data, SUM(amount) as total FROM transactions
        WHERE company_id=? AND type='despesa' AND status='pago'
          AND date_caixa>=? AND date_caixa<=?
        GROUP BY date_caixa ORDER BY date_caixa""",
        (cid, dt_ini.strftime("%Y-%m-%d"), dt_fim.strftime("%Y-%m-%d")))

    all_dates = pd.date_range(dt_ini, dt_fim, freq="D")
    df_flow = pd.DataFrame({"data": all_dates})
    df_flow["data_str"] = df_flow["data"].dt.strftime("%Y-%m-%d")

    if not df_in.empty:
        df_in["data"] = pd.to_datetime(df_in["data"]).dt.strftime("%Y-%m-%d")
    if not df_out.empty:
        df_out["data"] = pd.to_datetime(df_out["data"]).dt.strftime("%Y-%m-%d")

    if not df_in.empty:
        df_flow = df_flow.merge(df_in.rename(columns={"total": "entradas", "data": "data_str"}), on="data_str", how="left")
    else:
        df_flow["entradas"] = 0.0
    if not df_out.empty:
        df_flow = df_flow.merge(df_out.rename(columns={"total": "saidas", "data": "data_str"}), on="data_str", how="left")
    else:
        df_flow["saidas"] = 0.0

    df_flow["entradas"] = df_flow["entradas"].fillna(0)
    df_flow["saidas"] = df_flow["saidas"].fillna(0)
    df_flow["saldo_dia"] = df_flow["entradas"] - df_flow["saidas"]
    df_flow["saldo_acum"] = df_flow["saldo_dia"].cumsum()

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Entradas", fmt_brl(df_flow["entradas"].sum()))
    c2.metric("Total Saidas", fmt_brl(df_flow["saidas"].sum()))
    c3.metric("Saldo do Periodo", fmt_brl(df_flow["saldo_dia"].sum()))

    fig = go.Figure()
    fig.add_bar(x=df_flow["data"], y=df_flow["entradas"], name="Entradas", marker_color="#27ae60", opacity=0.7)
    fig.add_bar(x=df_flow["data"], y=-df_flow["saidas"], name="Saidas", marker_color="#e74c3c", opacity=0.7)
    fig.add_scatter(x=df_flow["data"], y=df_flow["saldo_acum"], name="Saldo Acumulado",
                    line=dict(color="#3498db", width=2.5))
    fig.update_layout(barmode="relative", title="Fluxo de Caixa Diario", height=400)
    st.plotly_chart(fig, use_container_width=True)

    df_show = df_flow[["data", "entradas", "saidas", "saldo_dia", "saldo_acum"]].copy()
    df_show["data"] = df_show["data"].dt.strftime("%d/%m/%Y")
    df_show.columns = ["Data", "Entradas", "Saidas", "Saldo do Dia", "Saldo Acumulado"]
    for col in ["Entradas", "Saidas", "Saldo do Dia", "Saldo Acumulado"]:
        df_show[col] = df_show[col].apply(fmt_brl)
    st.dataframe(df_show, use_container_width=True, hide_index=True)

elif page == "DRE":
    st.title("DRE - Demonstracao do Resultado")
    st.caption("Regime de Competencia")
    today = date.today()
    col1, col2 = st.columns(2)
    with col1:
        ano = st.selectbox("Ano", list(range(today.year, today.year - 5, -1)))
    with col2:
        mes_names = ["Ano todo","Janeiro","Fevereiro","Marco","Abril","Maio","Junho",
                     "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
        mes_idx = st.selectbox("Mes", range(0, 13), format_func=lambda m: mes_names[m])

    if mes_idx == 0:
        dt_ini = "{}-01-01".format(ano)
        dt_fim = "{}-12-31".format(ano)
    else:
        dt_ini = "{}-{:02d}-01".format(ano, mes_idx)
        dt_fim = "{}-{:02d}-{:02d}".format(ano, mes_idx, calendar.monthrange(ano, mes_idx)[1])

    df_rec = q("""SELECT c.name as categoria, SUM(t.amount) as total
        FROM transactions t LEFT JOIN categories c ON t.category_id=c.id
        WHERE t.company_id=? AND t.type='receita'
          AND t.date_competencia>=? AND t.date_competencia<=?
        GROUP BY c.name ORDER BY total DESC""", (cid, dt_ini, dt_fim))
    df_desp = q("""SELECT c.name as categoria, SUM(t.amount) as total
        FROM transactions t LEFT JOIN categories c ON t.category_id=c.id
        WHERE t.company_id=? AND t.type='despesa'
          AND t.date_competencia>=? AND t.date_competencia<=?
        GROUP BY c.name ORDER BY total DESC""", (cid, dt_ini, dt_fim))

    total_rec = df_rec["total"].sum() if not df_rec.empty else 0
    total_desp = df_desp["total"].sum() if not df_desp.empty else 0
    resultado = total_rec - total_desp
    margem = (resultado / total_rec * 100) if total_rec > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Receita Bruta", fmt_brl(total_rec))
    c2.metric("Total Despesas", fmt_brl(total_desp))
    c3.metric("Resultado Liquido", fmt_brl(resultado))
    c4.metric("Margem Liquida", "{:.1f}%".format(margem))

    st.markdown("---")
    col_dre, col_chart = st.columns([2, 1])
    with col_dre:
        st.markdown("### Demonstracao do Resultado")
        dre_rows = []
        dre_rows.append(("RECEITAS OPERACIONAIS", "", ""))
        if not df_rec.empty:
            for _, r in df_rec.iterrows():
                dre_rows.append(("  " + (r["categoria"] or "Sem categoria"), fmt_brl(r["total"]), ""))
        dre_rows.append(("Total de Receitas", fmt_brl(total_rec), ""))
        dre_rows.append(("", "", ""))
        dre_rows.append(("DESPESAS OPERACIONAIS", "", ""))
        if not df_desp.empty:
            for _, r in df_desp.iterrows():
                dre_rows.append(("  " + (r["categoria"] or "Sem categoria"), "", fmt_brl(r["total"])))
        dre_rows.append(("Total de Despesas", "", fmt_brl(total_desp)))
        dre_rows.append(("", "", ""))
        label_res = "LUCRO LIQUIDO" if resultado >= 0 else "PREJUIZO LIQUIDO"
        dre_rows.append((label_res, fmt_brl(resultado), ""))
        dre_rows.append(("Margem Liquida", "{:.2f}%".format(margem), ""))
        df_dre = pd.DataFrame(dre_rows, columns=["Item", "Receitas", "Despesas"])
        st.dataframe(df_dre, use_container_width=True, hide_index=True)

    with col_chart:
        if not df_desp.empty:
            fig_dre = px.pie(df_desp, names="categoria", values="total",
                            title="Despesas por Categoria",
                            color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_dre.update_layout(height=350, margin=dict(t=40, b=10))
            st.plotly_chart(fig_dre, use_container_width=True)

    if mes_idx == 0:
        st.markdown("---")
        st.subheader("Evolucao Mensal")
        monthly = []
        for m in range(1, 13):
            fm = "{}-{:02d}-01".format(ano, m)
            lm = "{}-{:02d}-{:02d}".format(ano, m, calendar.monthrange(ano, m)[1])
            r = q("SELECT COALESCE(SUM(amount),0) as s FROM transactions WHERE company_id=? AND type='receita' AND {c}>=? AND {c}<=?".format(c=campo_dash) + prof_sql, (cid, fm, lm) + prof_param)
            d = q("SELECT COALESCE(SUM(amount),0) as s FROM transactions WHERE company_id=? AND type='despesa' AND {c}>=? AND {c}<=?".format(c=campo_dash) + prof_sql, (cid, fm, lm) + prof_param)
            rv = float(r.iloc[0]["s"])
            dv = float(d.iloc[0]["s"])
            monthly.append({"Mes": calendar.month_abbr[m], "Receita": rv, "Despesa": dv, "Resultado": rv - dv})
        df_monthly = pd.DataFrame(monthly)
        fig_m = go.Figure()
        fig_m.add_bar(x=df_monthly["Mes"], y=df_monthly["Receita"], name="Receita", marker_color="#27ae60")
        fig_m.add_bar(x=df_monthly["Mes"], y=df_monthly["Despesa"], name="Despesa", marker_color="#e74c3c")
        fig_m.add_scatter(x=df_monthly["Mes"], y=df_monthly["Resultado"], name="Resultado",
                         line=dict(color="#3498db", width=2.5, dash="dot"))
        fig_m.update_layout(barmode="group", height=350, margin=dict(t=10, b=10))
        st.plotly_chart(fig_m, use_container_width=True)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        if not df_rec.empty:
            df_rec.to_excel(writer, index=False, sheet_name="Receitas")
        if not df_desp.empty:
            df_desp.to_excel(writer, index=False, sheet_name="Despesas")
    st.download_button("Exportar DRE Excel", data=buf.getvalue(),
                       file_name="DRE_{}_{:02d}.xlsx".format(ano, mes_idx),
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

elif page == "Configuracoes":
    st.title("Configuracoes do Sistema")
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Empresas", "Profissionais", "Categorias", "Taxas Cartao", "Sobre"
    ])

    with tab1:
        st.subheader("Empresas Cadastradas")
        df_comp = q("SELECT * FROM companies WHERE active=1 ORDER BY name")
        st.dataframe(df_comp[["id", "name", "cnpj"]], use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("Editar Empresa")
        if not df_comp.empty:
            emp_nomes = df_comp["name"].tolist()
            emp_sel = st.selectbox("Selecionar empresa para editar", emp_nomes, key="emp_edit_sel")
            emp_row = df_comp[df_comp["name"] == emp_sel].iloc[0]
            col_emp1, col_emp2 = st.columns(2)
            with col_emp1:
                new_emp_nome = st.text_input("Nome da Empresa", value=emp_row["name"], key="edit_emp_nome")
            with col_emp2:
                new_emp_cnpj = st.text_input("CNPJ", value=emp_row["cnpj"] if emp_row["cnpj"] else "", key="edit_emp_cnpj")
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("Salvar Alteracoes", key="save_emp_btn"):
                    if new_emp_nome:
                        run("UPDATE companies SET name=?, cnpj=? WHERE id=?",
                            (new_emp_nome, new_emp_cnpj, int(emp_row["id"])))
                        st.success("Empresa atualizada!")
                        st.rerun()
                    else:
                        st.error("O nome nao pode ficar vazio.")
            with col_btn2:
                if st.button("Excluir Empresa", key="del_emp_btn"):
                    cnt = q("SELECT COUNT(*) as c FROM transactions WHERE company_id=?", (int(emp_row["id"]),))
                    total_lanc = int(cnt.iloc[0]["c"]) if not cnt.empty else 0
                    if total_lanc > 0:
                        st.error("Nao e possivel excluir: empresa possui {} lancamento(s). Apague os lancamentos primeiro em Extrato.".format(total_lanc))
                    else:
                        run("UPDATE companies SET active=0 WHERE id=?", (int(emp_row["id"]),))
                        st.success("Empresa excluida!")
                        st.rerun()
        else:
            st.info("Nenhuma empresa cadastrada.")

        st.markdown("---")
        st.subheader("Adicionar Empresa")
        with st.form("form_empresa"):
            e_nome = st.text_input("Nome da Empresa")
            e_cnpj = st.text_input("CNPJ")
            if st.form_submit_button("Adicionar"):
                if e_nome:
                    run("INSERT INTO companies (name, cnpj) VALUES (?,?)", (e_nome, e_cnpj))
                    st.success("Empresa adicionada!")
                    st.rerun()

    with tab2:
        st.subheader("Profissionais")
        df_prof = get_professionals(cid)
        if not df_prof.empty:
            st.dataframe(df_prof[["id", "name", "role"]], use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum profissional cadastrado.")
        st.subheader("Adicionar Profissional")
        with st.form("form_prof"):
            p_nome = st.text_input("Nome")
            p_cargo = st.text_input("Cargo / Funcao")
            if st.form_submit_button("Adicionar"):
                if p_nome:
                    run("INSERT INTO professionals (company_id, name, role) VALUES (?,?,?)", (cid, p_nome, p_cargo))
                    st.success("Profissional adicionado!")
                    st.rerun()
        if not df_prof.empty:
            st.subheader("Desativar Profissional")
            p_sel = st.selectbox("Selecionar", df_prof["name"].tolist(), key="del_prof_sel")
            if st.button("Desativar", key="del_prof_btn"):
                p_id = int(df_prof[df_prof["name"] == p_sel].iloc[0]["id"])
                run("UPDATE professionals SET active=0 WHERE id=?", (p_id,))
                st.success("Profissional desativado.")
                st.rerun()

    with tab3:
        st.subheader("Categorias de Receita")
        df_cat_r = get_categories(cid, "receita")
        if not df_cat_r.empty:
            st.dataframe(df_cat_r[["id", "name"]], use_container_width=True, hide_index=True)
        st.subheader("Categorias de Despesa")
        df_cat_d = get_categories(cid, "despesa")
        if not df_cat_d.empty:
            st.dataframe(df_cat_d[["id", "name"]], use_container_width=True, hide_index=True)
        st.subheader("Adicionar Categoria")
        with st.form("form_cat"):
            c_nome = st.text_input("Nome da Categoria")
            c_tipo = st.selectbox("Tipo", ["receita", "despesa"])
            if st.form_submit_button("Adicionar"):
                if c_nome:
                    run("INSERT INTO categories (company_id, name, type) VALUES (?,?,?)", (cid, c_nome, c_tipo))
                    st.success("Categoria adicionada!")
                    st.rerun()

    with tab4:
        st.subheader("Taxas de Cartao Cadastradas")
        df_fees = get_card_fees(cid)
        if not df_fees.empty:
            df_fees_show = df_fees[["card_type", "installments", "fee_percent", "days_to_receive"]].copy()
            df_fees_show.columns = ["Tipo/Nome", "Parcelas", "Taxa %", "Dias p/ Receber"]
            st.dataframe(df_fees_show, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhuma taxa cadastrada.")

        st.markdown("---")
        st.subheader("Adicionar Nova Taxa")
        with st.form("form_add_taxa"):
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                new_card_type = st.text_input("Nome/Tipo do Cartao *", placeholder="ex: credito_4x, elo_vista, maquininha_x")
                new_installments = st.number_input("Numero de Parcelas", min_value=1, max_value=60, value=1, step=1)
            with col_t2:
                new_fee_add = st.number_input("Taxa (%)", min_value=0.0, max_value=100.0, value=2.5, step=0.1)
                new_days_add = st.number_input("Dias para Receber", min_value=0, max_value=365, value=30, step=1)
            if st.form_submit_button("Adicionar Taxa", use_container_width=True):
                if new_card_type:
                    run("INSERT INTO card_fees (company_id, card_type, installments, fee_percent, days_to_receive) VALUES (?,?,?,?,?)",
                        (cid, new_card_type.strip(), int(new_installments), new_fee_add, int(new_days_add)))
                    st.success("Taxa adicionada com sucesso!")
                    st.rerun()
                else:
                    st.error("Informe o nome/tipo do cartao.")

        st.markdown("---")
        df_fees2 = get_card_fees(cid)
        if not df_fees2.empty:
            st.subheader("Editar Taxa Existente")
            fee_sel = st.selectbox("Selecionar taxa para editar", df_fees2["card_type"].tolist(), key="fee_sel")
            f_row = df_fees2[df_fees2["card_type"] == fee_sel].iloc[0]
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                new_fee = st.number_input("Taxa (%)", value=float(f_row["fee_percent"]),
                                         min_value=0.0, max_value=100.0, step=0.1, key="new_fee")
            with col_f2:
                new_days = st.number_input("Dias para receber", value=int(f_row["days_to_receive"]),
                                           min_value=0, max_value=365, step=1, key="new_days")
            with col_f3:
                new_inst = st.number_input("Parcelas", value=int(f_row["installments"]),
                                           min_value=1, max_value=60, step=1, key="new_inst")
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                if st.button("Salvar Alteracoes", key="save_fee"):
                    run("UPDATE card_fees SET fee_percent=?, days_to_receive=?, installments=? WHERE id=?",
                        (new_fee, new_days, int(new_inst), int(f_row["id"])))
                    st.success("Taxa atualizada!")
                    st.rerun()
            with col_s2:
                if st.button("Excluir Taxa", key="del_fee"):
                    run("DELETE FROM card_fees WHERE id=?", (int(f_row["id"]),))
                    st.success("Taxa excluida!")
                    st.rerun()

    with tab5:
        st.subheader("Sobre o Sistema")
        st.markdown("""
**Sistema Financeiro - Grupo Empresarial v2.0**

Desenvolvido com Python + Streamlit + SQLite

Funcionalidades:
- Multiplas empresas
- Receitas e despesas com parcelamento
- Cartao de credito com calculo automatico de taxas
- Controle por banco e profissional
- DRE (Regime de Competencia)
- Fluxo de Caixa (Regime de Caixa)
- Dashboard com graficos interativos
- Extrato com exportacao Excel
        """)
        st.markdown("---")
        st.subheader("Zona de Perigo")
        with st.expander("Apagar TODOS os lancamentos desta empresa"):
            st.warning("Esta acao e irreversivel!")
            confirm = st.text_input("Digite CONFIRMAR para prosseguir")
            if st.button("Apagar tudo", key="danger_del"):
                if confirm == "CONFIRMAR":
                    run("DELETE FROM transactions WHERE company_id=?", (cid,))
                    st.success("Todos os lancamentos foram apagados.")
                    st.rerun()
                else:
                    st.error("Digite CONFIRMAR para prosseguir.")
        with st.expander("🔴 RESETAR SISTEMA COMPLETO (apaga TUDO e reinicia do zero)"):
            st.error("Esta acao apaga TODAS as empresas, bancos, lancamentos, agendamentos e categorias. Nao pode ser desfeita!")
            confirm_reset = st.text_input("Digite RESETAR para confirmar", key="confirm_reset")
            if st.button("Resetar tudo agora", key="danger_reset"):
                if confirm_reset == "RESETAR":
                    for tabela in ["transactions", "agendamentos", "card_fees", "categories", "professionals", "banks", "companies"]:
                        try:
                            run(f"DELETE FROM {tabela}")
                        except Exception:
                            pass
                    init_db()
                    st.success("Sistema resetado! Recarregue a pagina para comecar do zero.")
                    st.rerun()
                else:
                    st.error("Digite RESETAR para confirmar.")

if page == "Agendamentos":
    st.title("Agendamentos")

    STATUS_AG = {
        "agendado":   ("Agendado",   "🔵"),
        "confirmado": ("Confirmado", "🟢"),
        "realizado":  ("Realizado",  "✅"),
        "falta":      ("Falta",      "🔴"),
        "cancelado":  ("Cancelado",  "⚫"),
    }

    tab_lista, tab_novo, tab_import = st.tabs(["Lista de Agendamentos", "Novo Agendamento", "Importar Planilha"])

    with tab_novo:
        st.subheader("Novo Agendamento")
        FORMAS_AG = ["Dinheiro", "PIX", "Cartao Debito", "Cartao Credito", "Convenio", "Cheque"]

        # Controle reativo de forma de pagamento fora do form
        ag_forma_sel = st.selectbox("Forma de Pagamento", FORMAS_AG, key="novo_forma")
        eh_cartao = ag_forma_sel in ("Cartao Debito", "Cartao Credito")

        if eh_cartao:
            cf_novo = get_card_fees(cid)
            bandeiras_disp = sorted(cf_novo["card_type"].unique().tolist()) if not cf_novo.empty else []
            col_b, col_p = st.columns(2)
            with col_b:
                ag_bandeira = st.selectbox("Bandeira / Tipo do Cartao", bandeiras_disp if bandeiras_disp else ["credito_vista"], key="novo_band")
            with col_p:
                ag_parcelas = st.number_input("Numero de Parcelas", min_value=1, max_value=12, value=1, step=1, key="novo_parc") if ag_forma_sel == "Cartao Credito" else 1
        else:
            ag_bandeira = None
            ag_parcelas = 1

        with st.form("form_novo_ag", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                ag_paciente = st.text_input("Nome do Paciente *")
                ag_convenio = st.text_input("Convenio / Plano")
            with col2:
                ag_medico = st.text_input("Medico")
                ag_data = st.date_input("Data do Agendamento", value=date.today())
            col3, col4 = st.columns(2)
            with col3:
                ag_tipo = st.selectbox("Tipo", ["Consulta", "Procedimento"])
            with col4:
                ag_valor = st.number_input("Valor Bruto (R$)", min_value=0.0, step=0.01, format="%.2f")

            # Preview do parcelamento com taxa
            if eh_cartao and ag_valor > 0:
                cf_novo = get_card_fees(cid)
                fee_row = find_card_fee(cf_novo, ag_bandeira or "")
                taxa_pct = float(fee_row.iloc[0]["fee_percent"]) if not fee_row.empty else 0.0
                dias_rep = int(fee_row.iloc[0]["days_to_receive"]) if not fee_row.empty else 30
                n_parc = int(ag_parcelas) if ag_forma_sel == "Cartao Credito" else 1
                valor_taxa = round(ag_valor * taxa_pct / 100, 2)
                valor_liq = round(ag_valor - valor_taxa, 2)
                liq_parcela = round(valor_liq / n_parc, 2)
                st.info(
                    f"Taxa: {taxa_pct:.2f}% = {fmt_brl(valor_taxa)} | "
                    f"Liquido: {fmt_brl(valor_liq)} | "
                    f"{n_parc}x de {fmt_brl(liq_parcela)} "
                    f"(repasse em ~{dias_rep} dias)"
                )

            ag_status = st.selectbox("Status", list(STATUS_AG.keys()),
                                     format_func=lambda s: STATUS_AG[s][1] + " " + STATUS_AG[s][0])
            salvar = st.form_submit_button("Salvar Agendamento", type="primary")

        if salvar:
            if not ag_paciente.strip():
                st.error("Informe o nome do paciente.")
            else:
                data_hora_str = ag_data.strftime("%Y-%m-%d") + " 08:00"
                run("""INSERT INTO agendamentos
                    (company_id, paciente, medico, data_hora, status, convenio,
                     tipo_consulta, valor, forma_pagamento, cartao_bandeira, cartao_parcelas)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (cid, ag_paciente.strip(), ag_medico.strip(),
                     data_hora_str, ag_status, ag_convenio.strip(),
                     ag_tipo, ag_valor, ag_forma_sel, ag_bandeira, int(ag_parcelas)))

                # Lanca parcelas no financeiro se pagamento em cartao
                if eh_cartao and ag_valor > 0:
                    import uuid as _uuid
                    cf_s = get_card_fees(cid)
                    fee_r = find_card_fee(cf_s, ag_bandeira or "")
                    taxa_s = float(fee_r.iloc[0]["fee_percent"]) if not fee_r.empty else 0.0
                    dias_s = int(fee_r.iloc[0]["days_to_receive"]) if not fee_r.empty else 30
                    n_s = int(ag_parcelas) if ag_forma_sel == "Cartao Credito" else 1
                    valor_liq_s = round(ag_valor - ag_valor * taxa_s / 100, 2)
                    liq_p_s = round(valor_liq_s / n_s, 2)
                    grupo = str(_uuid.uuid4())[:8]
                    data_base = ag_data
                    for i in range(1, n_s + 1):
                        if ag_forma_sel == "Cartao Debito":
                            dt_caixa = (data_base + timedelta(days=dias_s)).strftime("%Y-%m-%d")
                        else:
                            dt_caixa = (data_base + timedelta(days=dias_s * i)).strftime("%Y-%m-%d")
                        run("""INSERT INTO transactions
                            (company_id, type, description, amount,
                             date_competencia, date_caixa, payment_method,
                             status, installment_group, installment_num, installment_total, notes)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (cid, "receita",
                             f"{ag_tipo} - {ag_paciente.strip()} ({ag_bandeira} {i}/{n_s})",
                             liq_p_s,
                             ag_data.strftime("%Y-%m-%d"), dt_caixa,
                             ag_forma_sel, "pendente",
                             grupo, i, n_s,
                             f"Taxa {taxa_s:.2f}% aplicada. Bruto: {fmt_brl(ag_valor)}"))
                st.success(f"Agendamento de **{ag_paciente}** salvo!")
                st.rerun()

    with tab_lista:
        col_f1, col_f2, col_f3, col_f4 = st.columns([2, 2, 2, 2])
        with col_f1:
            f_data_ini = st.date_input("De", value=date.today().replace(day=1), key="ag_ini")
        with col_f2:
            f_data_fim = st.date_input("Ate", value=date.today(), key="ag_fim")
        with col_f3:
            f_status = st.selectbox("Status", ["Todos"] + list(STATUS_AG.keys()),
                                    format_func=lambda s: "Todos" if s == "Todos" else STATUS_AG[s][1] + " " + STATUS_AG[s][0])
        with col_f4:
            f_busca = st.text_input("Buscar nome / medico")

        sql_ag = "SELECT * FROM agendamentos WHERE company_id=? AND date(data_hora) BETWEEN ? AND ?"
        params_ag = [cid, f_data_ini.strftime("%Y-%m-%d"), f_data_fim.strftime("%Y-%m-%d")]
        if f_status != "Todos":
            sql_ag += " AND status=?"
            params_ag.append(f_status)
        if f_busca.strip():
            sql_ag += " AND (paciente LIKE ? OR medico LIKE ?)"
            params_ag += [f"%{f_busca}%", f"%{f_busca}%"]
        sql_ag += " ORDER BY data_hora ASC"

        df_ag = q(sql_ag, tuple(params_ag))

        if df_ag.empty:
            st.info("Nenhum agendamento encontrado para o periodo.")
        else:
            m1, m2, m3, m4, m5 = st.columns(5)
            for col_m, status_key in zip([m1, m2, m3, m4, m5], STATUS_AG.keys()):
                cnt = len(df_ag[df_ag["status"] == status_key])
                emoji, label = STATUS_AG[status_key][1], STATUS_AG[status_key][0]
                col_m.metric(f"{emoji} {label}", cnt)

            st.markdown("---")

            total_val = df_ag["valor"].fillna(0).sum()
            st.markdown(f"**Total do periodo:** {fmt_brl(total_val)}")
            st.markdown("---")

            # Cabecalho da tabela
            h1, h2, h3, h4, h5, h6, h7 = st.columns([3, 2, 2, 2, 2, 2, 1])
            h1.markdown("**Nome**")
            h2.markdown("**Convenio**")
            h3.markdown("**Data**")
            h4.markdown("**Medico**")
            h5.markdown("**Tipo**")
            h6.markdown("**Valor / Pagamento**")
            h7.markdown("**Status**")
            st.markdown("---")

            FORMAS_AG = ["", "Dinheiro", "PIX", "Cartao Debito", "Cartao Credito", "Convenio", "Cheque"]

            for _, row in df_ag.iterrows():
                ag_id = int(row["id"])
                status_k = row["status"]
                emoji_s = STATUS_AG.get(status_k, ("?","❓"))[1]
                data_fmt = row["data_hora"][:10] if row["data_hora"] else ""
                if data_fmt:
                    partes = data_fmt.split("-")
                    if len(partes) == 3:
                        data_fmt = f"{partes[2]}/{partes[1]}/{partes[0]}"
                valor_fmt = fmt_brl(row["valor"]) if row["valor"] else "—"
                forma_fmt = row["forma_pagamento"] or "—"

                c1, c2, c3, c4, c5, c6, c7 = st.columns([3, 2, 2, 2, 2, 2, 1])
                c1.write(row["paciente"] or "—")
                c2.write(row["convenio"] or "—")
                c3.write(data_fmt or "—")
                c4.write(row["medico"] or "—")
                c5.write(row["tipo_consulta"] or "—")
                c6.write(f"{valor_fmt} | {forma_fmt}")
                c7.write(emoji_s)

                # --- Pagamento ---
                ja_pago = status_k in ("realizado",)
                with st.expander("💳 Efetuar Pagamento" + (" ✅ Pago" if ja_pago else "")):
                    if ja_pago:
                        st.success("Este agendamento ja foi marcado como realizado.")
                    else:
                        banks_pag = get_banks(cid)
                        bank_opts_pag = {r["name"]: int(r["id"]) for _, r in banks_pag.iterrows()} if not banks_pag.empty else {}
                        formas_pag = ["Dinheiro", "PIX", "Cartao Debito", "Cartao Credito", "Convenio", "Cheque"]
                        forma_atual = row["forma_pagamento"] if row["forma_pagamento"] in formas_pag else "Dinheiro"

                        pp1, pp2, pp3 = st.columns(3)
                        with pp1:
                            p_forma = st.selectbox("Forma de Pagamento", formas_pag,
                                index=formas_pag.index(forma_atual), key=f"pf_{ag_id}")
                        with pp2:
                            p_banco = st.selectbox("Banco", list(bank_opts_pag.keys()), key=f"pb_{ag_id}") if bank_opts_pag else None
                        with pp3:
                            p_data = st.date_input("Data do Pagamento", value=date.today(), key=f"pd_{ag_id}")

                        eh_cartao_pag = p_forma in ("Cartao Debito", "Cartao Credito")

                        if eh_cartao_pag:
                            cf_pag = get_card_fees(cid)
                            band_opts_pag = sorted(cf_pag["card_type"].unique().tolist()) if not cf_pag.empty else ["credito_vista"]
                            pc1, pc2 = st.columns(2)
                            with pc1:
                                band_atual_pag = row.get("cartao_bandeira") or band_opts_pag[0]
                                band_idx_pag = band_opts_pag.index(band_atual_pag) if band_atual_pag in band_opts_pag else 0
                                p_bandeira = st.selectbox("Bandeira / Tipo", band_opts_pag, index=band_idx_pag, key=f"pband_{ag_id}")
                            with pc2:
                                p_parcelas = st.number_input("Numero de Parcelas", min_value=1, max_value=12,
                                    value=int(row.get("cartao_parcelas") or 1), step=1, key=f"pparc_{ag_id}")
                        else:
                            p_bandeira = None
                            p_parcelas = 1

                        with st.form(f"pag_ag_{ag_id}"):
                            p_valor = st.number_input("Valor Recebido (R$)",
                                value=float(row["valor"] or 0), min_value=0.0,
                                step=0.01, format="%.2f", key=f"pv_{ag_id}")
                            p_obs = st.text_input("Observacao (opcional)", key=f"po_{ag_id}")

                            if eh_cartao_pag:
                                cf_prev = get_card_fees(cid)
                                fee_prev = find_card_fee(cf_prev, p_bandeira or "")
                                taxa_prev = float(fee_prev.iloc[0]["fee_percent"]) if not fee_prev.empty else 0.0
                                dias_prev = int(fee_prev.iloc[0]["days_to_receive"]) if not fee_prev.empty else 30
                                n_prev = int(p_parcelas) if p_forma == "Cartao Credito" else 1
                                liq_prev = round(p_valor - p_valor * taxa_prev / 100, 2)
                                st.info(f"Taxa: {taxa_prev:.2f}% | Liquido: {fmt_brl(liq_prev)} | {n_prev}x de {fmt_brl(round(liq_prev/n_prev,2))} (~{dias_prev} dias)")

                            confirmar_pag = st.form_submit_button("✅ Confirmar Pagamento", type="primary")

                        if confirmar_pag:
                            bank_id_pag = bank_opts_pag.get(p_banco) if p_banco else None

                            if eh_cartao_pag:
                                import uuid as _uuid2
                                cf_pag2 = get_card_fees(cid)
                                fee_pag2 = find_card_fee(cf_pag2, p_bandeira or "")
                                taxa_pag2 = float(fee_pag2.iloc[0]["fee_percent"]) if not fee_pag2.empty else 0.0
                                dias_pag2 = int(fee_pag2.iloc[0]["days_to_receive"]) if not fee_pag2.empty else 30
                                n_pag2 = int(p_parcelas) if p_forma == "Cartao Credito" else 1
                                liq_pag2 = round(p_valor - p_valor * taxa_pag2 / 100, 2)
                                liq_p_pag2 = round(liq_pag2 / n_pag2, 2)
                                grupo_pag = str(_uuid2.uuid4())[:8]
                                for i in range(1, n_pag2 + 1):
                                    if p_forma == "Cartao Debito":
                                        dt_cx = (p_data + timedelta(days=dias_pag2)).strftime("%Y-%m-%d")
                                    else:
                                        dt_cx = (p_data + timedelta(days=dias_pag2 * i)).strftime("%Y-%m-%d")
                                    run("""INSERT INTO transactions
                                        (company_id, bank_id, type, description, amount,
                                         date_competencia, date_caixa, payment_method,
                                         status, installment_group, installment_num, installment_total, notes)
                                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                        (cid, bank_id_pag, "receita",
                                         f"{row['tipo_consulta'] or 'Consulta'} - {row['paciente']} ({p_forma} {i}/{n_pag2})",
                                         liq_p_pag2,
                                         p_data.strftime("%Y-%m-%d"), dt_cx,
                                         p_forma, "pendente",
                                         grupo_pag, i, n_pag2,
                                         p_obs or f"Taxa {taxa_pag2:.2f}%. Bruto: {fmt_brl(p_valor)}"))
                            else:
                                run("""INSERT INTO transactions
                                    (company_id, bank_id, type, description, amount,
                                     date_competencia, date_caixa, payment_method, status, notes)
                                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                                    (cid, bank_id_pag, "receita",
                                     f"{row['tipo_consulta'] or 'Consulta'} - {row['paciente']}",
                                     p_valor,
                                     p_data.strftime("%Y-%m-%d"), p_data.strftime("%Y-%m-%d"),
                                     p_forma, "pago",
                                     p_obs or ""))

                            run("UPDATE agendamentos SET status='realizado', forma_pagamento=?, valor=? WHERE id=?",
                                (p_forma, p_valor, ag_id))
                            st.success(f"Pagamento de {fmt_brl(p_valor)} registrado e lancado no financeiro!")
                            st.rerun()

                with st.expander("✏️ Editar / Excluir"):
                    try:
                        e_dt = datetime.strptime(row["data_hora"][:10], "%Y-%m-%d").date()
                    except:
                        e_dt = date.today()

                    e_forma_sel = st.selectbox(
                        "Forma de Pagamento", FORMAS_AG,
                        index=FORMAS_AG.index(row["forma_pagamento"]) if row["forma_pagamento"] in FORMAS_AG else 0,
                        key=f"ef_{ag_id}"
                    )
                    e_eh_cartao = e_forma_sel in ("Cartao Debito", "Cartao Credito")

                    if e_eh_cartao:
                        cf_edit = get_card_fees(cid)
                        bandeiras_edit = sorted(cf_edit["card_type"].unique().tolist()) if not cf_edit.empty else []
                        eb1, ep1 = st.columns(2)
                        with eb1:
                            band_atual = row.get("cartao_bandeira") or (bandeiras_edit[0] if bandeiras_edit else "")
                            band_idx = bandeiras_edit.index(band_atual) if band_atual in bandeiras_edit else 0
                            e_bandeira = st.selectbox("Bandeira / Tipo", bandeiras_edit if bandeiras_edit else ["credito_vista"], index=band_idx, key=f"eband_{ag_id}")
                        with ep1:
                            e_parcelas = st.number_input("Parcelas", min_value=1, max_value=12,
                                                          value=int(row.get("cartao_parcelas") or 1),
                                                          step=1, key=f"epapc_{ag_id}") if e_forma_sel == "Cartao Credito" else 1
                    else:
                        e_bandeira = None
                        e_parcelas = 1

                    with st.form(f"edit_ag_{ag_id}"):
                        ec1, ec2 = st.columns(2)
                        with ec1:
                            e_pac = st.text_input("Nome", value=row["paciente"] or "", key=f"ep_{ag_id}")
                            e_conv = st.text_input("Convenio", value=row["convenio"] or "", key=f"ec_{ag_id}")
                        with ec2:
                            e_med = st.text_input("Medico", value=row["medico"] or "", key=f"em_{ag_id}")
                            e_data = st.date_input("Data", value=e_dt, key=f"ed_{ag_id}")
                        ec3, ec4 = st.columns(2)
                        with ec3:
                            tipo_opts = ["Consulta", "Procedimento"]
                            tipo_idx = tipo_opts.index(row["tipo_consulta"]) if row["tipo_consulta"] in tipo_opts else 0
                            e_tipo = st.selectbox("Tipo", tipo_opts, index=tipo_idx, key=f"et_{ag_id}")
                        with ec4:
                            e_val = st.number_input("Valor Bruto (R$)", value=float(row["valor"] or 0), min_value=0.0, step=0.01, format="%.2f", key=f"ev_{ag_id}")

                        if e_eh_cartao and e_val > 0:
                            cf_ep = get_card_fees(cid)
                            fee_ep = find_card_fee(cf_ep, e_bandeira or "")
                            taxa_ep = float(fee_ep.iloc[0]["fee_percent"]) if not fee_ep.empty else 0.0
                            dias_ep = int(fee_ep.iloc[0]["days_to_receive"]) if not fee_ep.empty else 30
                            n_ep = int(e_parcelas) if e_forma_sel == "Cartao Credito" else 1
                            vl_ep = round(e_val - e_val * taxa_ep / 100, 2)
                            st.info(f"Taxa: {taxa_ep:.2f}% | Liquido: {fmt_brl(vl_ep)} | {n_ep}x de {fmt_brl(round(vl_ep/n_ep,2))} (~{dias_ep} dias)")

                        e_status = st.selectbox("Status", list(STATUS_AG.keys()),
                                                index=list(STATUS_AG.keys()).index(status_k) if status_k in STATUS_AG else 0,
                                                format_func=lambda s: STATUS_AG[s][1] + " " + STATUS_AG[s][0],
                                                key=f"es_{ag_id}")
                        col_btn1, col_btn2 = st.columns(2)
                        with col_btn1:
                            salvar_ed = st.form_submit_button("Salvar", type="primary")
                        with col_btn2:
                            excluir_ed = st.form_submit_button("Excluir")

                    if salvar_ed:
                        nova_dh = e_data.strftime("%Y-%m-%d") + " 08:00"
                        run("""UPDATE agendamentos SET paciente=?, medico=?,
                            data_hora=?, status=?, convenio=?,
                            tipo_consulta=?, valor=?, forma_pagamento=?,
                            cartao_bandeira=?, cartao_parcelas=? WHERE id=?""",
                            (e_pac, e_med, nova_dh, e_status, e_conv,
                             e_tipo, e_val, e_forma_sel,
                             e_bandeira, int(e_parcelas), ag_id))
                        st.success("Agendamento atualizado!")
                        st.rerun()
                    if excluir_ed:
                        run("DELETE FROM agendamentos WHERE id=?", (ag_id,))
                        st.warning("Agendamento excluido.")
                        st.rerun()

    with tab_import:
        st.subheader("Importar Agendamentos de Planilha")
        st.markdown("""
**Formatos aceitos:** `.xlsx`, `.xls`, `.csv`

A planilha precisa ter pelo menos as colunas de **nome do paciente** e **data**. As demais (medico, convenio, tipo, valor, forma de pagamento) são opcionais. Os nomes das colunas podem variar — o sistema detecta automaticamente.

**Exemplos de nomes aceitos para cada campo:**

| Campo | Nomes aceitos na planilha |
|---|---|
| Paciente | Paciente, Nome, PACIENTE, NOME |
| Data | Data, DATA, Data Agendamento, date |
| Medico | Medico, MEDICO, Profissional, Doctor |
| Convenio | Convenio, CONVENIO, Plano, PLANO |
| Tipo | Tipo, TIPO, Procedimento, PROCEDIMENTO |
| Valor | Valor, VALOR, Value, Preco |
| Pagamento | Pagamento, Forma Pagamento, FORMA PAGAMENTO |
| Status | Status, STATUS, Situacao |
        """)

        arquivo_import = st.file_uploader("Selecione o arquivo", type=["xlsx", "xls", "csv"], key="import_ag")

        if arquivo_import:
            try:
                nome_arq = arquivo_import.name.lower()
                if nome_arq.endswith(".csv"):
                    df_import = pd.read_csv(arquivo_import, encoding="utf-8-sig")
                elif nome_arq.endswith(".xlsx"):
                    df_import = pd.read_excel(arquivo_import, engine="openpyxl")
                else:
                    df_import = pd.read_excel(arquivo_import, engine="xlrd")

                # Normaliza nomes de colunas
                import unicodedata
                def norm_col(c):
                    c = str(c).strip().replace("\n", " ")
                    while "  " in c:
                        c = c.replace("  ", " ")
                    c = "".join(ch for ch in unicodedata.normalize("NFD", c) if unicodedata.category(ch) != "Mn")
                    return c.upper()
                df_import.columns = [norm_col(c) for c in df_import.columns]

                st.markdown(f"**{len(df_import)} linhas encontradas.** Colunas: `{', '.join(df_import.columns.tolist())}`")
                st.dataframe(df_import.head(5), use_container_width=True)

                # Mapeamento flexivel de colunas
                MAPA = {
                    "paciente":        ["PACIENTE", "NOME", "PATIENT", "NOME PACIENTE"],
                    "data_hora":       ["DATA", "DATA AGENDAMENTO", "DATA_AGENDAMENTO", "DATE", "DATA HORA", "DATA_HORA"],
                    "medico":          ["MEDICO", "PROFISSIONAL", "DOCTOR", "MEDICO(A)"],
                    "convenio":        ["CONVENIO", "PLANO", "CONVENIO PLANO", "PLANO SAUDE"],
                    "tipo_consulta":   ["TIPO", "PROCEDIMENTO", "TIPO CONSULTA", "TIPO_CONSULTA", "ESPECIALIDADE"],
                    "valor":           ["VALOR", "VALUE", "PRECO", "PRECO CONSULTA"],
                    "forma_pagamento": ["FORMA PAGAMENTO", "PAGAMENTO", "FORMA DE PAGAMENTO", "PAYMENT"],
                    "status":          ["STATUS", "SITUACAO", "SITUAÇÃO"],
                }
                col_map = {}
                for campo, opcoes in MAPA.items():
                    for op in opcoes:
                        if op in df_import.columns:
                            col_map[campo] = op
                            break

                STATUS_IMPORT = {
                    "confirmado": "confirmado", "confirmada": "confirmado",
                    "cancelado": "cancelado", "cancelada": "cancelado",
                    "realizado": "realizado", "realizada": "realizado",
                    "falta": "falta", "nao compareceu": "falta", "nao veio": "falta",
                    "agendado": "agendado", "agendada": "agendado",
                }

                if "paciente" not in col_map:
                    st.error("Coluna de paciente nao encontrada. Verifique o arquivo.")
                elif "data_hora" not in col_map:
                    st.error("Coluna de data nao encontrada. Verifique o arquivo.")
                else:
                    mapeado = {k: v for k, v in col_map.items()}
                    st.success(f"Colunas detectadas: {mapeado}")

                    if st.button("Importar agendamentos", type="primary", key="btn_import"):
                        inseridos = 0
                        erros = 0
                        for _, row_i in df_import.iterrows():
                            try:
                                paciente = str(row_i[col_map["paciente"]]).strip()
                                if not paciente or paciente.lower() == "nan":
                                    continue

                                data_val = row_i[col_map["data_hora"]]
                                if pd.isna(data_val):
                                    continue
                                if isinstance(data_val, str):
                                    data_hora_i = None
                                    for fmt in ["%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]:
                                        try:
                                            data_hora_i = datetime.strptime(data_val.strip(), fmt)
                                            break
                                        except:
                                            continue
                                    if not data_hora_i:
                                        erros += 1
                                        continue
                                else:
                                    data_hora_i = pd.Timestamp(data_val).to_pydatetime()

                                medico_i    = str(row_i.get(col_map.get("medico",""), "")).strip() if col_map.get("medico") else ""
                                convenio_i  = str(row_i.get(col_map.get("convenio",""), "")).strip() if col_map.get("convenio") else ""
                                tipo_i      = str(row_i.get(col_map.get("tipo_consulta",""), "")).strip() if col_map.get("tipo_consulta") else ""
                                valor_i     = float(row_i.get(col_map.get("valor",""), 0) or 0) if col_map.get("valor") else 0.0
                                forma_i     = str(row_i.get(col_map.get("forma_pagamento",""), "")).strip() if col_map.get("forma_pagamento") else ""
                                status_raw  = str(row_i.get(col_map.get("status",""), "agendado")).strip().lower() if col_map.get("status") else "agendado"
                                status_i    = STATUS_IMPORT.get(status_raw, "agendado")

                                for v in [medico_i, convenio_i, tipo_i, forma_i]:
                                    if v.lower() == "nan":
                                        v = ""
                                medico_i   = "" if medico_i.lower()   == "nan" else medico_i
                                convenio_i = "" if convenio_i.lower() == "nan" else convenio_i
                                tipo_i     = "" if tipo_i.lower()     == "nan" else tipo_i
                                forma_i    = "" if forma_i.lower()    == "nan" else forma_i

                                run("""INSERT INTO agendamentos
                                    (company_id, paciente, medico, data_hora, status,
                                     convenio, tipo_consulta, valor, forma_pagamento)
                                    VALUES (?,?,?,?,?,?,?,?,?)""",
                                    (cid, paciente,
                                     medico_i, data_hora_i.strftime("%Y-%m-%d %H:%M"),
                                     status_i, convenio_i, tipo_i, valor_i, forma_i or None))
                                inseridos += 1
                            except Exception:
                                erros += 1
                                continue

                        st.success(f"Importacao concluida! {inseridos} agendamentos importados. {erros} erros ignorados.")
                        st.rerun()

            except Exception as e:
                st.error(f"Erro ao ler o arquivo: {e}")
