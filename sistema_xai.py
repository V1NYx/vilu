import re
import sqlite3
import pandas as pd
from database import get_db, DB_PATH


# Carregamento único ao importar — Flask não relê a cada requisição
filmes          = pd.read_csv('dataset/movies.csv')
notas_movielens = pd.read_csv('dataset/ratings.csv')

# Lookups rápidos para evitar split/map repetido por chamada
_generos_idx    = {r['title']: set(r['genres'].split('|')) for _, r in filmes.iterrows()}
_titulo_para_id = {r['title']: r['movieId']               for _, r in filmes.iterrows()}


def _notas_vilu():
    """
    Puxa as avaliações do banco e converte para o formato do ratings.csv.
    IDs de usuário recebem offset 100k para não colidir com os do MovieLens (1–610).
    Avaliações de filmes fora do dataset são ignoradas silenciosamente.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        df   = pd.read_sql("SELECT user_id, titulo, nota FROM avaliacoes", conn)
        conn.close()
    except Exception:
        return pd.DataFrame(columns=['userId', 'movieId', 'rating'])

    if df.empty:
        return pd.DataFrame(columns=['userId', 'movieId', 'rating'])

    df['userId']  = df['user_id'] + 100_000
    df['movieId'] = df['titulo'].map(_titulo_para_id)
    df = df.dropna(subset=['movieId'])
    df['movieId'] = df['movieId'].astype(int)
    df['rating']  = df['nota'].astype(float)
    return df[['userId', 'movieId', 'rating']]


def _build_matrix():
    """Constrói a matriz usuário×filme combinando MovieLens e avaliações do VILU."""
    notas = pd.concat([notas_movielens, _notas_vilu()], ignore_index=True)
    dados = pd.merge(notas, filmes, on='movieId')

    contagem  = dados.groupby('title')['rating'].count()
    populares = contagem[contagem > 50].index
    recorte   = dados[dados['title'].isin(populares)]

    matriz = recorte.pivot_table(index='userId', columns='title', values='rating')
    return matriz, dados, contagem


print('Carregando dados e construindo matriz...')
matriz_filmes, dados_completos, contagem_votos = _build_matrix()
print(f'Pronto — {matriz_filmes.shape[0]} usuários × {matriz_filmes.shape[1]} filmes')


def atualizar_matriz():
    """Reconstrói a matriz após uma nova avaliação ser salva no banco."""
    global matriz_filmes, dados_completos, contagem_votos
    matriz_filmes, dados_completos, contagem_votos = _build_matrix()


# ── helpers de gênero ─────────────────────────────────────────────────────────

def _jaccard(a, b):
    """Sobreposição de gêneros entre dois filmes (0 = nada em comum, 1 = idênticos)."""
    ga = _generos_idx.get(a, set())
    gb = _generos_idx.get(b, set())
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def _historico_relevante(historico, filme_ref, max_itens=2, min_generos=2):
    """
    Retorna filmes do histórico do usuário que tenham ao menos `min_generos`
    gêneros em comum com o filme de referência.

    min_generos=2 evita citações vagas — 'Drama' aparece em centenas de filmes,
    dois gêneros em comum já indica afinidade real.
    """
    gen_ref = _generos_idx.get(filme_ref, set())
    if not gen_ref:
        return []
    return [
        h for h in historico
        if len(_generos_idx.get(h['titulo'], set()) & gen_ref) >= min_generos
    ][:max_itens]


def _subir_sequencias(titulo_base, lista):
    """Move continuações da mesma franquia para o topo da lista de recomendações."""
    base = re.sub(r'\s*\(\d{4}\)', '', titulo_base).strip()
    base = re.sub(r'[\s,]+\d+$', '', base).strip()
    base = re.sub(r'\s+(I{1,3}|IV|V|VI{0,3}|IX|X)$', '', base, flags=re.IGNORECASE).strip()

    if len(base) < 3:
        return lista

    def eh_sequencia(titulo):
        t = re.sub(r'\s*\(\d{4}\)', '', titulo)
        return base.lower() in t.lower()

    sequencias = [r for r in lista if eh_sequencia(r['titulo'])]
    resto      = [r for r in lista if not eh_sequencia(r['titulo'])]
    return sequencias + resto


def buscar_historico_usuario(user_id):
    if not user_id:
        return []
    db   = get_db()
    rows = db.execute("""
        SELECT titulo, nota FROM avaliacoes
        WHERE user_id = ? AND nota >= 4.0
        ORDER BY nota DESC, data DESC
        LIMIT 10
    """, (user_id,)).fetchall()
    db.close()
    return [dict(r) for r in rows]


# ── algoritmos ────────────────────────────────────────────────────────────────

def recomendar_colaborativo(titulo, user_id=None, user_nome=None):
    """
    Filtragem colaborativa item-item com Pearson.

    Pega os 30 filmes mais correlacionados e os reranqueia por um score
    combinado: 60% correlação de Pearson + 40% sobreposição de gêneros (Jaccard).
    O componente de gênero corrige casos como Matrix → Toy Story, onde a
    correlação é espúria mas os públicos são totalmente distintos.
    """
    PESO_PEARSON = 0.6
    PESO_GENERO  = 0.4
    N_CANDIDATOS = 30

    vetor     = matriz_filmes[titulo]
    corr      = matriz_filmes.corrwith(vetor)
    df        = pd.DataFrame(corr, columns=['pearson']).dropna()
    df        = df.sort_values('pearson', ascending=False)
    candidatos = df.iloc[1:N_CANDIDATOS + 1].copy()

    candidatos['jaccard'] = candidatos.index.map(lambda t: _jaccard(titulo, t))
    candidatos['score']   = (
        PESO_PEARSON * candidatos['pearson'] +
        PESO_GENERO  * candidatos['jaccard']
    )

    top = candidatos.sort_values('score', ascending=False).head(8)
    recs = [{'titulo': r, 'modo': 'colaborativo'} for r in top.index]
    recs = _subir_sequencias(titulo, recs)

    historico  = buscar_historico_usuario(user_id)
    relevantes = _historico_relevante(historico, titulo)
    prefixo    = f'{user_nome}, ' if user_nome else ''

    xai = (
        f"{prefixo}'{titulo}' é popular aqui. "
        f"Analisei o padrão de avaliações e priorizei filmes de gênero parecido."
    )
    if relevantes:
        nomes  = ' e '.join(h['titulo'] for h in relevantes)
        comuns = _generos_idx.get(titulo, set()) & _generos_idx.get(relevantes[0]['titulo'], set())
        label  = ', '.join(sorted(comuns)) if comuns else 'parecidos'
        xai   += f" Você também gostou de {nomes} — filmes de {label} — o que reforça o perfil."

    return recs, xai


def recomendar_conteudo(titulo, dados_filme, user_id=None, user_nome=None):
    """
    Fallback para filmes com poucos dados (cold start).
    Busca por sobreposição de gêneros e ranqueia pelo Jaccard.
    """
    generos = set(dados_filme['genres'].split('|'))

    rec = filmes[filmes['genres'].apply(lambda g: bool(set(g.split('|')) & generos))]
    rec = rec[rec['title'] != titulo].copy()

    if rec.empty:
        rec = filmes[filmes['title'] != titulo].sample(min(8, len(filmes) - 1))
    else:
        rec['j'] = rec['genres'].apply(
            lambda g: len(set(g.split('|')) & generos) / len(set(g.split('|')) | generos)
        )
        rec = rec.sort_values('j', ascending=False).head(8)

    recs = [{'titulo': r, 'modo': 'conteudo'} for r in rec['title']]
    recs = _subir_sequencias(titulo, recs)

    historico  = buscar_historico_usuario(user_id)
    relevantes = _historico_relevante(historico, titulo)
    gen_str    = ', '.join(sorted(generos))
    prefixo    = f'{user_nome}, ' if user_nome else ''

    xai = (
        f"{prefixo}'{titulo}' tem poucos dados históricos aqui. "
        f"Busquei filmes com gêneros em comum [{gen_str}], priorizando maior sobreposição."
    )
    if relevantes:
        nomes = ', '.join(h['titulo'] for h in relevantes)
        xai  += f" Seu histórico ({nomes}) confirma interesse nesses gêneros."

    return recs, xai


def recomendar_hibrido(nome, user_id=None, user_nome=None):
    """
    Ponto de entrada principal — decide entre colaborativo e conteúdo.

    Retorna: (titulo, recomendacoes, explicacao, modo, erro)
    """
    busca = filmes[filmes['title'].str.contains(nome, case=False, na=False, regex=False)]

    if busca.empty:
        return None, [], '', '', 'Filme não encontrado. Tente o nome em inglês.'

    dados_filme = busca.iloc[0]
    titulo      = dados_filme['title']

    if titulo in matriz_filmes.columns:
        recs, xai = recomendar_colaborativo(titulo, user_id, user_nome)
        modo = 'colaborativo'
    else:
        recs, xai = recomendar_conteudo(titulo, dados_filme, user_id, user_nome)
        modo = 'conteudo'

    return titulo, recs, xai, modo, ''
