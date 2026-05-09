import sqlite3

DB_PATH = 'vilu.db'


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def criar_tabelas():
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

    # UNIQUE(user_id, movie_id) garante uma avaliação por filme por usuário.
    # A rota /avaliar faz upsert via ON CONFLICT.
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


if __name__ == '__main__':
    criar_tabelas()
    print(f'Banco criado: {DB_PATH}')
