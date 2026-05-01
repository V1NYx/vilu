import sqlite3

# Caminho do banco de dados — fica na mesma pasta do projeto
DB_PATH = 'vilu.db'


def get_db():
    """Abre e retorna uma conexão com o banco de dados."""
    conn = sqlite3.connect(DB_PATH)
    # row_factory permite acessar colunas por nome: row['nome'] em vez de row[0]
    conn.row_factory = sqlite3.Row
    return conn


def criar_tabelas():
    """
    Cria todas as tabelas do banco se ainda não existirem.
    Seguro rodar múltiplas vezes — IF NOT EXISTS protege os dados.
    """
    conn = get_db()

    # Tabela de usuários: cadastros com senha criptografada
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            nome      TEXT    NOT NULL,
            email     TEXT    NOT NULL UNIQUE,
            senha     TEXT    NOT NULL,
            criado_em TEXT    DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Avaliações privadas: alimentam o XAI e as recomendações personalizadas
    # UNIQUE(user_id, movie_id): cada usuário avalia um filme apenas uma vez
    # ON CONFLICT DO UPDATE no app.py atualiza a nota em vez de rejeitar
    conn.execute("""
        CREATE TABLE IF NOT EXISTS avaliacoes (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER NOT NULL,
            movie_id  INTEGER NOT NULL,
            titulo    TEXT    NOT NULL,
            nota      REAL    NOT NULL CHECK(nota >= 0.5 AND nota <= 5.0),
            data      TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, movie_id)
        )
    """)

    # Comentários públicos: aparecem no feed da comunidade (página Principal)
    # Sem UNIQUE: o mesmo usuário pode comentar o mesmo filme mais de uma vez
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comentarios (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            movie_id   INTEGER NOT NULL,
            titulo     TEXT    NOT NULL,
            nota       REAL    CHECK(nota >= 0.5 AND nota <= 5.0),
            comentario TEXT    NOT NULL,
            data       TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()
    print(f"Banco criado em: {DB_PATH}")
    print("Tabelas: users, avaliacoes, comentarios")


if __name__ == '__main__':
    criar_tabelas()
