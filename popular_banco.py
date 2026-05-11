"""
popular_banco.py — Popula o banco com 20 usuários e 10 avaliações cada.

Rodar UMA vez, após o banco já ter sido criado:
    python database.py   (se ainda não rodou)
    python popular_banco.py

Os usuários são criados com senha '123456' para facilitar os testes.
"""

import random
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
from werkzeug.security import generate_password_hash

DB_PATH = 'vilu.db'

# ── Usuários de teste ─────────────────────────────────────────────────────────

USUARIOS = [
    ('Ana Lima',        'ana.lima@email.com'),
    ('Bruno Carvalho',  'bruno.carvalho@email.com'),
    ('Camila Souza',    'camila.souza@email.com'),
    ('Diego Martins',   'diego.martins@email.com'),
    ('Eduarda Ferreira','eduarda.ferreira@email.com'),
    ('Felipe Rocha',    'felipe.rocha@email.com'),
    ('Gabriela Costa',  'gabriela.costa@email.com'),
    ('Henrique Alves',  'henrique.alves@email.com'),
    ('Isabela Nunes',   'isabela.nunes@email.com'),
    ('João Ribeiro',    'joao.ribeiro@email.com'),
    ('Karen Oliveira',  'karen.oliveira@email.com'),
    ('Lucas Pereira',   'lucas.pereira@email.com'),
    ('Marina Santos',   'marina.santos@email.com'),
    ('Nicolas Gomes',   'nicolas.gomes@email.com'),
    ('Olivia Mendes',   'olivia.mendes@email.com'),
    ('Pedro Araújo',    'pedro.araujo@email.com'),
    ('Quézia Barbosa',  'quezia.barbosa@email.com'),
    ('Rafael Torres',   'rafael.torres@email.com'),
    ('Sabrina Cardoso', 'sabrina.cardoso@email.com'),
    ('Thiago Rodrigues','thiago.rodrigues@email.com'),
]

# Perfis de gosto — cada usuário tem preferência por certos gêneros.
# Isso torna as avaliações mais realistas e melhora as correlações do modelo.

PERFIS = [
    ['Action', 'Thriller', 'Crime'],        # Ana
    ['Comedy', 'Romance', 'Drama'],         # Bruno
    ['Sci-Fi', 'Action', 'Adventure'],      # Camila
    ['Drama', 'Crime', 'Thriller'],         # Diego
    ['Animation', 'Comedy', 'Family'],      # Eduarda
    ['Horror', 'Thriller', 'Mystery'],      # Felipe
    ['Romance', 'Drama', 'Comedy'],         # Gabriela
    ['Action', 'Sci-Fi', 'Adventure'],      # Henrique
    ['Drama', 'War', 'History'],            # Isabela
    ['Comedy', 'Animation', 'Family'],      # João
    ['Crime', 'Drama', 'Thriller'],         # Karen
    ['Sci-Fi', 'Horror', 'Thriller'],       # Lucas
    ['Romance', 'Comedy', 'Drama'],         # Marina
    ['Action', 'Adventure', 'Fantasy'],     # Nicolas
    ['Drama', 'Romance', 'Biography'],      # Olivia
    ['Horror', 'Mystery', 'Thriller'],      # Pedro
    ['Comedy', 'Drama', 'Romance'],         # Quézia
    ['Sci-Fi', 'Action', 'Thriller'],       # Rafael
    ['Animation', 'Family', 'Adventure'],   # Sabrina
    ['Drama', 'Crime', 'Mystery'],          # Thiago
]


def _data_aleatoria():
    """Gera uma data aleatória entre 01/05/2025 e 10/05/2025."""
    inicio = datetime(2025, 5, 1)
    delta  = timedelta(days=random.randint(0, 9), hours=random.randint(8, 23), minutes=random.randint(0, 59))
    return (inicio + delta).strftime('%Y-%m-%d %H:%M:%S')


def filmes_para_perfil(df_filmes, generos_preferidos, n=10):
    """
    Seleciona n filmes que contenham ao menos um dos gêneros preferidos,
    priorizando filmes conhecidos (com mais avaliações no MovieLens).
    """
    mask = df_filmes['genres'].apply(
        lambda g: any(gen in g for gen in generos_preferidos)
    )
    candidatos = df_filmes[mask]

    # Prefere filmes clássicos/conhecidos — lista curada por popularidade
    populares = [
        'The Shawshank Redemption (1994)', 'Pulp Fiction (1994)',
        'The Dark Knight (2008)', 'Schindler\'s List (1993)',
        'The Silence of the Lambs (1991)', 'Forrest Gump (1994)',
        'The Matrix (1999)', 'Goodfellas (1990)', 'Fight Club (1999)',
        'The Lord of the Rings: The Fellowship of the Ring (2001)',
        'Star Wars: Episode IV - A New Hope (1977)', 'Inception (2010)',
        'The Godfather (1972)', 'Interstellar (2014)', 'Gladiator (2000)',
        'The Lion King (1994)', 'Toy Story (1995)', 'Finding Nemo (2003)',
        'Schindler\'s List (1993)', 'Saving Private Ryan (1998)',
        'Braveheart (1995)', 'The Usual Suspects (1995)',
        'Silence of the Lambs (1991)', 'Se7en (1995)', 'Cast Away (2000)',
        'American History X (1998)', 'Good Will Hunting (1997)',
        'Die Hard (1988)', 'Terminator 2: Judgment Day (1991)',
        'Raiders of the Lost Ark (1981)', 'Back to the Future (1985)',
        'The Truman Show (1998)', 'Eternal Sunshine of the Spotless Mind (2004)',
        'Memento (2000)', 'The Prestige (2006)', 'V for Vendetta (2005)',
        'Shrek (2001)', 'Monsters, Inc. (2001)', 'Up (2009)', 'WALL·E (2008)',
        'The Avengers (2012)', 'Iron Man (2008)', 'Spider-Man (2002)',
        'The Dark Knight Rises (2012)', 'Batman Begins (2005)',
        'Jurassic Park (1993)', 'Titanic (1997)', 'Avatar (2009)',
        'Harry Potter and the Sorcerer\'s Stone (2001)',
        'Pirates of the Caribbean: The Curse of the Black Pearl (2003)',
    ]

    # Filtra populares que estejam no perfil
    preferidos_pop = [t for t in populares if t in candidatos['title'].values]

    if len(preferidos_pop) >= n:
        return random.sample(preferidos_pop, n)

    # Completa com filmes aleatórios do perfil
    resto = candidatos[~candidatos['title'].isin(preferidos_pop)]['title'].tolist()
    random.shuffle(resto)
    return (preferidos_pop + resto)[:n]


def nota_para_perfil(titulo, generos_preferidos):
    """
    Gera uma nota realista:
    - Filmes do gênero preferido tendem a receber notas mais altas (3.5–5.0)
    - Outros recebem notas mais variadas (2.0–4.0)
    """
    try:
        filmes_df = pd.read_csv('dataset/movies.csv')
        row = filmes_df[filmes_df['title'] == titulo]
        if not row.empty:
            generos_filme = row.iloc[0]['genres']
            if any(g in generos_filme for g in generos_preferidos):
                nota = random.choice([3.5, 4.0, 4.0, 4.5, 4.5, 5.0])
            else:
                nota = random.choice([2.0, 2.5, 3.0, 3.5, 4.0])
            return nota
    except Exception:
        pass
    return random.choice([2.5, 3.0, 3.5, 4.0, 4.5])


def popular():
    random.seed(42)  # reprodutível — mesma execução sempre gera os mesmos dados

    try:
        filmes_df = pd.read_csv('dataset/movies.csv')
    except FileNotFoundError:
        print('Erro: dataset/movies.csv não encontrado.')
        print('Certifique-se de estar rodando na pasta do projeto.')
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    senha_hash = generate_password_hash('123456')

    criados    = 0
    avaliacoes = 0
    pulados    = 0

    for (nome, email), perfil in zip(USUARIOS, PERFIS):
        # Tenta inserir o usuário — pula se o email já existir
        try:
            cur = conn.execute(
                'INSERT INTO users (nome, email, senha, criado_em) VALUES (?, ?, ?, ?)',
                (nome, email, senha_hash, _data_aleatoria())
            )
            user_id = cur.lastrowid
            criados += 1
        except sqlite3.IntegrityError:
            user_id = conn.execute(
                'SELECT id FROM users WHERE email = ?', (email,)
            ).fetchone()['id']
            pulados += 1

        # Seleciona 10 filmes compatíveis com o perfil do usuário
        filmes_escolhidos = filmes_para_perfil(filmes_df, perfil, n=10)

        for titulo in filmes_escolhidos:
            row = filmes_df[filmes_df['title'] == titulo]
            if row.empty:
                continue

            movie_id = int(row.iloc[0]['movieId'])
            nota     = nota_para_perfil(titulo, perfil)

            try:
                conn.execute(
                    """
                    INSERT INTO avaliacoes (user_id, movie_id, titulo, nota, data)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, movie_id) DO NOTHING
                    """,
                    (user_id, movie_id, titulo, nota, _data_aleatoria())
                )
                avaliacoes += 1
            except Exception:
                pass

    conn.commit()
    conn.close()

    print(f'\nConcluído!')
    print(f'  Usuários criados: {criados}')
    print(f'  Usuários já existentes (pulados): {pulados}')
    print(f'  Avaliações inseridas: {avaliacoes}')
    print(f'\nSenha de todos os usuários: 123456')
    print(f'\nExemplos para testar:')
    for nome, email in USUARIOS[:5]:
        print(f'  {email}  /  123456')


# ── Comentários públicos para o feed ─────────────────────────────────────────

# Frases variadas por faixa de nota — tornam o feed mais natural
FRASES = {
    5.0: [
        "Um dos melhores filmes que já assisti. Recomendo muito.",
        "Simplesmente perfeito. Roteiro, atuações, tudo impecável.",
        "Obra-prima. Fica na memória por muito tempo.",
        "Assisti duas vezes e continua incrível. Vale cada minuto.",
        "Difícil encontrar algo tão bem feito. Nota máxima.",
    ],
    4.5: [
        "Muito bom, quase perfeito. Valeu muito a pena.",
        "Ótimo filme, me surpreendeu bastante.",
        "Excelente. Alguns detalhes poderiam ser melhores, mas no geral é nota 10.",
        "Super recomendo, especialmente pra quem curte o gênero.",
        "Muito bem produzido. Difícil parar de assistir.",
    ],
    4.0: [
        "Bom filme, gostei bastante. Vale a maratona.",
        "Bem produzido e com uma história envolvente.",
        "Gostei, mas esperava um pouco mais do final.",
        "Entretenimento de qualidade. Cumpre bem o que promete.",
        "Recomendo, principalmente se você curte esse estilo.",
    ],
    3.5: [
        "Razoável, tem seus momentos mas também algumas partes arrastadas.",
        "Assistir uma vez vale, mas não é imperdível.",
        "Tem pontos positivos, mas também me decepcionou em algumas cenas.",
        "Não é o melhor do gênero, mas passa bem.",
        "Mediano. Esperava mais dado o quanto falavam.",
    ],
    3.0: [
        "Não me empolgou muito, mas tem quem goste.",
        "Passei o tempo, mas não ficou na memória.",
        "Abaixo da expectativa. Mas tem seus fãs.",
        "Razoável. Dá pra assistir uma vez sem grandes arrependimentos.",
        "Não é ruim, mas também não é nada especial.",
    ],
}


def frase_para_nota(nota):
    """Retorna uma frase aleatória compatível com a nota dada."""
    chave = min(FRASES.keys(), key=lambda k: abs(k - nota))
    return random.choice(FRASES[chave])


def popular_comentarios():
    """
    Cada usuário publica comentários sobre alguns dos filmes que avaliou.
    Não todos — simula o comportamento real onde nem toda avaliação
    vira publicação pública.
    """
    random.seed(99)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Busca todas as avaliações já inseridas
    avaliacoes = conn.execute("""
        SELECT a.user_id, a.movie_id, a.titulo, a.nota
        FROM avaliacoes a
        JOIN users u ON a.user_id = u.id
        ORDER BY a.user_id
    """).fetchall()

    if not avaliacoes:
        print("Nenhuma avaliação encontrada. Rode popular() antes.")
        conn.close()
        return

    # Agrupa por usuário
    por_usuario = {}
    for av in avaliacoes:
        uid = av['user_id']
        if uid not in por_usuario:
            por_usuario[uid] = []
        por_usuario[uid].append(av)

    inseridos = 0
    for uid, avs in por_usuario.items():
        # Cada usuário comenta entre 4 e 7 dos seus filmes avaliados
        qtd       = random.randint(4, 7)
        escolhidos = random.sample(avs, min(qtd, len(avs)))

        for av in escolhidos:
            comentario = frase_para_nota(av['nota'])
            try:
                conn.execute(
                    """INSERT INTO comentarios (user_id, movie_id, titulo, nota, comentario, data)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (uid, av['movie_id'], av['titulo'], av['nota'], comentario, _data_aleatoria())
                )
                inseridos += 1
            except Exception:
                pass

    conn.commit()
    conn.close()
    print(f"  Comentários inseridos no feed: {inseridos}")


if __name__ == '__main__':
    popular()
    popular_comentarios()
