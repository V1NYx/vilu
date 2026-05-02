# app.py — Servidor principal do VILU (projeto acadêmico)
#
# Rotas:
#   /              → Busca e recomendações (primeira tela pós-login)
#   /principal     → Comunidade: feed + busca rápida
#   /buscar_filmes → Autocomplete de títulos em JSON (chamado pelo JS)
#   /detalhes/<f>  → Detalhes: XAI, avaliação privada, comentários
#   /avaliar       → Salva avaliação privada (POST)
#   /comentar      → Publica comentário no feed (POST)
#   /excluir_comentario/<id> → Remove comentário próprio (POST)
#   /perfil        → Histórico do usuário logado
#   /usuario/<id>  → Perfil público de outro usuário

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
import requests, re, os

# Carrega variáveis de ambiente do arquivo .env (se existir)
# Instalar suporte: pip install python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_db, criar_tabelas
from auth import auth as auth_blueprint
from sistema_xai import (
    recomendar_hibrido, filmes, dados_completos,
    _generos_idx, buscar_historico_usuario,
    _historico_relevante, contagem_votos
)


# ── INICIALIZAÇÃO ─────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key  = os.getenv('SECRET_KEY', 'vilu-chave-secreta-troque-em-producao-2024')
app.register_blueprint(auth_blueprint)
criar_tabelas()

TMDB_API_KEY = os.getenv('TMDB_API_KEY', '417fbe5b98d6a5a1daff00dfc9a77915')

# Cache título → (sinopse, poster_url, titulo_ptbr)
# Evita chamadas repetidas ao TMDB para o mesmo filme
_cache_tmdb = {}


# ── DECORATOR ────────────────────────────────────────────────────────────────

def login_required(f):
    """Protege uma rota: redireciona para /login se não estiver autenticado."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


# ── TMDB ──────────────────────────────────────────────────────────────────────

def buscar_info_tmdb(titulo_movielens):
    """
    Busca sinopse, pôster e título PT-BR no TMDB.
    Remove o ano antes de buscar: 'Toy Story (1995)' → 'Toy Story'.
    Retorna: (sinopse, poster_url, titulo_ptbr)
    Resultado salvo no cache — sem repetição de requisições HTTP.
    """
    if titulo_movielens in _cache_tmdb:
        return _cache_tmdb[titulo_movielens]

    titulo_limpo = re.sub(r'\s*\(\d{4}\)', '', titulo_movielens).strip()
    params = {'api_key': TMDB_API_KEY, 'query': titulo_limpo, 'language': 'pt-BR'}

    try:
        resp = requests.get(
            'https://api.themoviedb.org/3/search/movie',
            params=params, timeout=5
        )
        if resp.status_code == 401:
            result = ('Chave da API TMDB inválida.', None, None)
        else:
            resultados = resp.json().get('results', [])
            if resultados:
                item    = resultados[0]
                sinopse = item.get('overview') or 'Sinopse não disponível em português.'
                path    = item.get('poster_path')
                result  = (
                    sinopse,
                    f'https://image.tmdb.org/t/p/w500{path}' if path else None,
                    item.get('title') or None
                )
            else:
                result = ('Sinopse não disponível.', None, None)
    except requests.exceptions.Timeout:
        result = ('Tempo de conexão esgotado.', None, None)
    except Exception as e:
        print(f'Erro TMDB: {e}')
        result = ('Sinopse não disponível.', None, None)

    _cache_tmdb[titulo_movielens] = result
    return result


# ── GRADE DE FILMES POPULARES (pré-carregada) ─────────────────────────────────
# Executada uma única vez ao iniciar o servidor, após buscar_info_tmdb definida.
# ThreadPoolExecutor paraleliza as 18 chamadas TMDB (~1-2s vs ~18s sequencial).

def _montar_destaque(titulo):
    """Monta o dicionário de um filme para a grade de populares."""
    _, poster, ptbr = buscar_info_tmdb(titulo)
    busca_f = filmes[filmes['title'] == titulo]
    generos = busca_f.iloc[0]['genres'].split('|')[:2] if len(busca_f) > 0 else []
    return {'titulo': titulo, 'titulo_ptbr': ptbr, 'poster': poster, 'generos': generos}

print("Pré-carregando grade de filmes populares...")
_top = contagem_votos.sort_values(ascending=False).head(18).index.tolist()
with ThreadPoolExecutor(max_workers=18) as _ex:
    _FILMES_DESTAQUE = list(_ex.map(_montar_destaque, _top))
print(f"Grade pronta: {len(_FILMES_DESTAQUE)} filmes.")


# ── XAI DE REFORÇO ────────────────────────────────────────────────────────────

def gerar_xai_detalhe(nome_filme, nota_usuario, user_id=None):
    """
    Texto XAI exibido na página de detalhes, próximo à sinopse.
    Cita filmes do histórico com ao menos 2 gêneros em comum.
    """
    generos_set = _generos_idx.get(nome_filme, set())
    generos_str = ', '.join(sorted(generos_set)) if generos_set else 'variados'
    xai         = f"Este filme pertence aos gêneros {generos_str}. "

    if user_id:
        historico  = buscar_historico_usuario(user_id)
        relevantes = _historico_relevante(historico, nome_filme)
        if relevantes:
            nomes = ' e '.join([h['titulo'] for h in relevantes])
            xai  += f"Como você avaliou bem {nomes}, o VILU identificou que este filme combina com o seu perfil."
        else:
            xai  += "Com base nas avaliações da comunidade, o VILU identificou que ele pode combinar com o seu perfil."
    else:
        xai += "Com base nas avaliações da comunidade, o VILU identificou que ele pode combinar com o seu perfil."

    if nota_usuario:
        xai += f" Você já avaliou com nota {nota_usuario} — essa avaliação alimenta suas recomendações futuras."

    return xai


# ── ROTA: AUTOCOMPLETE ────────────────────────────────────────────────────────

@app.route('/buscar_filmes')
@login_required
def buscar_filmes():
    """Retorna até 8 títulos que contêm o texto digitado. Usado pelo JS do autocomplete."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    return jsonify(
        filmes[filmes['title'].str.contains(q, case=False, na=False, regex=False)
        ]['title'].head(8).tolist()
    )


# ── ROTA: HOME ────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    """
    GET  → exibe a grade de filmes populares pré-carregada.
    POST → executa o motor de recomendação e exibe os resultados.
    """
    recomendacoes    = []
    explicacao       = ''
    filme_escolhido  = ''
    poster_principal = None
    modo = erro      = ''

    if request.method == 'POST':
        nome_digitado    = request.form.get('nome_filme', '').strip()
        user_id          = session.get('user_id')
        user_nome_sessao = session.get('user_nome', '')

        titulo_completo, recomendacoes, explicacao, modo, erro = \
            recomendar_hibrido(nome_digitado, user_id, user_nome_sessao)

        if titulo_completo:
            filme_escolhido        = titulo_completo
            _, poster_principal, _ = buscar_info_tmdb(titulo_completo)

    # Busca pôsteres das recomendações em paralelo
    def _enriquecer(rec):
        _, poster, ptbr = buscar_info_tmdb(rec['titulo'])
        return {**rec, 'poster': poster, 'titulo_ptbr': ptbr}

    with ThreadPoolExecutor(max_workers=8) as ex:
        recomendacoes_com_poster = list(ex.map(_enriquecer, recomendacoes))

    # Verifica se o usuário já avaliou o filme pesquisado
    nota_filme_pesquisado = None
    movie_id_pesquisado   = None
    if filme_escolhido:
        b = filmes[filmes['title'] == filme_escolhido]
        if len(b) > 0:
            movie_id_pesquisado = int(b.iloc[0]['movieId'])
            db  = get_db()
            row = db.execute(
                'SELECT nota FROM avaliacoes WHERE user_id = ? AND movie_id = ?',
                (session.get('user_id'), movie_id_pesquisado)
            ).fetchone()
            db.close()
            if row:
                nota_filme_pesquisado = row['nota']

    return render_template('index.html',
        filme_escolhido       = filme_escolhido,
        lista_recomendacoes   = recomendacoes_com_poster,
        explicacao            = explicacao,
        modo                  = modo,
        erro                  = erro,
        poster_principal      = poster_principal,
        movie_id_pesquisado   = movie_id_pesquisado,
        nota_filme_pesquisado = nota_filme_pesquisado,
        filmes_destaque       = _FILMES_DESTAQUE,
        user_nome             = session.get('user_nome', '')
    )


# ── ROTA: PRINCIPAL (comunidade) ─────────────────────────────────────────────

@app.route('/principal')
@login_required
def principal():
    """Feed da comunidade com pôsteres buscados em paralelo."""
    db        = get_db()
    posts_raw = db.execute("""
        SELECT c.id, c.comentario, c.nota, c.titulo, c.movie_id, c.data,
               u.nome AS autor, u.id AS autor_id
        FROM comentarios c
        JOIN users u ON c.user_id = u.id
        ORDER BY c.data DESC LIMIT 100
    """).fetchall()
    db.close()

    def _enriquecer_post(p):
        _, poster, _ = buscar_info_tmdb(p['titulo'])
        return {**dict(p), 'poster_url': poster}

    with ThreadPoolExecutor(max_workers=10) as ex:
        posts = list(ex.map(_enriquecer_post, posts_raw))

    return render_template('principal.html',
        posts     = posts,
        user_nome = session.get('user_nome', ''),
        user_id   = session['user_id']
    )


# ── ROTA: DETALHES ────────────────────────────────────────────────────────────

@app.route('/detalhes/<path:nome_filme>')
@login_required
def detalhes(nome_filme):
    """Exibe pôster, sinopse, XAI de reforço, avaliação e comentários do filme."""
    busca = filmes[filmes['title'] == nome_filme]
    if len(busca) == 0:
        return render_template('404.html', mensagem='Filme não encontrado.'), 404

    dados_filme   = busca.iloc[0]
    movie_id      = int(dados_filme['movieId'])
    generos_lista = dados_filme['genres'].split('|')

    nota_media = '-'
    if nome_filme in dados_completos['title'].values:
        media      = dados_completos[dados_completos['title'] == nome_filme]['rating'].mean()
        nota_media = f'{media:.2f}'

    user_id = session.get('user_id')
    db      = get_db()

    row          = db.execute(
        'SELECT nota FROM avaliacoes WHERE user_id = ? AND movie_id = ?',
        (user_id, movie_id)
    ).fetchone()
    nota_usuario = row['nota'] if row else None

    comentarios = db.execute("""
        SELECT c.id, c.comentario, c.nota, c.data,
               u.nome AS autor, u.id AS autor_id
        FROM comentarios c
        JOIN users u ON c.user_id = u.id
        WHERE c.movie_id = ?
        ORDER BY c.data DESC
    """, (movie_id,)).fetchall()
    db.close()

    sinopse, poster_url, titulo_ptbr = buscar_info_tmdb(nome_filme)

    return render_template('detalhes.html',
        titulo       = nome_filme,
        titulo_ptbr  = titulo_ptbr,
        movie_id     = movie_id,
        generos      = generos_lista,
        nota_media   = nota_media,
        sinopse      = sinopse,
        poster_url   = poster_url,
        nota_usuario = nota_usuario,
        comentarios  = comentarios,
        xai_detalhe  = gerar_xai_detalhe(nome_filme, nota_usuario, user_id),
        user_nome    = session.get('user_nome', ''),
        user_id      = user_id
    )


# ── ROTA: AVALIAR ─────────────────────────────────────────────────────────────

@app.route('/avaliar', methods=['POST'])
@login_required
def avaliar():
    """Salva ou atualiza a avaliação privada. ON CONFLICT atualiza nota existente."""
    movie_id = request.form.get('movie_id')
    titulo   = request.form.get('titulo')
    nota     = float(request.form.get('nota', 0))

    if not movie_id or not titulo or nota < 0.5:
        return redirect(url_for('home'))

    db = get_db()
    db.execute("""
        INSERT INTO avaliacoes (user_id, movie_id, titulo, nota)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, movie_id) DO UPDATE SET
            nota = excluded.nota, data = CURRENT_TIMESTAMP
    """, (session['user_id'], movie_id, titulo, nota))
    db.commit()
    db.close()
    return redirect(url_for('detalhes', nome_filme=titulo))


# ── ROTA: COMENTAR ────────────────────────────────────────────────────────────

@app.route('/comentar', methods=['POST'])
@login_required
def comentar():
    """Publica comentário no feed. Nota herdada da avaliação privada já salva."""
    movie_id   = request.form.get('movie_id')
    titulo     = request.form.get('titulo')
    comentario = request.form.get('comentario', '').strip()
    user_id    = session['user_id']

    if not comentario or not 3 <= len(comentario) <= 500:
        return redirect(url_for('detalhes', nome_filme=titulo))

    db  = get_db()
    row = db.execute(
        'SELECT nota FROM avaliacoes WHERE user_id = ? AND movie_id = ?',
        (user_id, movie_id)
    ).fetchone()

    db.execute("""
        INSERT INTO comentarios (user_id, movie_id, titulo, nota, comentario)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, movie_id, titulo, row['nota'] if row else None, comentario))
    db.commit()
    db.close()
    return redirect(url_for('detalhes', nome_filme=titulo))


# ── ROTA: EXCLUIR COMENTÁRIO ──────────────────────────────────────────────────

@app.route('/excluir_comentario/<int:comentario_id>', methods=['POST'])
@login_required
def excluir_comentario(comentario_id):
    """Remove comentário após verificar que pertence ao usuário logado."""
    db  = get_db()
    com = db.execute(
        'SELECT titulo, user_id FROM comentarios WHERE id = ?',
        (comentario_id,)
    ).fetchone()

    titulo = ''
    if com and com['user_id'] == session['user_id']:
        db.execute('DELETE FROM comentarios WHERE id = ?', (comentario_id,))
        db.commit()
        titulo = com['titulo']
    db.close()

    return redirect(
        url_for('detalhes', nome_filme=titulo) if titulo else url_for('principal')
    )


# ── ROTA: PERFIL ──────────────────────────────────────────────────────────────

@app.route('/perfil')
@login_required
def perfil():
    """Exibe avaliações privadas e publicações no feed do usuário logado."""
    user_id = session['user_id']
    db      = get_db()

    avaliacoes  = db.execute(
        'SELECT titulo, movie_id, nota, data FROM avaliacoes WHERE user_id = ? ORDER BY data DESC',
        (user_id,)
    ).fetchall()
    comentarios = db.execute(
        'SELECT id, titulo, nota, comentario, data FROM comentarios WHERE user_id = ? ORDER BY data DESC',
        (user_id,)
    ).fetchall()
    db.close()

    return render_template('perfil.html',
        avaliacoes  = avaliacoes,
        comentarios = comentarios,
        user_nome   = session.get('user_nome', ''),
        user_id     = user_id
    )


# ── ROTA: PERFIL PÚBLICO ──────────────────────────────────────────────────────

@app.route('/usuario/<int:uid>')
@login_required
def usuario_publico(uid):
    """Exibe o perfil público e publicações de outro usuário."""
    db      = get_db()
    usuario = db.execute(
        'SELECT id, nome, criado_em FROM users WHERE id = ?', (uid,)
    ).fetchone()

    if not usuario:
        return render_template('404.html', mensagem='Usuário não encontrado.'), 404

    comentarios = db.execute(
        'SELECT id, titulo, nota, comentario, data FROM comentarios WHERE user_id = ? ORDER BY data DESC',
        (uid,)
    ).fetchall()
    db.close()

    return render_template('usuario_publico.html',
        usuario     = usuario,
        comentarios = comentarios,
        user_nome   = session.get('user_nome', ''),
        user_id     = session['user_id']
    )


# ── ERRO 404 ──────────────────────────────────────────────────────────────────

@app.errorhandler(404)
def pagina_nao_encontrada(e):
    return render_template('404.html', mensagem='Página não encontrada.'), 404


if __name__ == '__main__':
    app.run(debug=True)
