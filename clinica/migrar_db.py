"""Migração: adiciona colunas novas ao banco existente."""
import sqlite3, os

DB = os.path.join(os.path.dirname(__file__), 'clinica.db')
conn = sqlite3.connect(DB)
cur = conn.cursor()

def coluna_existe(tabela, coluna):
    cur.execute(f"PRAGMA table_info({tabela})")
    return any(row[1] == coluna for row in cur.fetchall())

def tabela_existe(tabela):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabela,))
    return cur.fetchone() is not None

alteracoes = []

# agendamentos: forma_pagamento, cartao_tipo, cartao_bandeira, cartao_parcelas
if tabela_existe('agendamentos') and not coluna_existe('agendamentos', 'forma_pagamento'):
    cur.execute("ALTER TABLE agendamentos ADD COLUMN forma_pagamento VARCHAR(50)")
    alteracoes.append('agendamentos.forma_pagamento')
if tabela_existe('agendamentos') and not coluna_existe('agendamentos', 'cartao_tipo'):
    cur.execute("ALTER TABLE agendamentos ADD COLUMN cartao_tipo VARCHAR(20)")
    alteracoes.append('agendamentos.cartao_tipo')
if tabela_existe('agendamentos') and not coluna_existe('agendamentos', 'cartao_bandeira'):
    cur.execute("ALTER TABLE agendamentos ADD COLUMN cartao_bandeira VARCHAR(50)")
    alteracoes.append('agendamentos.cartao_bandeira')
if tabela_existe('agendamentos') and not coluna_existe('agendamentos', 'cartao_parcelas'):
    cur.execute("ALTER TABLE agendamentos ADD COLUMN cartao_parcelas INTEGER DEFAULT 1")
    alteracoes.append('agendamentos.cartao_parcelas')
if tabela_existe('agendamentos') and not coluna_existe('agendamentos', 'conta_bancaria_id'):
    cur.execute("ALTER TABLE agendamentos ADD COLUMN conta_bancaria_id INTEGER REFERENCES contas_bancarias(id)")
    alteracoes.append('agendamentos.conta_bancaria_id')

# pagamentos_cartao: conta_id
if tabela_existe('pagamentos_cartao') and not coluna_existe('pagamentos_cartao', 'conta_id'):
    cur.execute("ALTER TABLE pagamentos_cartao ADD COLUMN conta_id INTEGER REFERENCES contas_bancarias(id)")
    alteracoes.append('pagamentos_cartao.conta_id')

# lancamentos_bancarios: conta_id e medico
if not coluna_existe('lancamentos_bancarios', 'conta_id'):
    cur.execute("ALTER TABLE lancamentos_bancarios ADD COLUMN conta_id INTEGER REFERENCES contas_bancarias(id)")
    alteracoes.append('lancamentos_bancarios.conta_id')

if not coluna_existe('lancamentos_bancarios', 'medico'):
    cur.execute("ALTER TABLE lancamentos_bancarios ADD COLUMN medico VARCHAR(200)")
    alteracoes.append('lancamentos_bancarios.medico')

if not coluna_existe('lancamentos_bancarios', 'forma_pagamento'):
    cur.execute("ALTER TABLE lancamentos_bancarios ADD COLUMN forma_pagamento VARCHAR(50)")
    alteracoes.append('lancamentos_bancarios.forma_pagamento')

# contas_receber: lancamento_id (pode já existir)
if tabela_existe('contas_receber') and not coluna_existe('contas_receber', 'lancamento_id'):
    cur.execute("ALTER TABLE contas_receber ADD COLUMN lancamento_id INTEGER REFERENCES lancamentos_bancarios(id)")
    alteracoes.append('contas_receber.lancamento_id')

# contas_pagar: forma_pagamento, conta_bancaria_id
if tabela_existe('contas_pagar') and not coluna_existe('contas_pagar', 'forma_pagamento'):
    cur.execute("ALTER TABLE contas_pagar ADD COLUMN forma_pagamento VARCHAR(50)")
    alteracoes.append('contas_pagar.forma_pagamento')
if tabela_existe('contas_pagar') and not coluna_existe('contas_pagar', 'conta_bancaria_id'):
    cur.execute("ALTER TABLE contas_pagar ADD COLUMN conta_bancaria_id INTEGER REFERENCES contas_bancarias(id)")
    alteracoes.append('contas_pagar.conta_bancaria_id')

# parcelas_cartao: lancamento_id
if tabela_existe('parcelas_cartao') and not coluna_existe('parcelas_cartao', 'lancamento_id'):
    cur.execute("ALTER TABLE parcelas_cartao ADD COLUMN lancamento_id INTEGER REFERENCES lancamentos_bancarios(id)")
    alteracoes.append('parcelas_cartao.lancamento_id')

conn.commit()
conn.close()

if alteracoes:
    print(f"Migração concluída. Colunas adicionadas: {', '.join(alteracoes)}")
else:
    print("Nada a migrar — banco já está atualizado.")
