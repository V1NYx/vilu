# database.py — Gerenciamento do banco de dados SQLite

import sqlite3

DB_PATH = 'vilu.db'


def get_db():
    """Abre e retorna uma conexão com o banco. Colunas acessadas por nome (row['campo'])."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def criar_tabelas():
    """Cria as tabelas do banco se não existirem. Seguro chamar múltiplas vezes."""
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            nome      TEXT NOT NULL,
            email     TEXT NOT NULL UNIQUE,
            senha     TEXT NOT NULL,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # UNIQUE(user_id, movie_id): cada usuário avalia cada filme apenas uma vez.
    # A rota /avaliar usa ON CONFLICT DO UPDATE para atualizar notas existentes.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS avaliacoes (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id  INTEGER NOT NULL,
            movie_id INTEGER NOT NULL,
            titulo   TEXT    NOT NULL,
            nota     REAL    NOT NULL CHECK(nota >= 0.5 AND nota <= 5.0),
            data     TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, movie_id)
        )
    """)

    # Comentários públicos exibidos no feed da comunidade.
    # Sem UNIQUE: o mesmo usuário pode comentar o mesmo filme mais de uma vez.
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
