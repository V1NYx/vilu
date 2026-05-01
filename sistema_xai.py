"""
sistema_xai.py
Motor de recomendação híbrido com camada de Explicabilidade (XAI).

Algoritmos usados:
  1. Filtragem Colaborativa  → Correlação de Pearson entre vetores de notas
                               + reranking por sobreposição de gêneros
  2. Filtragem por Conteúdo  → Interseção de gêneros (fallback Cold Start)
  3. XAI Personalizado       → Histórico filtrado por gênero relevante

Mudanças desta versão:
  - Colaborativo agora re-ranqueia o top-20 de Pearson priorizando gêneros
    compartilhados com o filme buscado (Matrix não sugere Toy Story)
  - Filtragem por conteúdo usa interseção de gêneros em vez de igualdade exata
  - XAI só cita filmes do histórico que compartilham ao menos 1 gênero com
    o filme buscado (evita citar Toy Story ao buscar The Dark Knight)
  - Feed simplificado: comentário herda a avaliação já salva pelo usuário
"""

import pandas as pd
from database import get_db


# ── CARREGAMENTO DOS DADOS ────────────────────────────────────────────────────

print("Carregando datasets MovieLens...")

filmes = pd.read_csv('dataset/movies.csv')
notas  = pd.read_csv('dataset/ratings.csv')

dados_completos = pd.merge(notas, filmes, on='movieId')

contagem_votos = dados_completos.groupby('title')['rating'].count()

filmes_populares_idx = contagem_votos[contagem_votos > 50].index
dados_filtrados = dados_completos[
    dados_completos['title'].isin(filmes_populares_idx)
]

matriz_filmes = dados_filtrados.pivot_table(
    index='userId', columns='title', values='rating'
)

# Índice rápido: título → set de gêneros (usado no reranking e XAI)
# Ex: 'The Matrix (1999)' → {'Action', 'Sci-Fi', 'Thriller'}
_generos_idx = {
    row['title']: set(row['genres'].split('|'))
    for _, row in filmes.iterrows()
}

print(f"Pronto! {len(filmes)} filmes | {len(notas)} avaliações carregadas.")


# ── HELPERS DE GÊNERO ─────────────────────────────────────────────────────────


def _sobreposicao(titulo_a, titulo_b):
    """
    Calcula a sobreposição de gêneros entre dois filmes (índice Jaccard).
    Retorna valor entre 0.0 (nenhum gênero em comum) e 1.0 (idênticos).

    Jaccard = |A ∩ B| / |A ∪ B|

    Exemplos:
      Matrix (Action|Sci-Fi) vs Matrix Reloaded (Action|Sci-Fi) → 1.0
      Matrix (Action|Sci-Fi) vs Star Trek (Action|Adventure|Sci-Fi) → 0.67
      Matrix (Action|Sci-Fi) vs Toy Story (Animation|Comedy) → 0.0
    """
    gen_a = _generos_idx.get(titulo_a, set())
    gen_b = _generos_idx.get(titulo_b, set())
    if not gen_a or not gen_b:
        return 0.0
    return len(gen_a & gen_b) / len(gen_a | gen_b)


# ── HISTÓRICO DO USUÁRIO LOGADO ───────────────────────────────────────────────

def buscar_historico_usuario(user_id):
    """
    Busca no banco SQLite as avaliações do usuário logado,
    filtrando apenas notas >= 4.0 (filmes que ele gostou).
    Retorna lista de dicionários: [{'titulo': '...', 'nota': 4.5}, ...]
    """
    if not user_id:
        return []

    db = get_db()
    rows = db.execute("""
        SELECT titulo, nota
        FROM avaliacoes
        WHERE user_id = ? AND nota >= 4.0
        ORDER BY nota DESC, data DESC
        LIMIT 10
    """, (user_id,)).fetchall()
    db.close()

    return [dict(r) for r in rows]


def _historico_relevante(historico, titulo_busca, max_itens=2):
    """
    NOVO: Filtra o histórico do usuário mantendo apenas filmes que
    compartilham pelo menos 1 gênero com o filme buscado.

    Problema anterior: usuário gostou de Toy Story e Shrek (animação).
    Ao buscar Matrix (ação/ficção), o XAI citava Toy Story como reforço
    — o que não faz sentido temático.

    Agora: só cita filmes do histórico com gênero relevante para a busca.
    Se nenhum histórico for relevante, retorna lista vazia (XAI não cita).
    """
    gen_busca = _generos_idx.get(titulo_busca, set())
    if not gen_busca:
        return []

    relevantes = [
        h for h in historico
        if _generos_idx.get(h['titulo'], set()) & gen_busca
        # interseção não vazia = pelo menos 1 gênero em comum
    ]

    return relevantes[:max_itens]


# ── ALGORITMO 1: FILTRAGEM COLABORATIVA COM RERANKING POR GÊNERO ─────────────

def recomendar_colaborativo(titulo_completo, user_id=None):
    """
    Fase 1 — Pearson:
      Calcula corrwith() e pega o top-20 mais correlacionados.
      Usar top-20 em vez de top-5 dá margem para o reranking filtrar.

    Fase 2 — Reranking por gênero (NOVO):
      Para cada candidato do top-20, calcula um score combinado:
        score = (peso_pearson * correlacao) + (peso_genero * jaccard)

      peso_pearson = 0.6  → Pearson ainda domina (comportamento coletivo)
      peso_genero  = 0.4  → gênero penaliza filmes muito díspares

      Isso faz Matrix Reloaded (Action|Sci-Fi, Pearson 0.82) superar
      Toy Story (Animation|Comedy, Pearson 0.75) mesmo com correlação menor.

    Fase 3 — XAI:
      Cita apenas filmes do histórico com gênero relevante ao filme buscado.
    """
    PESO_PEARSON = 0.6
    PESO_GENERO  = 0.4
    TOP_CANDIDATOS = 20   # pega mais candidatos para o reranking escolher

    notas_filme = matriz_filmes[titulo_completo]
    similares   = matriz_filmes.corrwith(notas_filme)

    corr_df = pd.DataFrame(similares, columns=['Correlacao']).dropna()
    corr_df = corr_df.sort_values(by='Correlacao', ascending=False)

    # Top-20 candidatos (excluindo o próprio filme no índice 0)
    candidatos = corr_df.iloc[1: TOP_CANDIDATOS + 1]

    # ── Reranking: adiciona coluna de score combinado ──
    candidatos = candidatos.copy()
    candidatos['Jaccard'] = candidatos.index.map(
        lambda t: _sobreposicao(titulo_completo, t)
    )
    candidatos['Score'] = (
        PESO_PEARSON * candidatos['Correlacao'] +
        PESO_GENERO  * candidatos['Jaccard']
    )

    # Reordena pelo score combinado e pega os 5 melhores
    top_5 = candidatos.sort_values('Score', ascending=False).head(5)

    recomendacoes = [
        {
            'titulo':    row.name,
            'confianca': f"{row['Correlacao'] * 100:.1f}%",
            'jaccard':   f"{row['Jaccard']:.2f}",
            'modo':      'colaborativo'
        }
        for _, row in top_5.iterrows()
    ]

    # ── XAI ──
    historico  = buscar_historico_usuario(user_id)
    relevantes = _historico_relevante(historico, titulo_completo)

    explicacao = (
        f"'{titulo_completo}' é popular em nossa base. "
        f"Analisei o padrão de avaliações de outros usuários "
        f"e priorizei filmes de gêneros similares nas sugestões abaixo."
    )

    if relevantes:
        nomes = ' e '.join([h['titulo'] for h in relevantes])
        gen_comuns = _generos_idx.get(titulo_completo, set()) & \
                     _generos_idx.get(relevantes[0]['titulo'], set())
        gen_str = ', '.join(sorted(gen_comuns)) if gen_comuns else 'similares'
        explicacao += (
            f" Você também gostou de {nomes} — filmes de {gen_str} — "
            f"o que reforça esse perfil de preferências."
        )

    return recomendacoes, explicacao


# ── ALGORITMO 2: FILTRAGEM POR CONTEÚDO — INTERSEÇÃO DE GÊNEROS ──────────────

def recomendar_conteudo(titulo_completo, dados_filme, user_id=None):
    """
    MELHORADO: usa interseção de gêneros em vez de igualdade exata.

    Problema anterior: 'Adventure|Comedy' == 'Adventure|Comedy' apenas.
    'Comedy' ou 'Comedy|Adventure' não eram encontrados.

    Agora: qualquer filme com pelo menos 1 gênero em comum é candidato.
    Os candidatos são ranqueados pelo índice de Jaccard (mais sobreposição = melhor).
    """
    generos_busca = set(dados_filme['genres'].split('|'))

    # Filtra filmes com ao menos 1 gênero em comum
    def tem_genero_comum(row_genres):
        return bool(set(row_genres.split('|')) & generos_busca)

    rec = filmes[filmes['genres'].apply(tem_genero_comum)]
    rec = rec[rec['title'] != titulo_completo].copy()

    if rec.empty:
        # Fallback final: pega filmes aleatórios se não achar nada
        rec = filmes[filmes['title'] != titulo_completo].sample(
            min(5, len(filmes) - 1)
        )
    else:
        # Ranqueia por Jaccard decrescente
        rec['jaccard'] = rec['genres'].apply(
            lambda g: len(set(g.split('|')) & generos_busca) /
                      len(set(g.split('|')) | generos_busca)
        )
        rec = rec.sort_values('jaccard', ascending=False).head(5)

    recomendacoes = [
        {
            'titulo':    row['title'],
            'confianca': 'Por Gênero',
            'modo':      'conteudo'
        }
        for _, row in rec.iterrows()
    ]

    # ── XAI ──
    historico  = buscar_historico_usuario(user_id)
    relevantes = _historico_relevante(historico, titulo_completo)

    generos_formatados = ', '.join(sorted(generos_busca))
    explicacao = (
        f"'{titulo_completo}' tem poucos dados históricos na nossa base. "
        f"Por isso, busquei filmes com gêneros em comum [{generos_formatados}], "
        f"priorizando os com maior sobreposição de gêneros."
    )

    if relevantes:
        nomes = ', '.join([h['titulo'] for h in relevantes])
        explicacao += (
            f" Seu histórico ({nomes}) confirma interesse "
            f"nesses gêneros."
        )

    return recomendacoes, explicacao


# ── ORQUESTRADOR HÍBRIDO ──────────────────────────────────────────────────────

def recomendar_hibrido(nome_entrada, user_id=None):
    """
    Decide qual algoritmo usar:
      - Filme na matriz (> 50 votos) → Colaborativo + reranking por gênero
      - Senão                        → Conteúdo com interseção de gêneros
    """
    busca = filmes[filmes['title'].str.contains(nome_entrada, case=False, na=False)]

    if len(busca) == 0:
        return None, [], '', '', 'Filme não encontrado. Tente o nome em inglês.'

    dados_filme     = busca.iloc[0]
    titulo_completo = dados_filme['title']

    if titulo_completo in matriz_filmes.columns:
        recomendacoes, explicacao = recomendar_colaborativo(titulo_completo, user_id)
        modo = 'colaborativo'
    else:
        recomendacoes, explicacao = recomendar_conteudo(titulo_completo, dados_filme, user_id)
        modo = 'conteudo'

    return titulo_completo, recomendacoes, explicacao, modo, ''
