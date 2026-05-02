# sistema_xai.py — Motor de recomendação híbrido com Explicabilidade (XAI)
#
# Algoritmos implementados:
#   1. Colaborativo → Correlação de Pearson + reranking por Jaccard de gêneros
#   2. Conteúdo     → Interseção de gêneros ranqueada por Jaccard (Cold Start)
#
# XAI: explicações personalizadas que citam apenas filmes do histórico do
# usuário com mínimo de 2 gêneros em comum com o filme buscado.

import pandas as pd
from database import get_db


# ── DADOS ─────────────────────────────────────────────────────────────────────
# Carregados uma única vez ao importar o módulo.
# O Flask reutiliza o processo — os CSVs não são relidos a cada requisição.

print("Carregando datasets MovieLens...")

filmes          = pd.read_csv('dataset/movies.csv')
notas           = pd.read_csv('dataset/ratings.csv')
dados_completos = pd.merge(notas, filmes, on='movieId')

# Conta avaliações por filme para filtrar ruído estatístico
contagem_votos       = dados_completos.groupby('title')['rating'].count()
filmes_populares_idx = contagem_votos[contagem_votos > 50].index
dados_filtrados      = dados_completos[dados_completos['title'].isin(filmes_populares_idx)]

# Matriz Usuário × Filme: valores = notas, NaN = não assistiu
matriz_filmes = dados_filtrados.pivot_table(
    index='userId', columns='title', values='rating'
)

# Índice título → set de gêneros para consultas rápidas sem split repetido
_generos_idx = {
    row['title']: set(row['genres'].split('|'))
    for _, row in filmes.iterrows()
}

print(f"Pronto! {len(filmes)} filmes | {len(notas)} avaliações carregadas.")


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _sobreposicao(titulo_a, titulo_b):
    """
    Índice de Jaccard entre os gêneros de dois filmes.
    Retorna: 0.0 (nenhum gênero em comum) a 1.0 (conjuntos idênticos).
    Fórmula: |A ∩ B| / |A ∪ B|
    """
    gen_a = _generos_idx.get(titulo_a, set())
    gen_b = _generos_idx.get(titulo_b, set())
    if not gen_a or not gen_b:
        return 0.0
    return len(gen_a & gen_b) / len(gen_a | gen_b)


def _historico_relevante(historico, titulo_busca, max_itens=2, min_generos=2):
    """
    Filtra o histórico do usuário mantendo apenas filmes com pelo menos
    `min_generos` gêneros em comum com o filme buscado.

    Padrão min_generos=2: evita citações sem relação temática real.
    Ex: Toy Story (Animation|Comedy) vs Matrix (Action|Sci-Fi) → 0 em comum → não citado.
    """
    gen_busca = _generos_idx.get(titulo_busca, set())
    if not gen_busca:
        return []
    return [
        h for h in historico
        if len(_generos_idx.get(h['titulo'], set()) & gen_busca) >= min_generos
    ][:max_itens]


def _priorizar_sequencias(titulo_busca, recomendacoes):
    """
    Move sequências e filmes da mesma franquia para o topo da lista.
    Extrai o título base (sem ano e sem número final) e verifica
    quais candidatos o contêm.
    Ex: 'Toy Story (1995)' → base 'Toy Story' → Toy Story 2 e 3 sobem.
    """
    import re as _re

    base = _re.sub(r'\s*\(\d{4}\)', '', titulo_busca).strip()
    base = _re.sub(r'[\s,]+\d+$', '', base).strip()
    base = _re.sub(r'\s+(I{1,3}|IV|V|VI{0,3}|IX|X)$', '', base, flags=_re.IGNORECASE).strip()

    if len(base) < 3:
        return recomendacoes

    sequencias, outros = [], []
    for rec in recomendacoes:
        candidato = _re.sub(r'\s*\(\d{4}\)', '', rec['titulo'])
        if base.lower() in candidato.lower():
            sequencias.append(rec)
        else:
            outros.append(rec)

    return sequencias + outros


def buscar_historico_usuario(user_id):
    """Retorna os filmes avaliados com nota >= 4.0 pelo usuário logado."""
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


# ── ALGORITMO 1: FILTRAGEM COLABORATIVA ──────────────────────────────────────

def recomendar_colaborativo(titulo_completo, user_id=None, user_nome=None):
    """
    Fase 1 — Pearson: calcula corrwith() e seleciona os 30 mais correlacionados.
    Fase 2 — Reranking: score = (0.6 × Pearson) + (0.4 × Jaccard de gêneros).
                        Garante que Matrix não sugira Toy Story.
    Fase 3 — XAI: explicação personalizada com histórico do usuário.
    """
    PESO_PEARSON   = 0.6
    PESO_GENERO    = 0.4
    TOP_CANDIDATOS = 30

    notas_filme = matriz_filmes[titulo_completo]
    similares   = matriz_filmes.corrwith(notas_filme)

    corr_df    = pd.DataFrame(similares, columns=['Correlacao']).dropna()
    corr_df    = corr_df.sort_values('Correlacao', ascending=False)
    candidatos = corr_df.iloc[1: TOP_CANDIDATOS + 1].copy()  # exclui o próprio filme

    candidatos['Jaccard'] = candidatos.index.map(
        lambda t: _sobreposicao(titulo_completo, t)
    )
    candidatos['Score'] = (
        PESO_PEARSON * candidatos['Correlacao'] +
        PESO_GENERO  * candidatos['Jaccard']
    )

    top_8 = candidatos.sort_values('Score', ascending=False).head(8)

    recomendacoes = [
        {'titulo': row.name, 'modo': 'colaborativo'}
        for _, row in top_8.iterrows()
    ]
    recomendacoes = _priorizar_sequencias(titulo_completo, recomendacoes)

    # XAI
    historico  = buscar_historico_usuario(user_id)
    relevantes = _historico_relevante(historico, titulo_completo)
    prefixo    = f"{user_nome}, " if user_nome else ""

    explicacao = (
        f"{prefixo}'{titulo_completo}' é popular em nossa base. "
        f"Analisei o padrão de avaliações de outros usuários "
        f"e priorizei filmes de gêneros similares nas sugestões abaixo."
    )
    if relevantes:
        nomes      = ' e '.join([h['titulo'] for h in relevantes])
        gen_comuns = (_generos_idx.get(titulo_completo, set()) &
                      _generos_idx.get(relevantes[0]['titulo'], set()))
        gen_str    = ', '.join(sorted(gen_comuns)) if gen_comuns else 'similares'
        explicacao += (
            f" Você também gostou de {nomes} — filmes de {gen_str} — "
            f"o que reforça esse perfil."
        )

    return recomendacoes, explicacao


# ── ALGORITMO 2: FILTRAGEM POR CONTEÚDO (Cold Start) ─────────────────────────

def recomendar_conteudo(titulo_completo, dados_filme, user_id=None, user_nome=None):
    """
    Usado quando o filme tem menos de 50 avaliações (Cold Start).
    Busca filmes com ao menos 1 gênero em comum, ranqueados por Jaccard.
    """
    generos_busca = set(dados_filme['genres'].split('|'))

    rec = filmes[filmes['genres'].apply(
        lambda g: bool(set(g.split('|')) & generos_busca)
    )]
    rec = rec[rec['title'] != titulo_completo].copy()

    if rec.empty:
        rec = filmes[filmes['title'] != titulo_completo].sample(min(8, len(filmes) - 1))
    else:
        rec['jaccard'] = rec['genres'].apply(
            lambda g: len(set(g.split('|')) & generos_busca) /
                      len(set(g.split('|')) | generos_busca)
        )
        rec = rec.sort_values('jaccard', ascending=False).head(8)

    recomendacoes = [
        {'titulo': row['title'], 'modo': 'conteudo'}
        for _, row in rec.iterrows()
    ]
    recomendacoes = _priorizar_sequencias(titulo_completo, recomendacoes)

    # XAI
    historico   = buscar_historico_usuario(user_id)
    relevantes  = _historico_relevante(historico, titulo_completo)
    generos_str = ', '.join(sorted(generos_busca))
    prefixo     = f"{user_nome}, " if user_nome else ""

    explicacao = (
        f"{prefixo}'{titulo_completo}' tem poucos dados históricos na nossa base. "
        f"Por isso, busquei filmes com gêneros em comum [{generos_str}], "
        f"priorizando os com maior sobreposição."
    )
    if relevantes:
        nomes = ', '.join([h['titulo'] for h in relevantes])
        explicacao += f" Seu histórico ({nomes}) confirma interesse nesses gêneros."

    return recomendacoes, explicacao


# ── ORQUESTRADOR HÍBRIDO ──────────────────────────────────────────────────────

def recomendar_hibrido(nome_entrada, user_id=None, user_nome=None):
    """
    Decide qual algoritmo usar e retorna a tupla:
    (titulo, recomendacoes, explicacao, modo, erro)

    Regra: filme com > 50 avaliações → Colaborativo; senão → Conteúdo.
    """
    busca = filmes[
        filmes['title'].str.contains(nome_entrada, case=False, na=False, regex=False)
    ]

    if len(busca) == 0:
        return None, [], '', '', 'Filme não encontrado. Tente o nome em inglês.'

    dados_filme     = busca.iloc[0]
    titulo_completo = dados_filme['title']

    if titulo_completo in matriz_filmes.columns:
        recs, exp = recomendar_colaborativo(titulo_completo, user_id, user_nome)
        modo = 'colaborativo'
    else:
        recs, exp = recomendar_conteudo(titulo_completo, dados_filme, user_id, user_nome)
        modo = 'conteudo'

    return titulo_completo, recs, exp, modo, ''
